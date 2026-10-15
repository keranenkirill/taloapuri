"""Tekoälychatin sivut: /yhtiot/{id}/kysy."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from taloapuri.ai.provider import AiProvider, AnthropicProvider
from taloapuri.auth import CompanyCtx, DbSession
from taloapuri.config import get_settings
from taloapuri.services import chat as svc
from taloapuri.services import law_admin
from taloapuri.sources.updater import SourceInfo
from taloapuri.web.streaming import stream_events
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)


def _active_laws(db: Session) -> list[SourceInfo]:
    return [s for s in law_admin.list_laws(db) if s.active]


def get_ai_provider() -> AiProvider | None:
    """None, jos tekoäly ei ole käytössä. Testit korvaavat tämän FakeProviderilla."""
    settings = get_settings()
    # Testeissä oikeaa tekoälyä ei koskaan käytetä (testit antavat FakeProviderin itse).
    if settings.env == "test" or not settings.ai_enabled or not settings.anthropic_api_key:
        return None
    return AnthropicProvider(settings)


Provider = Annotated[AiProvider | None, Depends(get_ai_provider)]


@router.get("/yhtiot/{company_id}/kysy", response_class=HTMLResponse)
def chat_home(request: Request, ctx: CompanyCtx, db: DbSession, provider: Provider) -> HTMLResponse:
    return render(
        request,
        "chat.html",
        {
            "ctx": ctx,
            "threads": svc.list_threads(db, ctx),
            "ai_available": provider is not None,
            "laws": _active_laws(db),
            "messages": [],
            "thread": None,
            "error": "",
            "question": "",
        },
    )


@router.post("/yhtiot/{company_id}/kysy")
def chat_ask(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    provider: Provider,
    question: Annotated[str, Form()] = "",
    thread_id: Annotated[str, Form()] = "",
) -> Response:
    try:
        parsed_thread = uuid.UUID(thread_id) if thread_id else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    try:
        new_thread = svc.ask(db, ctx, get_settings(), provider, question, parsed_thread)
    except svc.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.InvalidQuestion as exc:
        thread = svc.get_thread(db, ctx, parsed_thread) if parsed_thread else None
        return render(
            request,
            "chat.html",
            {
                "ctx": ctx,
                "threads": svc.list_threads(db, ctx),
                "ai_available": provider is not None,
                "laws": _active_laws(db),
                "messages": svc.thread_messages(db, ctx, thread.id) if thread else [],
                "thread": thread,
                "error": str(exc),
                "question": question,
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/kysy/{new_thread}#viimeisin",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/yhtiot/{company_id}/kysy/{thread_id}", response_class=HTMLResponse)
def chat_thread(
    request: Request, thread_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, provider: Provider
) -> HTMLResponse:
    try:
        thread = svc.get_thread(db, ctx, thread_id)
    except svc.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return render(
        request,
        "chat.html",
        {
            "ctx": ctx,
            "threads": svc.list_threads(db, ctx),
            "ai_available": provider is not None,
            "laws": _active_laws(db),
            "messages": svc.thread_messages(db, ctx, thread.id),
            "thread": thread,
            "error": "",
            "question": "",
        },
    )


@router.post("/yhtiot/{company_id}/kysy/stream")
def chat_ask_stream(
    ctx: CompanyCtx,
    provider: Provider,
    question: Annotated[str, Form()] = "",
    thread_id: Annotated[str, Form()] = "",
) -> Response:
    """Sama kuin chat_ask, mutta vastaus striimataan selaimeen sitä mukaa kuin se syntyy."""
    try:
        parsed_thread = uuid.UUID(thread_id) if thread_id else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    settings = get_settings()
    return stream_events(
        ctx,
        lambda db: svc.ask_events(db, ctx, settings, provider, question, parsed_thread),
        lambda ref: f"/yhtiot/{ctx.company_id}/kysy/{ref}#viimeisin",
        expected_errors=(svc.InvalidQuestion, svc.ThreadNotFound),
    )
