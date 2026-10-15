"""Asioiden käsittely. Sama logiikka palvelee REST-API:a ja web-käyttöliittymää.

Kaikki kyselyt kulkevat RLS:n läpi; kutsujan on asetettava tenant-konteksti
(taloapuri.auth.get_company_context) ennen näitä funktioita.
"""

import uuid
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.domain.case_details import DETAILS_MODELS
from taloapuri.domain.case_states import (
    CaseAction,
    CaseStatus,
    available_actions,
    resolve_transition,
)
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import Case, CaseEvent, CaseMessage
from taloapuri.services import members
from taloapuri.services.audit import write_audit


class CaseNotFound(Exception):
    pass


class VersionConflict(Exception):
    """Joku muu on muuttanut asiaa välillä (optimistinen lukitus)."""


class ApartmentNotAllowed(Exception):
    """Huoneisto ei kuulu yhtiöön tai käyttäjä ei voi liittää asiaa siihen."""


class NotAllowed(Exception):
    pass


class InvalidDetails(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


class EmptyText(Exception):
    """Lisätietopyyntö tai vastaus puuttuu."""


def _audit(db: Session, ctx: CompanyContext, action: str, case_id: uuid.UUID, **meta: Any) -> None:
    write_audit(db, ctx, action, "case", case_id, **meta)


def _check_apartment(db: Session, ctx: CompanyContext, apartment_id: uuid.UUID) -> None:
    """Isännöitsijä voi liittää asian mihin tahansa yhtiön huoneistoon, muut vain omaansa."""
    if ctx.is_manager:
        try:
            members.get_apartment(db, ctx, apartment_id)
        except members.NotFound as exc:
            raise ApartmentNotAllowed from exc
        return
    if apartment_id not in {a.id for a in members.my_active_apartments(db, ctx)}:
        raise ApartmentNotAllowed


def list_cases(db: Session, ctx: CompanyContext) -> list[Case]:
    # Yhtiörajaus on myös tässä eksplisiittisesti, vaikka RLS tekee saman (puolustus syvyydessä).
    stmt = (
        select(Case)
        .where(Case.housing_company_id == ctx.company_id)
        .order_by(Case.updated_at.desc())
    )
    return list(db.execute(stmt).scalars())


def get_case(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> Case:
    case = db.execute(
        select(Case).where(Case.id == case_id, Case.housing_company_id == ctx.company_id)
    ).scalar_one_or_none()
    if case is None:
        raise CaseNotFound(case_id)
    return case


def create_case(
    db: Session,
    ctx: CompanyContext,
    *,
    case_type: str,
    title: str,
    description: str,
    event_date: date | None,
    apartment_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> Case:
    """Luo asian. `details` validoidaan asiatyypin mallilla (domain/case_details.py)."""
    if case_type == "tender_request" and not (ctx.roles & ROLES_SEEING_ALL_CASES):
        raise NotAllowed("Tarjouspyynnön voi laatia vain hallitus tai isännöitsijä.")
    if apartment_id is not None:
        _check_apartment(db, ctx, apartment_id)
    model = DETAILS_MODELS.get(case_type)
    if model is None:
        raise InvalidDetails({"case_type": "Tuntematon asiatyyppi."})
    try:
        validated = model.model_validate(details or {})
    except ValidationError as exc:
        raise InvalidDetails(
            {".".join(str(p) for p in e["loc"]) or "details": e["msg"] for e in exc.errors()}
        ) from exc
    case = Case(
        id=uuid.uuid4(),
        housing_company_id=ctx.company_id,
        case_type=case_type,
        title=title,
        description=description,
        status=CaseStatus.DRAFT,
        event_date=event_date,
        created_by=ctx.user_id,
        version=1,
        apartment_id=apartment_id,
        details=validated.model_dump(mode="json"),
    )
    db.add(case)
    db.flush()
    db.add(
        CaseEvent(
            housing_company_id=ctx.company_id,
            case_id=case.id,
            event_type="created",
            from_status=None,
            to_status=CaseStatus.DRAFT,
            actor_user_id=ctx.user_id,
            actor_name=ctx.user_name or None,
        )
    )
    _audit(db, ctx, "case.created", case.id, case_type=case_type)
    db.flush()
    return case


def actions_for(ctx: CompanyContext, case: Case) -> list[CaseAction]:
    return available_actions(
        CaseStatus(case.status), ctx.roles, is_creator=case.created_by == ctx.user_id
    )


def transition_case(
    db: Session,
    ctx: CompanyContext,
    case_id: uuid.UUID,
    action: CaseAction,
    expected_version: int,
) -> Case:
    case = get_case(db, ctx, case_id)
    transition = resolve_transition(
        CaseStatus(case.status), action, ctx.roles, is_creator=case.created_by == ctx.user_id
    )
    # Ehdollinen päivitys: onnistuu vain, jos versio on yhä sama kuin käyttäjän näkemä.
    result = db.execute(
        update(Case)
        .where(
            Case.id == case.id,
            Case.housing_company_id == ctx.company_id,
            Case.version == expected_version,
        )
        .values(status=transition.target, version=Case.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise VersionConflict(case_id)
    db.add(
        CaseEvent(
            housing_company_id=ctx.company_id,
            case_id=case.id,
            event_type=action.value,
            from_status=transition.source,
            to_status=transition.target,
            actor_user_id=ctx.user_id,
            actor_name=ctx.user_name or None,
        )
    )
    _audit(
        db,
        ctx,
        f"case.{action.value}",
        case.id,
        from_status=transition.source.value,
        to_status=transition.target.value,
    )
    db.flush()
    db.refresh(case)
    return case


def set_history_note(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, note: str, expected_version: int
) -> Case:
    """Isännöitsijän merkintä huoneiston historiaan. Näytetään myöhemmille asukkaille."""
    if not ctx.is_manager:
        raise NotAllowed
    case = get_case(db, ctx, case_id)
    cleaned = note.strip()[:500] or None
    result = db.execute(
        update(Case)
        .where(
            Case.id == case.id,
            Case.housing_company_id == ctx.company_id,
            Case.version == expected_version,
        )
        .values(history_note=cleaned, version=Case.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise VersionConflict(case_id)
    _audit(db, ctx, "case.history_note_set", case.id)
    db.flush()
    db.refresh(case)
    return case


# --- Lisätietopyynnöt ja keskustelu ---


def _add_message(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, kind: str, body: str
) -> CaseMessage:
    message = CaseMessage(
        housing_company_id=ctx.company_id,
        case_id=case_id,
        author_id=ctx.user_id,
        author_name=ctx.user_name or "Käyttäjä",
        kind=kind,
        body=body,
    )
    db.add(message)
    db.flush()
    return message


def request_info(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, question: str, expected_version: int
) -> Case:
    """Isännöitsijä tai hallitus pyytää lisätietoja. Kysymys on pakollinen."""
    question = question.strip()
    if not question:
        raise EmptyText("Kirjoita, mitä lisätietoja tarvitset.")
    case = transition_case(db, ctx, case_id, CaseAction.REQUEST_INFO, expected_version)
    _add_message(db, ctx, case.id, "info_request", question[:5000])
    return case


def provide_info(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, answer: str, expected_version: int
) -> Case:
    """Ilmoittaja vastaa lisätietopyyntöön; asia palaa tarkistettavaksi."""
    answer = answer.strip()
    if not answer:
        raise EmptyText("Kirjoita vastaus isännöitsijän kysymykseen.")
    case = transition_case(db, ctx, case_id, CaseAction.PROVIDE_INFO, expected_version)
    _add_message(db, ctx, case.id, "info_response", answer[:5000])
    return case


def add_comment(db: Session, ctx: CompanyContext, case_id: uuid.UUID, body: str) -> CaseMessage:
    body = body.strip()
    if not body:
        raise EmptyText("Kirjoita viesti.")
    get_case(db, ctx, case_id)
    message = _add_message(db, ctx, case_id, "comment", body[:5000])
    _audit(db, ctx, "case.comment_added", case_id)
    return message


def list_messages(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> list[CaseMessage]:
    return list(
        db.execute(
            select(CaseMessage)
            .where(
                CaseMessage.case_id == case_id,
                CaseMessage.housing_company_id == ctx.company_id,
            )
            .order_by(CaseMessage.created_at)
        ).scalars()
    )


def latest_info_request(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> CaseMessage | None:
    messages = [m for m in list_messages(db, ctx, case_id) if m.kind == "info_request"]
    return messages[-1] if messages else None


def my_cases_awaiting_info(db: Session, ctx: CompanyContext) -> list[Case]:
    return list(
        db.execute(
            select(Case)
            .where(
                Case.housing_company_id == ctx.company_id,
                Case.created_by == ctx.user_id,
                Case.status == CaseStatus.AWAITING_INFO,
            )
            .order_by(Case.updated_at.desc())
        ).scalars()
    )


def recent_tenders(db: Session, ctx: CompanyContext, limit: int = 5) -> list[Case]:
    """Uusimmat tarjouspyynnöt. RLS näyttää ne vain hallitukselle ja isännöitsijälle."""
    if not (ctx.roles & ROLES_SEEING_ALL_CASES):
        return []
    return list(
        db.execute(
            select(Case)
            .where(
                Case.housing_company_id == ctx.company_id,
                Case.case_type == "tender_request",
                Case.status.not_in([CaseStatus.CANCELLED]),
            )
            .order_by(Case.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def save_tender_draft(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, draft_text: str, expected_version: int
) -> Case:
    """Ihminen tallentaa (mahdollisesti tekoälyn laatiman) luonnoksen. Ei lähetä mitään."""
    if not (ctx.roles & ROLES_SEEING_ALL_CASES):
        raise NotAllowed
    case = get_case(db, ctx, case_id)
    if case.case_type != "tender_request":
        raise NotAllowed
    details = dict(case.details or {})
    details["draft_text"] = draft_text.strip()[:20000]
    details["draft_saved_by"] = ctx.user_name or ""
    result = db.execute(
        update(Case)
        .where(
            Case.id == case.id,
            Case.housing_company_id == ctx.company_id,
            Case.version == expected_version,
        )
        .values(details=details, version=Case.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise VersionConflict(case_id)
    _audit(db, ctx, "case.tender_draft_saved", case.id)
    db.flush()
    db.refresh(case)
    return case
