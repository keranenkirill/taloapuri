"""Suorat viestit: /yhtiot/{id}/viestit."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import CompanyCtx, DbSession
from taloapuri.services import messages as svc
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)


@router.get("/yhtiot/{company_id}/viestit", response_class=HTMLResponse)
def inbox(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    return render(request, "messages.html", {"ctx": ctx, "threads": svc.list_threads(db, ctx)})


@router.get("/yhtiot/{company_id}/viestit/uusi", response_class=HTMLResponse)
def new_message_form(
    request: Request, ctx: CompanyCtx, db: DbSession, vastaanottaja: str = ""
) -> HTMLResponse:
    return render(
        request,
        "message_new.html",
        {
            "ctx": ctx,
            "contacts": svc.contacts(db, ctx),
            "values": {"recipient": vastaanottaja},
            "error": "",
        },
    )


@router.post("/yhtiot/{company_id}/viestit")
def send_new(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    recipient: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
) -> Response:
    try:
        recipient_id = uuid.UUID(recipient)
    except ValueError:
        recipient_id = uuid.UUID(int=0)
    try:
        thread_id = svc.start_thread(db, ctx, recipient_id, subject, body)
    except svc.InvalidMessage as exc:
        return render(
            request,
            "message_new.html",
            {
                "ctx": ctx,
                "contacts": svc.contacts(db, ctx),
                "values": {"recipient": recipient, "subject": subject, "body": body},
                "error": str(exc),
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/viestit/{thread_id}?lahetetty=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/yhtiot/{company_id}/viestit/{thread_id}", response_class=HTMLResponse)
def thread_page(
    request: Request, thread_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, lahetetty: int = 0
) -> HTMLResponse:
    try:
        subject = svc.get_thread_subject(db, ctx, thread_id)
        messages = svc.thread_messages(db, ctx, thread_id)
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return render(
        request,
        "message_thread.html",
        {
            "ctx": ctx,
            "thread_id": thread_id,
            "subject": subject,
            "messages": messages,
            "sent": bool(lahetetty),
            "error": "",
        },
    )


@router.post("/yhtiot/{company_id}/viestit/{thread_id}")
def send_reply(
    request: Request,
    thread_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    body: Annotated[str, Form()] = "",
) -> Response:
    try:
        svc.reply(db, ctx, thread_id, body)
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.InvalidMessage as exc:
        return render(
            request,
            "message_thread.html",
            {
                "ctx": ctx,
                "thread_id": thread_id,
                "subject": svc.get_thread_subject(db, ctx, thread_id),
                "messages": svc.thread_messages(db, ctx, thread_id),
                "sent": False,
                "error": str(exc),
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/viestit/{thread_id}?lahetetty=1#viimeisin",
        status_code=status.HTTP_303_SEE_OTHER,
    )
