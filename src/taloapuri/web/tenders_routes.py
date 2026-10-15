"""Tarjouspyynnöt: luonnoksen tallennus (ihminen), tekoälyluonnos, tarjoukset ja vertailu."""

import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession
from taloapuri.config import get_settings
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import Case
from taloapuri.services import cases as svc
from taloapuri.services import tenders
from taloapuri.services.documents import MAX_BYTES
from taloapuri.web.chat_routes import Provider
from taloapuri.web.streaming import stream_events

router = APIRouter(include_in_schema=False)


def tender_context(db: Session, ctx: CompanyContext, case: Case) -> dict[str, Any]:
    """Asian sivun tarjouspyyntöosat. Tyhjä muille asiatyypeille."""
    if case.case_type != "tender_request" or not (ctx.roles & ROLES_SEEING_ALL_CASES):
        return {}
    return {
        "tender": True,
        "offers": tenders.list_offers(db, ctx, case.id),
        "draft_output": tenders.latest_output(db, ctx, case.id, "tender_draft"),
        "comparison": tenders.latest_output(db, ctx, case.id, "offer_comparison"),
    }


def _to_case(ctx: CompanyContext, case_id: uuid.UUID, query: str, anchor: str = "") -> Response:
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/asiat/{case_id}?{query}{anchor}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _error_page(
    request: Request, ctx: CompanyContext, db: Session, case_id: uuid.UUID, message: str
) -> Response:
    from taloapuri.web.cases_routes import case_page

    return case_page(
        request, ctx, db, case_id, error=message, code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/luonnos")
def save_draft(
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    expected_version: Annotated[int, Form()],
    draft_text: Annotated[str, Form()] = "",
) -> Response:
    try:
        svc.save_tender_draft(db, ctx, case_id, draft_text, expected_version)
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.VersionConflict:
        return _to_case(ctx, case_id, "virhe=versio")
    return _to_case(ctx, case_id, "tallennettu=1", "#luonnos")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/luonnos/tekoaly")
def ai_draft(
    request: Request, case_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, provider: Provider
) -> Response:
    try:
        tenders.generate_draft(db, ctx, get_settings(), provider, case_id)
    except tenders.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except tenders.TenderError as exc:
        return _error_page(request, ctx, db, case_id, str(exc))
    return _to_case(ctx, case_id, "luonnos=tekoaly", "#luonnos")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/tarjoukset")
def upload_offer(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    contractor_name: Annotated[str, Form()] = "",
    total_price: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> Response:
    data = file.file.read(MAX_BYTES + 1) if file is not None and file.filename else b""
    try:
        tenders.upload_offer(
            db,
            ctx,
            case_id,
            contractor_name=contractor_name,
            total_price=total_price,
            filename=file.filename or "" if file else "",
            data=data,
        )
    except tenders.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except tenders.TenderError as exc:
        return _error_page(request, ctx, db, case_id, str(exc))
    return _to_case(ctx, case_id, "tallennettu=1", "#tarjoukset")


@router.get("/yhtiot/{company_id}/asiat/{case_id}/tarjoukset/{offer_id}/lataa")
def download_offer(
    case_id: uuid.UUID, offer_id: uuid.UUID, ctx: CompanyCtx, db: DbSession
) -> Response:
    try:
        offer = tenders.get_offer_file(db, ctx, case_id, offer_id)
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return Response(
        content=offer.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(offer.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/tarjoukset/{offer_id}/poista")
def remove_offer(
    case_id: uuid.UUID, offer_id: uuid.UUID, ctx: CompanyCtx, db: DbSession
) -> Response:
    try:
        tenders.remove_offer(db, ctx, case_id, offer_id)
    except tenders.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return _to_case(ctx, case_id, "tallennettu=1", "#tarjoukset")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/vertailu")
def compare(
    request: Request, case_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, provider: Provider
) -> Response:
    try:
        tenders.compare_offers(db, ctx, get_settings(), provider, case_id)
    except tenders.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except tenders.TenderError as exc:
        return _error_page(request, ctx, db, case_id, str(exc))
    return _to_case(ctx, case_id, "tallennettu=1", "#vertailu")


def _stream_tender(
    ctx: CompanyContext,
    db: Session,
    case_id: uuid.UUID,
    provider: Any,
    events: Any,
    anchor: str,
) -> Response:
    # Oikeudet ja asian olemassaolo tarkistetaan ennen striimin alkua (oikea HTTP-tila).
    try:
        tenders.ensure_tender(db, ctx, case_id)
    except tenders.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except tenders.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    settings = get_settings()
    return stream_events(
        ctx,
        lambda session: events(session, ctx, settings, provider, case_id),
        lambda _ref: f"/yhtiot/{ctx.company_id}/asiat/{case_id}{anchor}",
        expected_errors=(tenders.TenderError,),
        commit_on_error=True,
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/luonnos/tekoaly/stream")
def ai_draft_stream(
    case_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, provider: Provider
) -> Response:
    return _stream_tender(
        ctx, db, case_id, provider, tenders.generate_draft_events, "?luonnos=tekoaly#luonnos"
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/vertailu/stream")
def compare_stream(
    case_id: uuid.UUID, ctx: CompanyCtx, db: DbSession, provider: Provider
) -> Response:
    return _stream_tender(
        ctx, db, case_id, provider, tenders.compare_offers_events, "?tallennettu=1#vertailu"
    )
