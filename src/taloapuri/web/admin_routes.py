"""Lakilähteet: ylläpitäjän hallintasivut (/yllapito/lait) ja kaikille jäsenille näkyvä lukulista.

Vain palvelun ylläpitäjä (users.is_platform_admin) pääsee hallintasivuille; muille vastataan 404.
Lait ovat yhteisiä kaikille taloyhtiöille, joten ylläpitäjä ei näe yhtiöiden tietoja.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import AdminUser, CompanyCtx, DbSession
from taloapuri.config import get_settings
from taloapuri.services import law_admin
from taloapuri.sources.finlex import Fetcher, FinlexError, fetch_act
from taloapuri.sources.updater import source_key_for
from taloapuri.web.templating import render

router = APIRouter(include_in_schema=False)

# Valmiit lisäysehdotukset (ylläpitäjä vahvistaa aina esikatselun jälkeen).
CATALOG = (
    {
        "year": 2002,
        "number": 453,
        "short": "KTJL",
        "label": "Laki kiinteistötietojärjestelmästä ja siitä tuotettavasta tietopalvelusta",
    },
)

NOTICES = {
    "paivitetty": "Päivitetty: uusi versio on otettu käyttöön. Vanha versio säilyy historiana.",
    "ei-muutoksia": "Ei muutoksia: käytössä on jo Finlexin uusin versio.",
    "lisatty": "Laki on lisätty ja otettu käyttöön.",
    "kaytossa": "Laki on otettu käyttöön.",
    "poistettu": "Laki on poistettu käytöstä. Sen tiedot ja vanhat viittaukset säilyvät.",
}


def get_law_fetcher() -> Fetcher:
    """Testit korvaavat tämän tiedostopohjaisella hakijalla (ei verkkoyhteyttä)."""
    return fetch_act


LawFetcher = Annotated[Fetcher, Depends(get_law_fetcher)]


def _parse_ints(year: str, number: str) -> tuple[int, int] | None:
    try:
        return int(year.strip()), int(number.strip())
    except ValueError:
        return None


def _page(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    *,
    error: str = "",
    notice: str = "",
    outcomes: list[law_admin.CheckOutcome] | None = None,
    code: int = 200,
    values: dict[str, str] | None = None,
) -> HTMLResponse:
    laws = law_admin.list_laws(db)
    present = {(s.act_year, s.act_number) for s in laws}
    return render(
        request,
        "admin_laws.html",
        {
            "me": admin,
            "laws": laws,
            "catalog": [c for c in CATALOG if (c["year"], c["number"]) not in present],
            "error": error,
            "notice": notice,
            "outcomes": outcomes,
            "values": values or {},
        },
        code=code,
    )


@router.get("/yllapito/lait", response_class=HTMLResponse)
def laws_page(request: Request, admin: AdminUser, db: DbSession, viesti: str = "") -> HTMLResponse:
    return _page(request, admin, db, notice=NOTICES.get(viesti, ""))


@router.post("/yllapito/lait/esikatsele")
def preview_law(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    fetcher: LawFetcher,
    year: Annotated[str, Form()] = "",
    number: Annotated[str, Form()] = "",
    short_title: Annotated[str, Form()] = "",
) -> Response:
    values = {"year": year, "number": number, "short_title": short_title}
    ints = _parse_ints(year, number)
    if ints is None:
        return _page(
            request,
            admin,
            db,
            error="Anna vuosi ja numero numeroina, esimerkiksi 2002 ja 453.",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            values=values,
        )
    try:
        preview = law_admin.preview_law(db, ints[0], ints[1], fetcher)
        if any(s.source_key == source_key_for(*ints) for s in law_admin.list_laws(db)):
            raise FinlexError("Tämä laki on jo lisätty.")
    except FinlexError as exc:
        return _page(
            request,
            admin,
            db,
            error=str(exc),
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            values=values,
        )
    return render(
        request,
        "admin_law_preview.html",
        {"me": admin, "preview": preview, "short_title": short_title.strip()},
    )


@router.post("/yllapito/lait/lisaa")
def add_law(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    fetcher: LawFetcher,
    year: Annotated[str, Form()] = "",
    number: Annotated[str, Form()] = "",
    short_title: Annotated[str, Form()] = "",
    sha256: Annotated[str, Form()] = "",
) -> Response:
    ints = _parse_ints(year, number)
    if ints is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST)
    try:
        law_admin.add_law(
            db,
            admin,
            year=ints[0],
            number=ints[1],
            short_title=short_title,
            expected_sha256=sha256,
            fetcher=fetcher,
        )
    except FinlexError as exc:
        return _page(request, admin, db, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return RedirectResponse("/yllapito/lait?viesti=lisatty", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/yllapito/lait/{year}/{number}/tarkista")
def check_law(
    request: Request,
    year: int,
    number: int,
    admin: AdminUser,
    db: DbSession,
    fetcher: LawFetcher,
) -> Response:
    try:
        result = law_admin.check_law(
            db,
            admin,
            source_key_for(year, number),
            fetcher,
            get_settings().law_check_cooldown_seconds,
        )
    except law_admin.Cooldown as exc:
        return _page(request, admin, db, error=str(exc), code=status.HTTP_429_TOO_MANY_REQUESTS)
    except FinlexError as exc:
        return _page(request, admin, db, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    notice = "paivitetty" if result.changed else "ei-muutoksia"
    return RedirectResponse(
        f"/yllapito/lait?viesti={notice}#laki-{year}-{number}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/yllapito/lait/tarkista-kaikki")
def check_all(request: Request, admin: AdminUser, db: DbSession, fetcher: LawFetcher) -> Response:
    outcomes = law_admin.check_all(db, admin, fetcher, get_settings().law_check_cooldown_seconds)
    return _page(request, admin, db, outcomes=outcomes)


@router.get("/yllapito/lait/{year}/{number}/poista-kaytosta", response_class=HTMLResponse)
def deactivate_confirm(
    request: Request, year: int, number: int, admin: AdminUser, db: DbSession
) -> HTMLResponse:
    law = next(
        (s for s in law_admin.list_laws(db) if s.source_key == source_key_for(year, number)), None
    )
    if law is None or law.is_core:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return render(request, "admin_law_deactivate.html", {"me": admin, "law": law})


@router.post("/yllapito/lait/{year}/{number}/kaytossa")
def set_active(
    year: int,
    number: int,
    admin: AdminUser,
    db: DbSession,
    active: Annotated[str, Form()] = "0",
) -> Response:
    try:
        law_admin.set_law_active(db, admin, source_key_for(year, number), active == "1")
    except FinlexError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    notice = "kaytossa" if active == "1" else "poistettu"
    return RedirectResponse(
        f"/yllapito/lait?viesti={notice}#laki-{year}-{number}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Kaikille jäsenille: mitä lakeja tekoäly käyttää (vain luku) ---


@router.get("/yhtiot/{company_id}/lait", response_class=HTMLResponse)
def laws_readonly(request: Request, ctx: CompanyCtx, db: DbSession) -> HTMLResponse:
    laws = [s for s in law_admin.list_laws(db) if s.active]
    return render(request, "laws.html", {"ctx": ctx, "laws": laws})
