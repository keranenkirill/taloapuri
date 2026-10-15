from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Kevyt elossaolotarkistus. Ei koske tietokantaan eikä palauta ympäristötietoja."""
    return {"status": "ok"}
