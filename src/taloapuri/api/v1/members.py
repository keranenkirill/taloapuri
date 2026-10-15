"""Jäsenet ja huoneistot (vain isännöitsijä ja hallituksen puheenjohtaja)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from taloapuri.auth import CompanyCtx, DbSession
from taloapuri.services import members as svc

router = APIRouter(prefix="/companies/{company_id}", tags=["members"])


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: str | None
    role: str
    valid_from: datetime
    valid_to: datetime | None
    active: bool
    apartments: list[str]


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=320)
    role: str = Field(pattern="^(shareholder|resident)$")
    apartment_id: uuid.UUID | None = None


class MemberCreated(BaseModel):
    membership_id: uuid.UUID


class ApartmentOut(BaseModel):
    id: uuid.UUID
    label: str


class ApartmentCreate(BaseModel):
    label: str = Field(min_length=1, max_length=32)


class HistoryOut(BaseModel):
    case_type: str
    status: str
    event_date: date | None
    closed_at: datetime | None
    history_note: str | None


def _forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Ei oikeutta tähän toimintoon")


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: CompanyCtx, db: DbSession) -> list[MemberOut]:
    try:
        rows = svc.list_members(db, ctx)
    except svc.NotAllowed as exc:
        raise _forbidden() from exc
    return [MemberOut(**r.__dict__) for r in rows]


@router.post("/members", response_model=MemberCreated, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberCreate, ctx: CompanyCtx, db: DbSession) -> MemberCreated:
    try:
        membership_id = svc.add_resident(
            db,
            ctx,
            display_name=body.display_name,
            email=body.email,
            role=body.role,
            apartment_id=body.apartment_id,
        )
    except svc.NotAllowed as exc:
        raise _forbidden() from exc
    except svc.InvalidInput as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors) from exc
    return MemberCreated(membership_id=membership_id)


@router.post("/members/{membership_id}/end", status_code=status.HTTP_204_NO_CONTENT)
def end_member(membership_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> None:
    try:
        svc.end_membership(db, ctx, membership_id)
    except svc.NotAllowed as exc:
        raise _forbidden() from exc
    except svc.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jäsenyyttä ei löytynyt") from exc


@router.get("/apartments", response_model=list[ApartmentOut])
def list_apartments(ctx: CompanyCtx, db: DbSession) -> list[ApartmentOut]:
    return [ApartmentOut(id=a.id, label=a.label) for a in svc.list_apartments(db, ctx)]


@router.post("/apartments", response_model=ApartmentOut, status_code=status.HTTP_201_CREATED)
def add_apartment(body: ApartmentCreate, ctx: CompanyCtx, db: DbSession) -> ApartmentOut:
    try:
        apartment_id = svc.add_apartment(db, ctx, body.label)
    except svc.NotAllowed as exc:
        raise _forbidden() from exc
    except svc.InvalidInput as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors) from exc
    return ApartmentOut(id=apartment_id, label=body.label.strip())


@router.get("/apartments/{apartment_id}/history", response_model=list[HistoryOut])
def apartment_history(apartment_id: uuid.UUID, ctx: CompanyCtx, db: DbSession) -> list[HistoryOut]:
    """Vain huoneiston nykyiselle asukkaalle tai isännöitsijälle; muille tyhjä lista."""
    return [HistoryOut(**h.__dict__) for h in svc.apartment_history(db, ctx, apartment_id)]
