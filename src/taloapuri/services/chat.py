"""Tekoälychat lain ja yhtiön pöytäkirjojen pohjalta (ks. docs/adr/0005 ja 0006).

Turvaraja:
- Tekoäly saa vain käyttäjän kysymyksen, julkiset lakitekstit ja ne hallituksen pöytäkirjat,
  jotka käyttäjä saa itsekin nähdä (RLS). Ei asioita, viestejä, kuvia eikä henkilörekisteriä.
- Tekoälyllä ei ole työkaluja: se ei voi lähettää, muuttaa eikä hakea mitään.
- Jokainen lähdeviite tarkistetaan: lainauksen on löydyttävä sanatarkasti viitatusta momentista.
- Kiintiöt: yhtiökohtainen kuukausibudjetti ja käyttäjäkohtainen päiväraja.
- Jos tekoäly ei ole käytössä tai ei vastaa, käyttäjä ohjataan ohjattuihin toimintoihin.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from taloapuri.ai.citations import CitableBlock, CitableSource, resolve_all, to_documents
from taloapuri.ai.events import StreamEvent, stream_model
from taloapuri.ai.prompts import ESCALATION_SENTENCE, PROMPT_VERSION, SYSTEM_PROMPT, wrap_question
from taloapuri.ai.provider import AiProvider, AiResult, AiUnavailable
from taloapuri.auth import CompanyContext
from taloapuri.config import Settings
from taloapuri.models import AiRun, ChatCitation, ChatMessage, ChatThread
from taloapuri.services.sources import (
    DocumentHit,
    SectionHit,
    search_company_documents,
    search_sections,
)

_WS = re.compile(r"\s+")

STATUS_MESSAGES_FI = {
    "unavailable": "Tekoäly ei ole juuri nyt käytettävissä. Voit silti hoitaa asian ohjatuilla "
    "toiminnoilla etusivulla.",
    "over_quota": "Tekoälyn käyttöraja on täynnä. Voit silti hoitaa asian ohjatuilla toiminnoilla "
    "etusivulla.",
    "no_sources": "En löytänyt kysymykseen liittyviä lainkohtia tai pöytäkirjoja. "
    "Kokeile kysyä toisin sanoin, "
    "esimerkiksi ”Kuka vastaa kylpyhuoneen lattiakaivosta?”.",
    "refused": "Tekoäly ei voinut vastata tähän kysymykseen. Kysy isännöitsijältä.",
}


class InvalidQuestion(Exception):
    pass


class ThreadNotFound(Exception):
    pass


@dataclass
class CitationView:
    ord: int
    label: str
    cited_text: str
    verified: bool
    public_url: str | None
    kind: str = "law"


@dataclass
class MessageView:
    role: str
    status: str
    text: str
    segments: list[dict[str, object]]
    created_at: datetime
    citations: list[CitationView]
    escalate: bool


def _norm(value: str) -> str:
    return _WS.sub(" ", value).strip()


def estimate_cost(settings: Settings, result: AiResult) -> Decimal:
    """Arvio dollareina. Välimuistin luku ~0,1× ja kirjoitus ~1,25× syötteen hinnasta."""
    per_in = Decimal(str(settings.ai_input_usd_per_mtok)) / Decimal(1_000_000)
    per_out = Decimal(str(settings.ai_output_usd_per_mtok)) / Decimal(1_000_000)
    return (
        result.input_tokens * per_in
        + result.cache_read_tokens * per_in * Decimal("0.1")
        + result.cache_write_tokens * per_in * Decimal("1.25")
        + result.output_tokens * per_out
    ).quantize(Decimal("0.000001"))


def month_cost(db: Session, ctx: CompanyContext) -> Decimal:
    value = db.execute(text("SELECT app_ai_month_cost(:c)"), {"c": ctx.company_id}).scalar_one()
    return Decimal(value)


def messages_today(db: Session, ctx: CompanyContext, settings: Settings) -> int:
    tz = ZoneInfo(settings.timezone)
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.housing_company_id == ctx.company_id,
                ChatMessage.user_id == ctx.user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= start,
            )
        ).scalar_one()
    )


def law_sources(hits: list[SectionHit]) -> list[CitableSource]:
    sources = []
    for hit in hits:
        heading = f" – {hit.section_heading}" if hit.section_heading else ""
        chapter = f"{hit.chapter_num} {hit.chapter_heading or ''}".strip()
        sources.append(
            CitableSource(
                kind="law",
                label=hit.citation_label,
                title=f"{hit.citation_label}{heading}",
                context=(
                    f"Laki: {', '.join(p for p in (hit.source_title, chapter) if p)}. "
                    f"Ajantasainen versio {hit.version_label}. "
                    "Lohkot ovat pykälän momentit järjestyksessä."
                ),
                link=hit.public_url,
                blocks=[CitableBlock(s.text, s.subsection_no, s.id) for s in hit.subsections],
            )
        )
    return sources


def minutes_sources(hits: list[DocumentHit], company_id: uuid.UUID) -> list[CitableSource]:
    sources = []
    for hit in hits:
        meeting = f", kokous {hit.meeting_date:%d.%m.%Y}" if hit.meeting_date else ""
        sources.append(
            CitableSource(
                kind="minutes",
                label=f"Pöytäkirja: {hit.title}",
                title=f"Taloyhtiön asiakirja: {hit.title}{meeting}",
                context=(
                    "Taloyhtiön hallituksen pöytäkirja (yhtiön oma asiakirja, ei laki). "
                    "Lohkot ovat PDF:n sivut järjestyksessä."
                ),
                link=f"/yhtiot/{company_id}/asiakirjat/{hit.id}/lataa",
                blocks=[CitableBlock(page_text, page_no) for page_no, page_text in hit.pages],
            )
        )
    return sources


def _list_threads_query(ctx: CompanyContext):  # type: ignore[no-untyped-def]
    return (
        select(ChatThread)
        .where(ChatThread.housing_company_id == ctx.company_id, ChatThread.user_id == ctx.user_id)
        .order_by(ChatThread.created_at.desc())
    )


def list_threads(db: Session, ctx: CompanyContext) -> list[ChatThread]:
    return list(db.execute(_list_threads_query(ctx).limit(20)).scalars())


def get_thread(db: Session, ctx: CompanyContext, thread_id: uuid.UUID) -> ChatThread:
    thread = db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.housing_company_id == ctx.company_id,
            ChatThread.user_id == ctx.user_id,
        )
    ).scalar_one_or_none()
    if thread is None:
        raise ThreadNotFound(thread_id)
    return thread


def _save_message(
    db: Session,
    ctx: CompanyContext,
    thread_id: uuid.UUID,
    role: str,
    message_text: str,
    status: str = "ok",
    segments: list[dict[str, object]] | None = None,
) -> ChatMessage:
    message = ChatMessage(
        id=uuid.uuid4(),
        housing_company_id=ctx.company_id,
        thread_id=thread_id,
        user_id=ctx.user_id,
        role=role,
        status=status,
        text=message_text,
        segments=segments or [],
    )
    db.add(message)
    db.flush()
    return message


def ask_events(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    question: str,
    thread_id: uuid.UUID | None = None,
) -> Iterator[StreamEvent]:
    """Tallentaa kysymyksen ja vastauksen; tuottaa etenemistapahtumat (viimeisenä "done")."""
    question = question.strip()
    if len(question) < 3:
        raise InvalidQuestion(
            "Kirjoita kysymys, esimerkiksi ”Kuka vastaa ikkunoiden korjaamisesta?”."
        )
    if len(question) > 1000:
        raise InvalidQuestion("Kysymys on liian pitkä. Käytä enintään 1000 merkkiä.")

    if thread_id is None:
        thread = ChatThread(
            id=uuid.uuid4(),
            housing_company_id=ctx.company_id,
            user_id=ctx.user_id,
            title=_norm(question)[:200],
        )
        db.add(thread)
        db.flush()
    else:
        thread = get_thread(db, ctx, thread_id)

    over_quota = messages_today(
        db, ctx, settings
    ) >= settings.ai_daily_messages_per_user or month_cost(db, ctx) >= Decimal(
        str(settings.ai_monthly_budget_usd)
    )
    _save_message(db, ctx, thread.id, "user", question)

    if provider is None:
        _save_message(
            db, ctx, thread.id, "assistant", STATUS_MESSAGES_FI["unavailable"], "unavailable"
        )
        yield StreamEvent("done", ref_id=thread.id)
        return
    if over_quota:
        _save_message(
            db, ctx, thread.id, "assistant", STATUS_MESSAGES_FI["over_quota"], "over_quota"
        )
        yield StreamEvent("done", ref_id=thread.id)
        return

    yield StreamEvent("status", "Haetaan lainkohtia ja pöytäkirjoja…")
    sources = law_sources(search_sections(db, question)) + minutes_sources(
        search_company_documents(db, ctx.company_id, question), ctx.company_id
    )
    if not sources:
        # Ei lähteitä → ei kutsuta tekoälyä lainkaan (ei arvailua, ei kustannuksia).
        _save_message(
            db, ctx, thread.id, "assistant", STATUS_MESSAGES_FI["no_sources"], "no_sources"
        )
        yield StreamEvent("done", ref_id=thread.id)
        return

    section_ids = [b.ref_id for s in sources for b in s.blocks if b.ref_id is not None]
    yield StreamEvent("status", f"Löytyi {len(sources)} lähdettä. Tekoäly kirjoittaa vastausta…")
    box: list[AiResult] = []
    try:
        yield from stream_model(
            provider, SYSTEM_PROMPT, to_documents(sources), wrap_question(question), None, box
        )
        result = box[0]
    except AiUnavailable as exc:
        message = _save_message(
            db, ctx, thread.id, "assistant", STATUS_MESSAGES_FI["unavailable"], "unavailable"
        )
        db.add(
            AiRun(
                housing_company_id=ctx.company_id,
                user_id=ctx.user_id,
                message_id=message.id,
                model=settings.ai_model,
                prompt_version=PROMPT_VERSION,
                section_ids=section_ids,
                error=exc.reason[:200],
            )
        )
        yield StreamEvent("done", ref_id=thread.id)
        return

    yield StreamEvent("status", "Tarkistetaan lähdeviitteitä…")
    refused = result.stop_reason == "refusal" or not any(s.text.strip() for s in result.segments)
    if refused:
        message = _save_message(
            db, ctx, thread.id, "assistant", STATUS_MESSAGES_FI["refused"], "refused"
        )
    else:
        segments, resolved = resolve_all(sources, result)
        message = _save_message(
            db,
            ctx,
            thread.id,
            "assistant",
            "".join(s.text for s in result.segments),
            "ok",
            segments,
        )
        for c in resolved:
            db.add(
                ChatCitation(
                    housing_company_id=ctx.company_id,
                    user_id=ctx.user_id,
                    message_id=message.id,
                    ord=c.ord,
                    source_section_id=c.ref_id,
                    citation_label=c.label,
                    cited_text=c.cited_text,
                    verified=c.verified,
                    source_kind=c.kind if c.kind != "unknown" else "law",
                    link=c.link,
                )
            )
    db.add(
        AiRun(
            housing_company_id=ctx.company_id,
            user_id=ctx.user_id,
            message_id=message.id,
            model=result.model,
            prompt_version=PROMPT_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
            cost_usd=estimate_cost(settings, result),
            section_ids=section_ids,
            stop_reason=result.stop_reason,
            latency_ms=result.latency_ms,
            request_id=result.request_id,
        )
    )
    db.flush()
    yield StreamEvent("done", ref_id=thread.id)


def ask(
    db: Session,
    ctx: CompanyContext,
    settings: Settings,
    provider: AiProvider | None,
    question: str,
    thread_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Sama kuin ask_events ilman striimausta. Palauttaa keskustelun tunnisteen."""
    done: uuid.UUID | None = None
    for event in ask_events(db, ctx, settings, provider, question, thread_id):
        if event.kind == "done":
            done = event.ref_id
    assert done is not None
    return done


