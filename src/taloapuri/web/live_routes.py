"""Kevyt tilakysely selaimen 30 sekunnin päivityksille (ks. static/live-updates.js)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from taloapuri.auth import CompanyCtx, DbSession
from taloapuri.services import activity

router = APIRouter(include_in_schema=False)


@router.get("/yhtiot/{company_id}/tilanne")
def status(ctx: CompanyCtx, db: DbSession) -> JSONResponse:
    return JSONResponse(
        {
            "unread_cases": ctx.unread_cases,
            "unread_messages": ctx.unread_messages,
            "feed_version": activity.feed_version(db, ctx),
        },
        headers={"Cache-Control": "private, no-store"},
    )
