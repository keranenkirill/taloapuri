"""Tarjouspyynnöt: tarjousten tallennus sekä tekoälyn luonnos ja tarjousvertailu.

- Vain hallitus ja isännöitsijä (RLS + tarkistus täällä).
- Tekoäly ei valitse urakoitsijaa eikä lähetä mitään. Luonnos tallennetaan tarjouspyynnöksi vasta,
  kun ihminen painaa "Tallenna luonnos" (services/cases.save_tender_draft).
- Tekoälylle ei lähetetä hallituksen budjettimuistiinpanoa eikä henkilöiden nimiä.
- Jokainen tekoälyn väite viittaa lomakkeeseen tai tarjouksen sivuun ja viite tarkistetaan.
"""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from taloapuri.ai.citations import CitableBlock, CitableSource, resolve_all, to_documents
from taloapuri.ai.events import StreamEvent, stream_model
from taloapuri.ai.prompts import (
    OFFER_COMPARE_PROMPT,
    OFFER_COMPARE_VERSION,
    TENDER_DRAFT_PROMPT,
    TENDER_DRAFT_VERSION,
)
from taloapuri.ai.provider import AiProvider, AiResult, AiUnavailable
from taloapuri.auth import CompanyContext
from taloapuri.config import Settings
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import AiRun, Case
from taloapuri.services import cases as case_svc
from taloapuri.services.audit import write_audit
from taloapuri.services.chat import estimate_cost, month_cost
from taloapuri.services.documents import MAX_BYTES, PDF_MAGIC, safe_filename
from taloapuri.sources.pdf_text import extract_pages

MAX_OFFERS = 5
MAX_TOTAL_PAGES = 30


class NotAllowed(Exception):
    pass


class NotFound(Exception):
    pass


class TenderError(Exception):
    """Selkokielinen virhe käyttäjälle."""


@dataclass
class OfferRow:
    id: uuid.UUID
    contractor_name: str
    total_price: Decimal | None
    uploaded_by_name: str
    filename: str
    size_bytes: int
    page_count: int


@dataclass
class OfferFile:
    filename: str
    content: bytes


@dataclass
class AiOutput:
    id: uuid.UUID
    kind: str
    text: str
    segments: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    created_by_name: str
    created_at: Any


def _require_board(ctx: CompanyContext) -> None:
    if not (ctx.roles & ROLES_SEEING_ALL_CASES):
        raise NotAllowed


