"""Jaetut Jinja-asetukset: suodattimet, globaalit ja teeman valinta."""

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from taloapuri.config import get_settings
from taloapuri.domain.case_states import STATUS_LABELS_FI
from taloapuri.domain.roles import ROLE_LABELS_FI

THEMES = ("auto", "light", "dark")
THEME_COOKIE = "theme"

CASE_TYPE_LABELS_FI: dict[str, str] = {
    "damage": "Vahinkoilmoitus",
    "maintenance_responsibility": "Kunnossapitovastuun selvitys",
    "renovation_notice": "Muutostyöilmoitus",
    "tender_request": "Tarjouspyyntö",
}


def current_theme(request: Request) -> str:
    theme = request.cookies.get(THEME_COOKIE, "auto")
    return theme if theme in THEMES else "auto"


def _theme_processor(request: Request) -> dict[str, Any]:
    return {"theme": current_theme(request), "current_path": request.url.path}


def _fi_date(value: date) -> str:
    return f"{value.day}.{value.month}.{value.year}"


def _fi_datetime(value: datetime) -> str:
    local = value.astimezone(ZoneInfo(get_settings().timezone))
    return f"{local.day}.{local.month}.{local.year} klo {local:%H.%M}"


def _fi_date_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return _fi_date(value.astimezone(ZoneInfo(get_settings().timezone)).date())


templates = Jinja2Templates(
    directory=Path(__file__).parent / "templates", context_processors=[_theme_processor]
)
templates.env.globals["STATUS_LABELS_FI"] = {
    s.value: label for s, label in STATUS_LABELS_FI.items()
}
templates.env.globals["ROLE_LABELS_FI"] = {r.value: label for r, label in ROLE_LABELS_FI.items()}
templates.env.globals["CASE_TYPE_LABELS_FI"] = CASE_TYPE_LABELS_FI
templates.env.filters["fi_date"] = _fi_date
templates.env.filters["fi_datetime"] = _fi_datetime
templates.env.filters["fi_date_dt"] = _fi_date_dt


def render(request: Request, name: str, ctx: dict[str, Any], code: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(request, name, ctx, status_code=code)
    # Tenant-kohtaista sisältöä ei saa tallentaa jaettuihin välimuisteihin.
    response.headers["Cache-Control"] = "private, no-store"
    return response


def safe_next(path: str) -> str:
    """Sallii vain saman palvelun sisäiset polut (estää avoimen uudelleenohjauksen)."""
    if path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/"
