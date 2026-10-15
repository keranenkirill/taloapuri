"""Usein kysytyt kysymykset: yleinen UKK (/ukk), yhtiön UKK ja isännöitsijän muokkaus."""

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession, OptionalUser
from taloapuri.services import faq as faq_svc
from taloapuri.services.sources import LawQuote, get_law_quote
from taloapuri.web.faq_content import FAQ_ENTRIES, GROUP_ORDER, FaqEntry, LawRef, front_page_entries
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)


@dataclass
class QuoteView:
    ref: LawRef
    quote: LawQuote | None
    stale: bool  # laki on päivittynyt yhteenvedon kirjoittamisen jälkeen


@dataclass
class EntryView:
    entry: FaqEntry
    quotes: list[QuoteView] = field(default_factory=list)
    login_needed: bool = False  # lakiviitteet näkyvät vain kirjautuneelle (lait luetaan RLS:n läpi)

    @property
    def unverified(self) -> bool:
        """Lakiväite, jonka lähdettä ei voitu hakea."""
        return any(q.quote is None for q in self.quotes)


def _view(entry: FaqEntry, db: Session | None) -> EntryView:
    view = EntryView(entry)
    if not entry.refs:
        return view
    if db is None:
        view.login_needed = True
        return view
    for ref in entry.refs:
        quote = get_law_quote(db, ref.source_key, ref.chapter, ref.section, ref.subsections)
        stale = quote is not None and quote.version_label != ref.verified_version
        view.quotes.append(QuoteView(ref, quote, stale))
    return view


def build_groups(db: Session | None) -> list[tuple[str, list[EntryView]]]:
    """Koko yleinen UKK ryhmiteltynä. db=None: lakiviitteitä ei haeta (ei kirjautunut)."""
    groups = []
    for name in GROUP_ORDER:
        entries = [_view(e, db) for e in FAQ_ENTRIES if e.group == name]
        if entries:
            groups.append((name, entries))
    return groups


def front_page_views() -> list[EntryView]:
    """Etusivun kysymykset: vain ilman lakiväitteitä (ei tietokantaa)."""
    return [EntryView(e) for e in front_page_entries()]


@router.get("/ukk", response_class=HTMLResponse)
def faq_public(request: Request, db: DbSession, me: OptionalUser) -> HTMLResponse:
    return render(
        request,
        "faq.html",
        {
            "me": me,
            "groups": build_groups(db if me is not None else None),
            "company_faq": [],
            "logged_in": me is not None,
        },
    )


@router.get("/yhtiot/{company_id}/ukk", response_class=HTMLResponse)
def faq_company(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    return render(
        request,
        "faq.html",
        {
            "ctx": ctx,
            "groups": build_groups(db),
            "company_faq": faq_svc.list_faq(db, ctx),
            "logged_in": True,
        },
    )


# --- Isännöitsijän muokkaus ---


def _require_manager(ctx: CompanyContext) -> None:
    if not ctx.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN)


def _edit_page(
    request: Request,
    ctx: CompanyContext,
    db: Session,
    *,
    errors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    edit_errors_for: uuid.UUID | None = None,
    notice: str = "",
    code: int = 200,
) -> HTMLResponse:
    return render(
        request,
        "faq_edit.html",
        {
            "ctx": ctx,
            "entries": faq_svc.list_faq(db, ctx),
            "errors": errors or {},
            "values": values or {},
            "edit_errors_for": edit_errors_for,
            "notice": notice,
        },
        code=code,
    )


@router.get("/yhtiot/{company_id}/ukk/muokkaa", response_class=HTMLResponse)
def faq_edit(request: Request, ctx: CompanyCtx, db: DbSession, viesti: str = "") -> HTMLResponse:
    _require_manager(ctx)
    notice = {
        "lisatty": "Kysymys on lisätty.",
        "tallennettu": "Muutokset on tallennettu.",
        "poistettu": "Kysymys on poistettu.",
    }.get(viesti, "")
    return _edit_page(request, ctx, db, notice=notice)


@router.post("/yhtiot/{company_id}/ukk")
def faq_add(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    question: Annotated[str, Form()] = "",
    answer: Annotated[str, Form()] = "",
    sort_order: Annotated[str, Form()] = "",
) -> Response:
    _require_manager(ctx)
    try:
        faq_svc.add_entry(db, ctx, question, answer, sort_order)
    except faq_svc.InvalidFaq as exc:
        return _edit_page(
            request,
            ctx,
            db,
            errors=exc.errors,
            values={"question": question, "answer": answer, "sort_order": sort_order},
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/ukk/muokkaa?viesti=lisatty",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/yhtiot/{company_id}/ukk/{entry_id}")
def faq_update(
    request: Request,
    entry_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    question: Annotated[str, Form()] = "",
    answer: Annotated[str, Form()] = "",
    sort_order: Annotated[str, Form()] = "",
) -> Response:
    _require_manager(ctx)
    try:
        faq_svc.update_entry(db, ctx, entry_id, question, answer, sort_order)
    except faq_svc.InvalidFaq as exc:
        return _edit_page(
            request,
            ctx,
            db,
            errors=exc.errors,
            values={"question": question, "answer": answer, "sort_order": sort_order},
            edit_errors_for=entry_id,
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except faq_svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/ukk/muokkaa?viesti=tallennettu",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/yhtiot/{company_id}/ukk/{entry_id}/poista", response_class=HTMLResponse)
def faq_delete_confirm(
    request: Request, entry_id: uuid.UUID, ctx: CompanyCtx, db: DbSession
) -> HTMLResponse:
    _require_manager(ctx)
    try:
        entry = faq_svc.get_entry(db, ctx, entry_id)
    except faq_svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return render(request, "faq_delete.html", {"ctx": ctx, "entry": entry})


@router.post("/yhtiot/{company_id}/ukk/{entry_id}/poista")
def faq_delete(entry_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> Response:
    _require_manager(ctx)
    try:
        faq_svc.delete_entry(db, ctx, entry_id)
    except faq_svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/ukk/muokkaa?viesti=poistettu",
        status_code=status.HTTP_303_SEE_OTHER,
    )