def ensure_tender(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> None:
    """Nostaa NotAllowed/NotFound, jos käyttäjä ei saa käsitellä tarjouspyyntöä."""
    _tender(db, ctx, case_id)


def _tender(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> Case:
    _require_board(ctx)
    try:
        case = case_svc.get_case(db, ctx, case_id)
    except case_svc.CaseNotFound as exc:
        raise NotFound(case_id) from exc
    if case.case_type != "tender_request":
        raise NotFound(case_id)
    return case


# --- Tarjoukset ---


def upload_offer(
    db: Session,
    ctx: CompanyContext,
    case_id: uuid.UUID,
    *,
    contractor_name: str,
    total_price: str,
    filename: str,
    data: bytes,
) -> uuid.UUID:
    _tender(db, ctx, case_id)
    contractor_name = contractor_name.strip()
    if not contractor_name:
        raise TenderError("Kirjoita urakoitsijan nimi.")
    if len(contractor_name) > 200:
        raise TenderError("Urakoitsijan nimi on liian pitkä.")
    price: Decimal | None = None
    if total_price.strip():
        try:
            price = Decimal(total_price.replace(" ", "").replace(",", ".").replace("€", ""))
        except InvalidOperation as exc:
            raise TenderError("Anna hinta numerona, esimerkiksi 12 500,00.") from exc
    if not data:
        raise TenderError("Valitse tarjouksen PDF-tiedosto.")
    if len(data) > MAX_BYTES:
        raise TenderError("Tiedosto on liian suuri. Enimmäiskoko on 10 Mt.")
    if not data.startswith(PDF_MAGIC):
        raise TenderError("Tiedosto ei ole PDF. Tallenna tarjous PDF-muodossa.")
    existing = list_offers(db, ctx, case_id)
    if len(existing) >= MAX_OFFERS * 2:
        raise TenderError("Tarjouksia on jo liikaa yhteen tarjouspyyntöön.")

    offer_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO tender_offers (id, housing_company_id, case_id, contractor_name,"
            " total_price, uploaded_by, uploaded_by_name, filename, size_bytes, sha256)"
            " VALUES (:id, :c, :case, :name, :price, :by, :by_name, :fn, :size, :sha)"
        ),
        {
            "id": offer_id,
            "c": ctx.company_id,
            "case": case_id,
            "name": contractor_name,
            "price": price,
            "by": ctx.user_id,
            "by_name": ctx.user_name or "Käyttäjä",
            "fn": safe_filename(filename),
            "size": len(data),
            "sha": hashlib.sha256(data).hexdigest(),
        },
    )
    db.execute(
        text(
            "INSERT INTO tender_offer_files (offer_id, housing_company_id, content)"
            " VALUES (:id, :c, :content)"
        ),
        {"id": offer_id, "c": ctx.company_id, "content": data},
    )
    pages = [
        {"o": offer_id, "c": ctx.company_id, "n": n, "t": t}
        for n, t in enumerate(extract_pages(data), start=1)
        if t.strip()
    ]
    if pages:
        db.execute(
            text(
                "INSERT INTO tender_offer_pages (offer_id, housing_company_id, page_no, text)"
                " VALUES (:o, :c, :n, :t)"
            ),
            pages,
        )
    write_audit(db, ctx, "tender.offer_uploaded", "case", case_id, pages=len(pages))
    return offer_id


def list_offers(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> list[OfferRow]:
    rows = db.execute(
        text(
            "SELECT o.id, o.contractor_name, o.total_price, o.uploaded_by_name, o.filename,"
            " o.size_bytes, (SELECT count(*) FROM tender_offer_pages p WHERE p.offer_id = o.id)"
            " FROM tender_offers o"
            " WHERE o.case_id = :case AND o.housing_company_id = :c AND o.removed_at IS NULL"
            " ORDER BY o.created_at"
        ),
        {"case": case_id, "c": ctx.company_id},
    ).all()
    return [OfferRow(*r) for r in rows]


def get_offer_file(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, offer_id: uuid.UUID
) -> OfferFile:
    row = db.execute(
        text(
            "SELECT o.filename, f.content FROM tender_offers o"
            " JOIN tender_offer_files f ON f.offer_id = o.id"
            " WHERE o.id = :id AND o.case_id = :case AND o.housing_company_id = :c"
            " AND o.removed_at IS NULL"
        ),
        {"id": offer_id, "case": case_id, "c": ctx.company_id},
    ).first()
    if row is None:
        raise NotFound(offer_id)
    return OfferFile(filename=row[0], content=bytes(row[1]))


def remove_offer(db: Session, ctx: CompanyContext, case_id: uuid.UUID, offer_id: uuid.UUID) -> None:
    _tender(db, ctx, case_id)
    result = db.execute(
        text(
            "UPDATE tender_offers SET removed_at = now() WHERE id = :id AND case_id = :case"
            " AND housing_company_id = :c AND removed_at IS NULL"
        ),
        {"id": offer_id, "case": case_id, "c": ctx.company_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound(offer_id)
    write_audit(db, ctx, "tender.offer_removed", "case", case_id)


# --- Tekoälyn tuotokset ---


def _form_source(case: Case, company_name: str) -> CitableSource:
    """Tarjouspyynnön lomaketiedot viitattavina lohkoina. Budjetti ja nimet jätetään pois."""
    d = case.details or {}
    fields = [
        ("Tilaaja", company_name),
        ("Kohde", d.get("target") or case.title),
        ("Työn laajuus", d.get("scope", "")),
        ("Kohde kiinteistössä", d.get("location_text", "")),
        ("Työ voi alkaa aikaisintaan", d.get("schedule_start") or ""),
        ("Työn on oltava valmis viimeistään", d.get("schedule_end") or ""),
        ("Tarjoukset viimeistään", d.get("offers_due") or ""),
        ("Vaatimukset urakoitsijalle", d.get("requirements", "")),
    ]
    blocks = [CitableBlock(f"{label}: {value}", None) for label, value in fields if value]
    if d.get("draft_text"):
        blocks.append(
            CitableBlock(f"Hallituksen tallentama tarjouspyyntöteksti:\n{d['draft_text']}", None)
        )
    return CitableSource(
        kind="form",
        label="Tarjouspyyntö",
        title=f"Tarjouspyynnön tiedot: {case.title}",
        context="Hallituksen täyttämä tarjouspyyntölomake.",
        link=None,
        blocks=blocks,
    )


def _offer_sources(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, offers: list[OfferRow]
) -> list[CitableSource]:
    sources = []
    for offer in offers:
        pages = db.execute(
            text(
                "SELECT page_no, text FROM tender_offer_pages WHERE offer_id = :o ORDER BY page_no"
            ),
            {"o": offer.id},
        ).all()
        sources.append(
            CitableSource(
                kind="offer",
                label=f"Tarjous: {offer.contractor_name}",
                title=f"Urakkatarjous: {offer.contractor_name}",
                context="Urakoitsijan tarjous. Lohkot ovat PDF:n sivut järjestyksessä.",
                link=f"/yhtiot/{ctx.company_id}/asiat/{case_id}/tarjoukset/{offer.id}/lataa",
                blocks=[CitableBlock(t, n) for n, t in pages],
            )
        )
    return sources


def _check_budget(db: Session, ctx: CompanyContext, settings: Settings) -> None:
    if month_cost(db, ctx) >= Decimal(str(settings.ai_monthly_budget_usd)):
        raise TenderError(
            "Tekoälyn kuukausikiintiö on täynnä. Voit silti kirjoittaa tarjouspyynnön itse."
        )


def _record(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    *,
    kind: str,
    prompt_version: str,
    result: AiResult | None,
    output_id: uuid.UUID | None,
    error: str | None = None,
) -> None:
    db.add(
        AiRun(
            housing_company_id=ctx.company_id,
            user_id=ctx.user_id,
            model=result.model if result else settings.ai_model,
            prompt_version=prompt_version,
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            cache_read_tokens=result.cache_read_tokens if result else 0,
            cache_write_tokens=result.cache_write_tokens if result else 0,
            cost_usd=estimate_cost(settings, result) if result else Decimal(0),
            stop_reason=result.stop_reason if result else None,
            latency_ms=result.latency_ms if result else None,
            request_id=result.request_id if result else None,
            error=error,
            kind=kind,
            output_id=output_id,
        )
    )
    db.flush()


def _run_events(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    case: Case,
    *,
    kind: str,
    system: str,
    prompt_version: str,
    sources: list[CitableSource],
    instruction: str,
) -> Iterator[StreamEvent]:
    if provider is None:
        raise TenderError("Tekoäly ei ole juuri nyt käytettävissä.")
    _check_budget(db, ctx, settings)
    yield StreamEvent("status", "Tekoäly kirjoittaa…")
    box: list[AiResult] = []
    try:
        yield from stream_model(
            provider,
            system,
            to_documents(sources),
            instruction,
            settings.ai_max_output_tokens_long,
            box,
        )
        result = box[0]
    except AiUnavailable as exc:
        _record(
            db,
            ctx,
            settings,
            kind=kind,
            prompt_version=prompt_version,
            result=None,
            output_id=None,
            error=exc.reason[:200],
        )
        raise TenderError("Tekoäly ei vastannut. Yritä hetken päästä uudelleen.") from exc
    if result.stop_reason == "refusal" or not any(s.text.strip() for s in result.segments):
        _record(
            db,
            ctx,
            settings,
            kind=kind,
            prompt_version=prompt_version,
            result=result,
            output_id=None,
        )
        raise TenderError("Tekoäly ei voinut tuottaa vastausta tähän pyyntöön.")
    yield StreamEvent("status", "Tarkistetaan lähdeviitteitä…")
    segments, resolved = resolve_all(sources, result)
    output_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO case_ai_outputs (id, housing_company_id, case_id, kind, created_by,"
            " created_by_name, text, segments, citations, model)"
            " VALUES (:id, :c, :case, :kind, :by, :by_name, :text, CAST(:seg AS jsonb),"
            " CAST(:cit AS jsonb), :model)"
        ),
        {
            "id": output_id,
            "c": ctx.company_id,
            "case": case.id,
            "kind": kind,
            "by": ctx.user_id,
            "by_name": ctx.user_name or "Käyttäjä",
            "text": "".join(s.text for s in result.segments),
            "seg": _json(segments),
            "cit": _json(
                [
                    {
                        "ord": c.ord,
                        "kind": c.kind,
                        "label": c.label,
                        "cited_text": c.cited_text,
                        "verified": c.verified,
                        "link": c.link,
                    }
                    for c in resolved
                ]
            ),
            "model": result.model,
        },
    )
    _record(
        db,
        ctx,
        settings,
        kind=kind,
        prompt_version=prompt_version,
        result=result,
        output_id=output_id,
    )
    write_audit(db, ctx, f"tender.ai_{kind}", "case", case.id)
    yield StreamEvent("done", ref_id=output_id)


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def generate_draft(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    case_id: uuid.UUID,
) -> uuid.UUID:
    return _last_done(generate_draft_events(db, ctx, settings, provider, case_id))


def compare_offers(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    case_id: uuid.UUID,
) -> uuid.UUID:
    return _last_done(compare_offers_events(db, ctx, settings, provider, case_id))


def _last_done(events: Iterator[StreamEvent]) -> uuid.UUID:
    done: uuid.UUID | None = None
    for event in events:
        if event.kind == "done":
            done = event.ref_id
    assert done is not None
    return done


def generate_draft_events(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    case_id: uuid.UUID,
) -> Iterator[StreamEvent]:
    case = _tender(db, ctx, case_id)
    source = _form_source(case, ctx.company_name)
    yield StreamEvent("status", "Luetaan tarjouspyynnön tiedot…")
    yield from _run_events(
        db,
        ctx,
        settings,
        provider,
        case,
        kind="tender_draft",
        system=TENDER_DRAFT_PROMPT,
        prompt_version=TENDER_DRAFT_VERSION,
        sources=[source],
        instruction="Laadi tarjouspyyntöluonnos yllä olevan lomakkeen tietojen perusteella.",
    )


def compare_offers_events(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    case_id: uuid.UUID,
) -> Iterator[StreamEvent]:
    case = _tender(db, ctx, case_id)
    offers = list_offers(db, ctx, case_id)
    readable = [o for o in offers if o.page_count > 0]
    if len(offers) < 2:
        raise TenderError("Vertailuun tarvitaan vähintään kaksi tarjousta.")
    if len(readable) < len(offers):
        names = ", ".join(o.contractor_name for o in offers if o.page_count == 0)
        raise TenderError(
            f"Tekoäly ei pysty lukemaan näitä tarjouksia (skannattu kuva?): {names}. "
            "Pyydä tarjous tekstimuotoisena PDF:nä tai poista se vertailusta."
        )
    if len(offers) > MAX_OFFERS:
        raise TenderError(f"Vertailuun voi ottaa enintään {MAX_OFFERS} tarjousta.")
    if sum(o.page_count for o in offers) > MAX_TOTAL_PAGES:
        raise TenderError(f"Tarjouksissa on yhteensä yli {MAX_TOTAL_PAGES} sivua.")
    yield StreamEvent("status", f"Luetaan {len(offers)} tarjousta…")
    sources = [_form_source(case, ctx.company_name), *_offer_sources(db, ctx, case_id, offers)]
    yield from _run_events(
        db,
        ctx,
        settings,
        provider,
        case,
        kind="offer_comparison",
        system=OFFER_COMPARE_PROMPT,
        prompt_version=OFFER_COMPARE_VERSION,
        sources=sources,
        instruction="Vertaile yllä olevia tarjouksia tarjouspyyntöön nähden.",
    )


def latest_output(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, kind: str
) -> AiOutput | None:
    row = db.execute(
        text(
            "SELECT id, kind, text, segments, citations, created_by_name, created_at"
            " FROM case_ai_outputs WHERE case_id = :case AND housing_company_id = :c"
            " AND kind = :k ORDER BY created_at DESC LIMIT 1"
        ),
        {"case": case_id, "c": ctx.company_id, "k": kind},
    ).first()
    return AiOutput(*row) if row else None
