"""Palvelinrenderöity, saavutettava web-käyttöliittymä (ks. docs/adr/0001).

Sama palvelukerros (taloapuri.services) palvelee myös REST-API:a, joten säännöt ovat yhdessä
paikassa. Yhtiön tunniste kulkee aina URL-polussa (/yhtiot/{company_id}/...).
"""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, text

from taloapuri.auth import CompanyCtx, DbSession, OptionalUser
from taloapuri.config import get_settings
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import HousingCompany
from taloapuri.services import activity, members
from taloapuri.services import cases as svc
from taloapuri.web.faq_routes import front_page_views
from taloapuri.web.templating import (
    THEME_COOKIE,
    THEMES,
    render,
    safe_next,
    templates,
)

router = APIRouter(include_in_schema=False)
_render = render

DEV_COOKIE = "dev_user_id"


@router.post("/asetukset/teema")
def set_theme(
    theme: Annotated[str, Form()], next_path: Annotated[str, Form(alias="next")] = "/"
) -> Response:
    response = RedirectResponse(safe_next(next_path), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        THEME_COOKIE,
        theme if theme in THEMES else "auto",
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: DbSession, me: OptionalUser, virhe: str = "") -> HTMLResponse:
    companies: list[HousingCompany] = []
    if me is not None:
        # RLS palauttaa vain yhtiöt, joissa käyttäjällä on voimassa oleva jäsenyys.
        companies = list(db.execute(select(HousingCompany).order_by(HousingCompany.name)).scalars())
    return _render(
        request,
        "index.html",
        {
            "me": me,
            "faq": front_page_views(),
            "logged_in": me is not None,
            "companies": companies,
            "dev_auth": get_settings().dev_auth_enabled,
            "login_error": (
                "Sähköpostiosoitteella ei löytynyt käyttäjää. Tarkista osoite."
                if virhe == "kirjautuminen"
                else ""
            ),
        },
    )


@router.post("/dev/kirjaudu")
def dev_login(db: DbSession, email: Annotated[str, Form()] = "") -> Response:
    """Kehityskirjautuminen sähköpostilla (ei salasanaa). Vain local/test-ympäristöissä."""
    if not get_settings().dev_auth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    user_id = None
    if email.strip():
        user_id = db.execute(
            text("SELECT app_find_user_by_email(:e)"), {"e": email.strip()[:320]}
        ).scalar_one()
    if user_id is None:
        return RedirectResponse("/?virhe=kirjautuminen", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(DEV_COOKIE, str(user_id), httponly=True, samesite="lax")
    return response


@router.post("/dev/kirjaudu-ulos")
def dev_logout() -> Response:
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(DEV_COOKIE)
    return response


@router.get("/ensiohjeet/vesivahinko", response_class=HTMLResponse)
def first_aid_water(request: Request) -> HTMLResponse:
    """Staattinen sisältö: toimii aina, ei riipu tietokannasta eikä tekoälystä."""
    response = templates.TemplateResponse(request, "ensiohjeet_vesivahinko.html", {})
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@router.get("/yhtiot/{company_id}", response_class=HTMLResponse)
def dashboard(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    return _render(
        request,
        "dashboard.html",
        {
            "ctx": ctx,
            "cases": svc.list_cases(db, ctx),
            "feed": activity.feed(db, ctx),
            "unread_map": activity.unread_case_ids(db, ctx),
            "is_board": bool(ctx.roles & ROLES_SEEING_ALL_CASES),
        },
    )


@router.get("/yhtiot/{company_id}/huoneistohistoria", response_class=HTMLResponse)
def apartment_history_page(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    histories = [
        {"apartment": a, "history": members.apartment_history(db, ctx, a.id)}
        for a in members.my_active_apartments(db, ctx)
    ]
    return _render(request, "apartment_history.html", {"ctx": ctx, "histories": histories})
