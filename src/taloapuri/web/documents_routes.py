"""Hallituksen pöytäkirjat: isännöitsijän lataussivu ja kaikkien jäsenten lataus (RLS rajaa)."""

import uuid
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession
from taloapuri.services import documents as svc
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)


def _require_manager(ctx: CompanyContext) -> None:
    if not ctx.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN)


def _page(
    request: Request,
    ctx: CompanyContext,
    db: DbSession,
    errors: dict[str, str],
    values: dict[str, object],
    notice: str = "",
    code: int = 200,
) -> HTMLResponse:
    return render(
        request,
        "documents.html",
        {
            "ctx": ctx,
            "documents": svc.list_documents(db, ctx),
            "errors": errors,
            "values": values,
            "notice": notice,
        },
        code=code,
    )


@router.get("/yhtiot/{company_id}/poytakirjat", response_class=HTMLResponse)
def documents_page(
    request: Request, ctx: CompanyCtx, db: DbSession, viesti: str = ""
) -> HTMLResponse:
    _require_manager(ctx)
    notice = {
        "ladattu": "Pöytäkirja on lisätty.",
        "nakyvyys": "Näkyvyys on muutettu.",
        "poistettu": "Pöytäkirja on poistettu näkyvistä.",
    }.get(viesti, "")
    return _page(request, ctx, db, {}, {"visible": False}, notice)


@router.post("/yhtiot/{company_id}/poytakirjat")
def upload_document(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str, Form()] = "",
    meeting_date: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    visible: Annotated[str | None, Form()] = None,
) -> Response:
    _require_manager(ctx)
    values: dict[str, object] = {
        "title": title,
        "meeting_date": meeting_date,
        "description": description,
        "visible": bool(visible),
    }
    errors: dict[str, str] = {}
    parsed_date: date | None = None
    if meeting_date:
        try:
            parsed_date = date.fromisoformat(meeting_date)
        except ValueError:
            errors["meeting_date"] = "Anna kokouspäivä muodossa vvvv-kk-pp."
    data = b""
    filename = ""
    if file is not None and file.filename:
        # Luetaan enintään raja + 1 tavu, jotta liian suuri tiedosto tunnistetaan.
        data = file.file.read(svc.MAX_BYTES + 1)
        filename = file.filename
    try:
        if errors:
            raise svc.InvalidUpload(errors)
        svc.upload_minutes(
            db,
            ctx,
            title=title,
            meeting_date=parsed_date,
            description=description,
            visible_to_residents=bool(visible),
            filename=filename,
            data=data,
        )
    except svc.InvalidUpload as exc:
        return _page(
            request,
            ctx,
            db,
            {**errors, **exc.errors},
            values,
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/poytakirjat?viesti=ladattu",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/yhtiot/{company_id}/poytakirjat/{document_id}/nakyvyys")
def change_visibility(
    document_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    visible: Annotated[str, Form()] = "0",
) -> Response:
    try:
        svc.set_visibility(db, ctx, document_id, visible == "1")
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/poytakirjat?viesti=nakyvyys",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/yhtiot/{company_id}/poytakirjat/{document_id}/poista")
def remove_document(document_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> Response:
    try:
        svc.remove(db, ctx, document_id)
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/poytakirjat?viesti=poistettu",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/yhtiot/{company_id}/asiakirjat/{document_id}/lataa")
def download_document(document_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> Response:
    try:
        doc = svc.get_file(db, ctx, document_id)
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return Response(
        content=doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
