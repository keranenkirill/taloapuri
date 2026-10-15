"""Yhtiön asiakirjat (metatiedot). RLS rajaa asukkaille näkyviin merkittyihin."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from taloapuri.auth import CompanyCtx, DbSession
from taloapuri.services import documents as svc

router = APIRouter(prefix="/companies/{company_id}", tags=["documents"])


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    meeting_date: date | None
    description: str | None
    visible_to_residents: bool
    uploaded_by_name: str
    uploaded_at: datetime
    filename: str
    size_bytes: int
    download_url: str


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(ctx: CompanyCtx, db: DbSession) -> list[DocumentOut]:
    return [
        DocumentOut(
            **d.__dict__,
            download_url=f"/yhtiot/{ctx.company_id}/asiakirjat/{d.id}/lataa",
        )
        for d in svc.list_documents(db, ctx)
    ]
