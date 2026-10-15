import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

# Testit ajetaan aina test-ympäristössä. Asetetaan ennen sovelluksen tuontia ja ennen .env:iä
# (load_dotenv ei korvaa jo asetettuja arvoja). .env:stä luetaan esim. TEST_DATABASE_URL.
os.environ["TALOAPURI_ENV"] = "test"
load_dotenv(ROOT / ".env")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_MIGRATION_DATABASE_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["TALOAPURI_DATABASE_URL"] = TEST_DATABASE_URL

from taloapuri.config import get_settings  # noqa: E402
from taloapuri.db import get_engine  # noqa: E402
from taloapuri.main import create_app  # noqa: E402

get_settings.cache_clear()
get_engine.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def as_user(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


@pytest.fixture(scope="session")
def _migrated_db() -> None:
    if not (TEST_DATABASE_URL and TEST_MIGRATION_DATABASE_URL):
        pytest.skip("TEST_DATABASE_URL ja TEST_MIGRATION_DATABASE_URL puuttuvat")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    os.environ["TALOAPURI_MIGRATION_DATABASE_URL"] = TEST_MIGRATION_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture
def seeded(_migrated_db: None) -> Iterator[dict[str, uuid.UUID]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from seed_dev import seed

    assert TEST_MIGRATION_DATABASE_URL
    yield seed(TEST_MIGRATION_DATABASE_URL)


FIXTURE = ROOT / "tests" / "fixtures" / "aoyl_4luku_sample.akn"


@pytest.fixture
def ingested(_migrated_db: None) -> None:
    """Tallentaa AOYL:n 4 luvun näytteen lähteeksi (idempotentti)."""
    from sqlalchemy import create_engine

    from taloapuri.sources.finlex import parse_akn
    from taloapuri.sources.ingest import ingest_act

    assert TEST_MIGRATION_DATABASE_URL
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    with engine.begin() as conn:
        ingest_act(
            conn,
            parse_akn(FIXTURE.read_bytes()),
            source_key="fi/statute/2009/1599",
            short_title="AOYL",
            public_url="https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2009/1599",
        )
    engine.dispose()
    reset_laws()  # fixtureversio käyttöön, vaikka edellinen testi olisi jättänyt jälkiä


KTJL_FIXTURE = ROOT / "tests" / "fixtures" / "ktjl_453_2002.akn"


def reset_laws() -> None:
    """Palauttaa lakilähteet testien perustilaan: vain AOYL:n näyteversio, ei muita lakeja.

    Ylläpitotestit lisäävät lakeja ja versioita jaettuun testikantaan; tämä siivoaa ne pois.
    """
    from sqlalchemy import create_engine, text

    from taloapuri.sources.finlex import parse_akn

    assert TEST_MIGRATION_DATABASE_URL
    sha = parse_akn(FIXTURE.read_bytes()).sha256
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    doomed = (
        "SELECT sec.id FROM source_sections sec"
        " JOIN source_versions v ON v.id = sec.version_id"
        " JOIN sources s ON s.id = v.source_id"
        " WHERE NOT s.is_core OR v.sha256 <> :sha"
    )
    with engine.begin() as conn:
        conn.execute(text("UPDATE sources SET current_version_id = NULL"))
        conn.execute(
            text(f"DELETE FROM chat_citations WHERE source_section_id IN ({doomed})"), {"sha": sha}
        )
        conn.execute(text(f"DELETE FROM source_sections WHERE id IN ({doomed})"), {"sha": sha})
        conn.execute(
            text(
                "DELETE FROM source_versions v USING sources s"
                " WHERE s.id = v.source_id AND (NOT s.is_core OR v.sha256 <> :sha)"
            ),
            {"sha": sha},
        )
        conn.execute(text("DELETE FROM sources WHERE NOT is_core"))
        conn.execute(
            text(
                "UPDATE sources SET active = true, last_checked_at = NULL,"
                " current_version_id = (SELECT id FROM source_versions"
                "                        WHERE source_id = sources.id AND sha256 = :sha)"
                " WHERE is_core"
            ),
            {"sha": sha},
        )
    engine.dispose()


def changed_aoyl_xml(new_version: str = "20270101") -> bytes:
    """AOYL-näyte, jossa yksi momentti on muuttunut ja versionumero uusi (eri SHA-256)."""
    xml = FIXTURE.read_text(encoding="utf-8")
    old = "Yhtiö vastaa kunnossapidosta siltä osin kuin se ei kuulu osakkeenomistajalle."
    assert old in xml, "fixture ei sisällä odotettua momenttia"
    assert 'FRBRversionNumber value="20260535"' in xml
    xml = xml.replace(old, old[:-1] + " ja uusi testilause luotettavuudesta.")
    xml = xml.replace(
        'FRBRversionNumber value="20260535"', f'FRBRversionNumber value="{new_version}"'
    )
    return xml.encode("utf-8")


class FakeLawFetcher:
    """Tiedostopohjainen Finlex-hakija: testit eivät koskaan käytä verkkoa."""

    def __init__(self) -> None:
        self.files: dict[tuple[int, int], bytes | Exception] = {
            (2009, 1599): FIXTURE.read_bytes(),
            (2002, 453): KTJL_FIXTURE.read_bytes(),
        }
        self.calls: list[tuple[int, int]] = []

    def __call__(self, year: int, number: int) -> bytes:
        from taloapuri.sources.finlex import ActNotFound

        self.calls.append((year, number))
        item = self.files.get((year, number))
        if item is None:
            raise ActNotFound("Säädöstä ei löytynyt ajantasaisena versiona.")
        if isinstance(item, Exception):
            raise item
        return item
