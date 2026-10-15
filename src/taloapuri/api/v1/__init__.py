from fastapi import APIRouter

from taloapuri.api.v1 import cases, documents, health, members

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(cases.router)
router.include_router(members.router)
router.include_router(documents.router)