def thread_messages(db: Session, ctx: CompanyContext, thread_id: uuid.UUID) -> list[MessageView]:
    get_thread(db, ctx, thread_id)
    messages = list(
        db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.thread_id == thread_id,
                ChatMessage.housing_company_id == ctx.company_id,
            )
            .order_by(ChatMessage.created_at, ChatMessage.role.desc())
        ).scalars()
    )
    citations = list(
        db.execute(
            select(ChatCitation)
            .where(ChatCitation.message_id.in_([m.id for m in messages]))
            .order_by(ChatCitation.ord)
        ).scalars()
    )
    urls: dict[uuid.UUID, str] = dict(
        db.execute(
            text(
                "SELECT s.id, src.public_url FROM source_sections s"
                " JOIN source_versions v ON v.id = s.version_id"
                " JOIN sources src ON src.id = v.source_id"
                " WHERE s.id = ANY(:ids)"
            ),
            {"ids": [c.source_section_id for c in citations if c.source_section_id]},
        ).all()
    )
    views = []
    for m in messages:
        own = [c for c in citations if c.message_id == m.id]
        views.append(
            MessageView(
                role=m.role,
                status=m.status,
                text=m.text,
                segments=m.segments,
                created_at=m.created_at,
                citations=[
                    CitationView(
                        ord=c.ord,
                        label=c.citation_label,
                        cited_text=c.cited_text,
                        verified=c.verified,
                        public_url=c.link
                        or (urls.get(c.source_section_id) if c.source_section_id else None),
                        kind=c.source_kind,
                    )
                    for c in own
                ],
                escalate=m.role == "assistant" and ESCALATION_SENTENCE in m.text,
            )
        )
    return views
