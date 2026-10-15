"""Isännöitsijän sivut: asukkaat, osakkaat ja huoneistot.

Linkit näytetään vain isännöitsijälle, mutta oikeus tarkistetaan aina palvelussa ja RLS:ssä.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession
from taloapuri.services import members as svc
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)


def _require_manager(ctx: CompanyContext) -> None:
    if not ctx.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN)


@router.get("/yhtiot/{company_id}/asukkaat", response_class=HTMLResponse)
def members_page(
    request: Request, ctx: CompanyCtx, db: DbSession, viesti: str = ""
) -> HTMLResponse:
    _require_manager(ctx)
    notice = {
        "lisatty": "Henkilö on lisätty.",
        "paatetty": "Käyttöoikeus on päätetty.",
    }.get(viesti, "")
    return render(
        request,
        "members.html",
        {"ctx": ctx, "members": svc.list_members(db, ctx), "notice": notice},
    )


@router.get("/yhtiot/{company_id}/asukkaat/uusi", response_class=HTMLResponse)
def new_member_form(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    _require_manager(ctx)
    return render(
        request,
        "member_new.html",
        {
            "ctx": ctx,
            "apartments": svc.list_apartments(db, ctx),
            "values": {"role": "shareholder"},
            "errors": {},
        },
    )


@router.post("/yhtiot/{company_id}/asukkaat")
def add_member(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    display_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "",
    apartment_id: Annotated[str, Form()] = "",
) -> Response:
    _require_manager(ctx)
    values = {
        "display_name": display_name,
        "email": email,
        "role": role,
        "apartment_id": apartment_id,
    }
    try:
        parsed_apartment = uuid.UUID(apartment_id) if apartment_id else None
    except ValueError:
        parsed_apartment = uuid.uuid4()  # ei löydy → selkeä virheilmoitus palvelusta
    try:
        svc.add_resident(
            db,
            ctx,
            display_name=display_name,
            email=email,
            role=role,
            apartment_id=parsed_apartment,
        )
    except svc.InvalidInput as exc:
        return render(
            request,
            "member_new.html",
            {
                "ctx": ctx,
                "apartments": svc.list_apartments(db, ctx),
                "values": values,
                "errors": exc.errors,
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/asukkaat?viesti=lisatty", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/yhtiot/{company_id}/asukkaat/{membership_id}/paata", response_class=HTMLResponse)
def end_member_confirm(
    request: Request, membership_id: uuid.UUID, ctx: CompanyCtx, db: DbSession
) -> HTMLResponse:
    _require_manager(ctx)
    member = next((m for m in svc.list_members(db, ctx) if m.membership_id == membership_id), None)
    if member is None or not member.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return render(request, "member_end.html", {"ctx": ctx, "member": member})


@router.post("/yhtiot/{company_id}/asukkaat/{membership_id}/paata")
def end_member(membership_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> Response:
    try:
        svc.end_membership(db, ctx, membership_id)
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/asukkaat?viesti=paatetty",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/yhtiot/{company_id}/huoneistot", response_class=HTMLResponse)
def apartments_page(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    _require_manager(ctx)
    return _apartments_render(request, ctx, db, {}, "")


def _apartments_render(
    request: Request,
    ctx: CompanyContext,
    db: DbSession,
    errors: dict[str, str],
    label: str,
    code: int = 200,
) -> HTMLResponse:
    apartments = svc.list_apartments(db, ctx)
    histories = {a.id: svc.apartment_history(db, ctx, a.id) for a in apartments}
    return render(
        request,
        "apartments.html",
        {
            "ctx": ctx,
            "apartments": apartments,
            "histories": histories,
            "errors": errors,
            "label": label,
        },
        code=code,
    )


@router.post("/yhtiot/{company_id}/huoneistot")
def add_apartment(
    request: Request, ctx: CompanyCtx, db: DbSession, label: Annotated[str, Form()] = ""
) -> Response:
    _require_manager(ctx)
    try:
        svc.add_apartment(db, ctx, label)
    except svc.InvalidInput as exc:
        return _apartments_render(
            request, ctx, db, exc.errors, label, code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/huoneistot", status_code=status.HTTP_303_SEE_OTHER
    )
