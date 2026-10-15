"""Asiat: tyyppikohtaiset lomakkeet (vahinkoilmoitus, tarjouspyyntö), asian sivu,
lisätietopyynnöt ja vastaukset, kommentit sekä valokuvat."""

import uuid
from dataclasses import replace
from datetime import date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession
from taloapuri.config import get_settings
from taloapuri.domain.case_states import (
    STATUS_LABELS_FI,
    CaseAction,
    CaseStatus,
    TransitionError,
    TransitionForbidden,
)
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import Apartment
from taloapuri.services import activity, attachments, members
from taloapuri.services import cases as svc
from taloapuri.web.templating import CASE_TYPE_LABELS_FI, render

router = APIRouter(include_in_schema=False)

ACTION_LABELS_FI: dict[CaseAction, str] = {
    CaseAction.SUBMIT: "Lähetä tarkistettavaksi",
    CaseAction.REQUEST_INFO: "Pyydä lisätietoja",
    CaseAction.PROVIDE_INFO: "Lisätiedot on annettu",
    CaseAction.ESCALATE: "Pyydä asiantuntijan arvio",
    CaseAction.RETURN_FROM_EXPERT: "Asiantuntijan arvio saatu",
    CaseAction.APPROVE: "Hyväksy",
    CaseAction.REJECT: "Hylkää",
    CaseAction.REVISE: "Muokkaa (hyväksyntä perutaan)",
    CaseAction.MARK_SENT: "Merkitse lähetetyksi",
    CaseAction.MARK_SEND_FAILED: "Merkitse lähetys epäonnistuneeksi",
    CaseAction.RETRY_SEND: "Yritä lähetystä uudelleen",
    CaseAction.CLOSE: "Sulje asia",
    CaseAction.CANCEL: "Peru asia",
    CaseAction.REOPEN: "Avaa asia uudelleen",
}

# Nämä toiminnot tehdään omilla lomakkeillaan (kysymys / vastaus pakollinen).
_FORM_ACTIONS = {CaseAction.REQUEST_INFO, CaseAction.PROVIDE_INFO}

TEMPLATES = {
    "damage": "case_new_damage.html",
    "tender_request": "case_new_tender.html",
}

ERRORS_FI = {
    "versio": "Joku muu on muuttanut asiaa sillä välin. Tarkista tiedot ja yritä uudelleen.",
    "ei-sallittu": "Tätä toimintoa ei voi tehdä nyt.",
}


def _is_board(ctx: CompanyContext) -> bool:
    return bool(ctx.roles & ROLES_SEEING_ALL_CASES)


def _selectable_apartments(db: DbSession, ctx: CompanyContext) -> list[Apartment]:
    """Isännöitsijä voi valita minkä tahansa huoneiston, muut vain omansa."""
    if ctx.is_manager:
        return members.list_apartments(db, ctx)
    return members.my_active_apartments(db, ctx)


