"""Asetukset-sivu: ulkoasu, oma sähköposti ja uloskirjautuminen."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import DbSession, UserDep
from taloapuri.services import account
from taloapuri.web.templating import render, safe_next

router = APIRouter(include_in_schema=False)


@router.get("/asetukset", response_class=HTMLResponse)
def settings_page(
    request: Request, me: UserDep, tallennettu: int = 0, takaisin: str = "/"
) -> HTMLResponse:
    return render(
        request,
        "settings.html",
        {
            "me": me,
            "email_value": me.email or "",
            "email_error": "",
            "saved": bool(tallennettu),
            "back": safe_next(takaisin),
        },
    )


@router.post("/asetukset/sahkoposti")
def change_email(
    request: Request,
    db: DbSession,
    me: UserDep,
    email: Annotated[str, Form()] = "",
    takaisin: Annotated[str, Form()] = "/",
) -> Response:
    try:
        account.change_email(db, me, email)
    except account.InvalidEmail as exc:
        return render(
            request,
            "settings.html",
            {
                "me": me,
                "email_value": email,
                "email_error": str(exc),
                "saved": False,
                "back": safe_next(takaisin),
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse(
        f"/asetukset?tallennettu=1&takaisin={safe_next(takaisin)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
