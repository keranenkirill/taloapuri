"""Asiat. Reitti sisältää aina yhtiön tunnisteen: /companies/{company_id}/... (ks. ADR 0004)."""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from taloapuri.auth import CompanyContext, CompanyCtx, DbSession
from taloapuri.domain.case_states import (
    STATUS_LABELS_FI,
    CaseAction,
    CaseStatus,
    TransitionError,
    TransitionForbidden,
)
from taloapuri.domain.roles import ROLES_SEEING_ALL_CASES
from taloapuri.models import Case
from taloapuri.services import cases as svc

router = APIRouter(prefix="/companies/{company_id}/cases", tags=["cases"])

CASE_TYPES = ("damage", "maintenance_responsibility", "renovation_notice", "tender_request")


class CaseCreate(BaseModel):
    case_type: str = Field(pattern="^(" + "|".join(CASE_TYPES) + ")$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    event_date: date | None = None
    apartment_id: uuid.UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CaseOut(BaseModel):
    id: uuid.UUID
    case_type: str
    title: str
    description: str
    status: CaseStatus
    status_label: str
    event_date: date | None
    apartment_id: uuid.UUID | None
    details: dict[str, Any]
    created_by_me: bool
    version: int
    available_actions: list[CaseAction]
    updated_at: datetime


class TransitionIn(BaseModel):
    action: CaseAction
    expected_version: int = Field(ge=1)
    # Pakollinen, kun action on request_info (kysymys) tai provide_info (vastaus).
    message: str = Field(default="", max_length=5000)


def _board(ctx: CompanyContext) -> bool:
    return bool(ctx.roles & ROLES_SEEING_ALL_CASES)


def _public_details(case: Case, can_see_budget: bool) -> dict[str, Any]:
    details = dict(case.details or {})
    if not can_see_budget:
        details.pop("budget_note", None)
    return details


def _out(
    case: Case, ctx_user: uuid.UUID, actions: list[CaseAction], can_see_budget: bool = False
) -> CaseOut:
    st = CaseStatus(case.status)
    return CaseOut(
        id=case.id,
        case_type=case.case_type,
        title=case.title,
        description=case.description,
        status=st,
        status_label=STATUS_LABELS_FI[st],
        event_date=case.event_date,
        apartment_id=case.apartment_id,
        details=_public_details(case, can_see_budget),
        created_by_me=case.created_by == ctx_user,
        version=case.version,
        available_actions=actions,
        updated_at=case.updated_at,
    )


@router.get("", response_model=list[CaseOut])
def list_cases(ctx: CompanyCtx, db: DbSession) -> list[CaseOut]:
    return [
        _out(c, ctx.user_id, svc.actions_for(ctx, c), _board(ctx)) for c in svc.list_cases(db, ctx)
    ]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, ctx: CompanyCtx, db: DbSession) -> CaseOut:
    try:
        case = svc.create_case(
            db,
            ctx,
            case_type=body.case_type,
            title=body.title,
            description=body.description,
            event_date=body.event_date,
            apartment_id=body.apartment_id,
            details=body.details,
        )
    except svc.NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except svc.InvalidDetails as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors) from exc
    except svc.ApartmentNotAllowed as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Huoneistoa ei voi valita"
        ) from exc
    return _out(case, ctx.user_id, svc.actions_for(ctx, case), _board(ctx))


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> CaseOut:
    try:
        case = svc.get_case(db, ctx, case_id)
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asiaa ei löytynyt") from exc
    return _out(case, ctx.user_id, svc.actions_for(ctx, case), _board(ctx))


@router.post("/{case_id}/transitions", response_model=CaseOut)
def transition_case(
    case_id: uuid.UUID, body: TransitionIn, ctx: CompanyCtx, db: DbSession
) -> CaseOut:
    try:
        if body.action == CaseAction.REQUEST_INFO:
            case = svc.request_info(db, ctx, case_id, body.message, body.expected_version)
        elif body.action == CaseAction.PROVIDE_INFO:
            case = svc.provide_info(db, ctx, case_id, body.message, body.expected_version)
        else:
            case = svc.transition_case(db, ctx, case_id, body.action, body.expected_version)
    except svc.EmptyText as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except svc.CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asiaa ei löytynyt") from exc
    except TransitionForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ei oikeutta tähän toimintoon") from exc
    except TransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Toiminto ei ole mahdollinen nyt") from exc
    except svc.VersionConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Joku muu on muuttanut asiaa. Lataa sivu uudelleen ja tarkista muutokset.",
        ) from exc
    return _out(case, ctx.user_id, svc.actions_for(ctx, case), _board(ctx))