def _read_photos(photos: list[UploadFile] | None) -> list[tuple[str, bytes]]:
    files = []
    for photo in photos or []:
        if photo.filename:
            files.append((photo.filename, photo.file.read(attachments.MAX_BYTES + 1)))
    return files


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def _parse_date(value: str, field: str, errors: dict[str, str], label: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors[field] = f"Anna {label} muodossa vvvv-kk-pp."
        return None


# --- Uusi asia ---


@router.get("/yhtiot/{company_id}/asiat/uusi", response_class=HTMLResponse)
def new_case_form(
    request: Request, ctx: CompanyCtx, db: DbSession, tyyppi: str = "damage"
) -> HTMLResponse:
    if tyyppi not in CASE_TYPE_LABELS_FI:
        tyyppi = "damage"
    if tyyppi == "tender_request" and not _is_board(ctx):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    apartments = _selectable_apartments(db, ctx)
    # Osakas tai asukas, jolla on yksi huoneisto: valitaan se valmiiksi.
    preselected = str(apartments[0].id) if len(apartments) == 1 and not ctx.is_manager else ""
    return render(
        request,
        TEMPLATES.get(tyyppi, "case_new.html"),
        {
            "ctx": ctx,
            "case_type": tyyppi,
            "values": {"apartment_id": preselected, "ongoing": "unknown"},
            "errors": {},
            "apartments": apartments,
        },
    )


@router.post("/yhtiot/{company_id}/asiat")
def create_case(
    request: Request,
    ctx: CompanyCtx,
    db: DbSession,
    case_type: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    event_date: Annotated[str, Form()] = "",
    event_date_unknown: Annotated[str | None, Form()] = None,
    apartment_id: Annotated[str, Form()] = "",
    location_text: Annotated[str, Form()] = "",
    ongoing: Annotated[str, Form()] = "unknown",
    scope: Annotated[str, Form()] = "",
    schedule_start: Annotated[str, Form()] = "",
    schedule_end: Annotated[str, Form()] = "",
    offers_due: Annotated[str, Form()] = "",
    requirements: Annotated[str, Form()] = "",
    budget_note: Annotated[str, Form()] = "",
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    if case_type not in CASE_TYPE_LABELS_FI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST)
    if case_type == "tender_request" and not _is_board(ctx):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    values: dict[str, Any] = {
        "title": title,
        "description": description,
        "event_date": event_date,
        "event_date_unknown": bool(event_date_unknown),
        "apartment_id": apartment_id,
        "location_text": location_text,
        "ongoing": ongoing,
        "scope": scope,
        "schedule_start": schedule_start,
        "schedule_end": schedule_end,
        "offers_due": offers_due,
        "requirements": requirements,
        "budget_note": budget_note,
    }
    errors: dict[str, str] = {}
    if not title.strip():
        errors["title"] = (
            "Kirjoita, mitä tarjouspyyntö koskee, esimerkiksi ”Porrashuoneiden maalaus”."
            if case_type == "tender_request"
            else "Kirjoita lyhyt otsikko, esimerkiksi ”Astianpesukone vuotaa”."
        )
    elif len(title) > 200:
        errors["title"] = "Otsikko on liian pitkä. Käytä enintään 200 merkkiä."

    parsed_date: date | None = None
    details: dict[str, Any] = {}
    if case_type == "tender_request":
        if not scope.strip():
            errors["scope"] = "Kuvaa työn laajuus: mitä tehdään ja missä."
        details = {
            "target": title,
            "scope": scope,
            "location_text": location_text,
            "schedule_start": _parse_date(schedule_start, "schedule_start", errors, "aloituspäivä"),
            "schedule_end": _parse_date(schedule_end, "schedule_end", errors, "päättymispäivä"),
            "offers_due": _parse_date(offers_due, "offers_due", errors, "viimeinen tarjouspäivä"),
            "requirements": requirements,
            "budget_note": budget_note,
        }
    else:
        if event_date and not event_date_unknown:
            parsed_date = _parse_date(event_date, "event_date", errors, "päivämäärä")
            if parsed_date and parsed_date > _today():
                errors["event_date"] = "Päivämäärä ei voi olla tulevaisuudessa."
        elif not event_date_unknown:
            errors["event_date"] = "Anna tapahtumapäivä tai valitse ”En tiedä”."
        if case_type == "damage":
            details = {"location_text": location_text, "ongoing": ongoing}

    apartments = _selectable_apartments(db, ctx)
    parsed_apartment: uuid.UUID | None = None
    if apartment_id and case_type != "tender_request":
        allowed = {str(a.id): a.id for a in apartments}
        if apartment_id in allowed:
            parsed_apartment = allowed[apartment_id]
        else:
            errors["apartment_id"] = "Valitse huoneisto listasta."

    # Kuvat käsitellään ennen tallennusta, jotta virheellinen kuva ei jätä puolikasta asiaa.
    prepared: list[tuple[str, attachments.ProcessedImage]] = []
    if case_type == "damage":
        try:
            prepared = attachments.prepare_photos(_read_photos(photos))
        except attachments.InvalidImage as exc:
            errors["photos"] = str(exc)

    def _form_again(errs: dict[str, str]) -> Response:
        return render(
            request,
            TEMPLATES.get(case_type, "case_new.html"),
            {
                "ctx": ctx,
                "case_type": case_type,
                "values": values,
                "errors": errs,
                "apartments": apartments,
            },
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if errors:
        return _form_again(errors)
    try:
        case = svc.create_case(
            db,
            ctx,
            case_type=case_type,
            title=title.strip(),
            description=description.strip(),
            event_date=parsed_date,
            apartment_id=parsed_apartment,
            details=details,
        )
    except svc.InvalidDetails as exc:
        return _form_again({k.split(".")[-1]: v for k, v in exc.errors.items()})
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    attachments.add_photos(db, ctx, case.id, prepared)
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/asiat/{case.id}?tallennettu=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Asian sivu ---


def case_page(
    request: Request,
    ctx: CompanyContext,
    db: DbSession,
    case_id: uuid.UUID,
    *,
    saved: bool = False,
    error: str = "",
    code: int = 200,
    extra: dict[str, Any] | None = None,
) -> HTMLResponse:
    try:
        case = svc.get_case(db, ctx, case_id)
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    # Avaaminen merkitsee asian luetuksi; yläpalkin laskuri päivitetään samalla.
    activity.mark_case_read(db, ctx, case.id)
    ctx = replace(ctx, unread_cases=activity.unread_case_count(db, ctx.company_id, ctx.user_id))
    available = svc.actions_for(ctx, case)
    actions = [(a.value, ACTION_LABELS_FI[a]) for a in available if a not in _FORM_ACTIONS]
    apartment_label = ""
    if case.apartment_id:
        try:
            apartment_label = members.get_apartment(db, ctx, case.apartment_id).label
        except members.NotFound:
            apartment_label = ""
    is_creator = case.created_by == ctx.user_id
    context: dict[str, Any] = {
        "ctx": ctx,
        "case": case,
        "details": case.details or {},
        "apartment_label": apartment_label,
        "status_label": STATUS_LABELS_FI[CaseStatus(case.status)],
        "actions": actions,
        "can_request_info": CaseAction.REQUEST_INFO in available,
        "can_provide_info": CaseAction.PROVIDE_INFO in available and is_creator,
        "info_request": svc.latest_info_request(db, ctx, case.id)
        if case.status == CaseStatus.AWAITING_INFO
        else None,
        "messages": svc.list_messages(db, ctx, case.id),
        "photos": attachments.list_for_case(db, ctx, case.id),
        "can_add_photos": case.case_type == "damage" and (is_creator or _is_board(ctx)),
        "is_board": _is_board(ctx),
        "saved": saved,
        "error": error,
    }
    # Tarjouspyynnön lisäosat (tarjoukset, tekoälyn tuotokset) – ks. tenders_routes.
    from taloapuri.web.tenders_routes import tender_context

    context.update(tender_context(db, ctx, case))
    context.update(extra or {})
    return render(request, "case_detail.html", context, code=code)


@router.get("/yhtiot/{company_id}/asiat/{case_id}", response_class=HTMLResponse)
def case_detail(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    tallennettu: int = 0,
    virhe: str = "",
    luonnos: str = "",
) -> HTMLResponse:
    extra: dict[str, Any] = {}
    if luonnos == "tekoaly":
        # Näytetään tekoälyn uusin luonnos muokattavana; tallentuu vasta, kun ihminen tallentaa.
        from taloapuri.services import tenders

        output = tenders.latest_output(db, ctx, case_id, "tender_draft")
        if output is not None:
            extra = {"draft_suggestion": output.text}
    return case_page(
        request,
        ctx,
        db,
        case_id,
        saved=bool(tallennettu),
        error=ERRORS_FI.get(virhe, ""),
        extra=extra,
    )


def _back(ctx: CompanyContext, case_id: uuid.UUID, query: str) -> RedirectResponse:
    return RedirectResponse(
        f"/yhtiot/{ctx.company_id}/asiat/{case_id}?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/toiminnot")
def case_action(
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    action: Annotated[CaseAction, Form()],
    expected_version: Annotated[int, Form()],
) -> Response:
    if action in _FORM_ACTIONS:
        return _back(ctx, case_id, "virhe=ei-sallittu")
    try:
        svc.transition_case(db, ctx, case_id, action, expected_version)
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.VersionConflict:
        return _back(ctx, case_id, "virhe=versio")
    except (TransitionError, TransitionForbidden):
        return _back(ctx, case_id, "virhe=ei-sallittu")
    return _back(ctx, case_id, "tallennettu=1")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/lisatietopyynto")
def request_info(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    expected_version: Annotated[int, Form()],
    question: Annotated[str, Form()] = "",
) -> Response:
    try:
        svc.request_info(db, ctx, case_id, question, expected_version)
    except svc.EmptyText as exc:
        return case_page(
            request, ctx, db, case_id, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.VersionConflict:
        return _back(ctx, case_id, "virhe=versio")
    except (TransitionError, TransitionForbidden):
        return _back(ctx, case_id, "virhe=ei-sallittu")
    return _back(ctx, case_id, "tallennettu=1")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/vastaus")
def provide_info(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    expected_version: Annotated[int, Form()],
    answer: Annotated[str, Form()] = "",
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    try:
        prepared = attachments.prepare_photos(_read_photos(photos))
        if prepared and attachments.count_for_case(db, ctx, case_id) + len(prepared) > (
            attachments.MAX_PER_CASE
        ):
            raise attachments.InvalidImage(
                f"Asiaan voi liittää enintään {attachments.MAX_PER_CASE} kuvaa."
            )
        svc.provide_info(db, ctx, case_id, answer, expected_version)
    except (svc.EmptyText, attachments.InvalidImage) as exc:
        return case_page(
            request, ctx, db, case_id, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.VersionConflict:
        return _back(ctx, case_id, "virhe=versio")
    except (TransitionError, TransitionForbidden):
        return _back(ctx, case_id, "virhe=ei-sallittu")
    attachments.add_photos(db, ctx, case_id, prepared)
    return _back(ctx, case_id, "tallennettu=1")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/kommentti")
def add_comment(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    body: Annotated[str, Form()] = "",
) -> Response:
    try:
        svc.add_comment(db, ctx, case_id, body)
    except svc.EmptyText as exc:
        return case_page(
            request, ctx, db, case_id, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return _back(ctx, case_id, "tallennettu=1")


@router.post("/yhtiot/{company_id}/asiat/{case_id}/kuvat")
def add_photos(
    request: Request,
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> Response:
    try:
        case = svc.get_case(db, ctx, case_id)
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    if case.created_by != ctx.user_id and not _is_board(ctx):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    try:
        prepared = attachments.prepare_photos(_read_photos(photos))
        if not prepared:
            raise attachments.InvalidImage("Valitse vähintään yksi kuva.")
        attachments.add_photos(db, ctx, case_id, prepared)
    except attachments.InvalidImage as exc:
        return case_page(
            request, ctx, db, case_id, error=str(exc), code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    return _back(ctx, case_id, "tallennettu=1")


@router.get("/yhtiot/{company_id}/asiat/{case_id}/kuvat/{attachment_id}")
def photo(case_id: uuid.UUID, attachment_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> Response:
    try:
        file = attachments.get_file(db, ctx, case_id, attachment_id)
    except attachments.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    return Response(
        content=file.content,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/yhtiot/{company_id}/asiat/{case_id}/historiamerkinta")
def case_history_note(
    case_id: uuid.UUID,
    ctx: CompanyCtx,
    db: DbSession,
    expected_version: Annotated[int, Form()],
    history_note: Annotated[str, Form()] = "",
) -> Response:
    try:
        svc.set_history_note(db, ctx, case_id, history_note, expected_version)
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from exc
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
    except svc.VersionConflict:
        return _back(ctx, case_id, "virhe=versio")
    return _back(ctx, case_id, "tallennettu=1")
