"""Finlex-jäsennys (ilman verkkoa) ja lähdehaku (tietokanta)."""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from taloapuri.db import set_user_context
from taloapuri.services.sources import build_tsquery, search_sections
from taloapuri.sources.finlex import consolidated_url, fetch, parse_akn
from taloapuri.sources.ingest import ingest_act
from tests.conftest import FIXTURE, TEST_DATABASE_URL, TEST_MIGRATION_DATABASE_URL


def test_parse_fixture_into_subsections() -> None:
    act = parse_akn(FIXTURE.read_bytes())
    assert act.title == "Asunto-osakeyhtiölaki"
    assert act.version_label == "20260535"
    assert str(act.consolidated_date) == "2026-06-16"
    sec2 = [s for s in act.sections if s.section_num == "2 §"]
    assert [s.subsection_no for s in sec2] == [1, 2, 3, 4]
    assert sec2[0].chapter_num == "4 luku"
    assert sec2[0].section_heading == "Yhtiön kunnossapitovastuu"
    assert "rakenteet, eristeet ja ikkunat" in sec2[1].text


def test_amendment_reference_is_removed_from_heading() -> None:
    act = parse_akn(FIXTURE.read_bytes())
    sec3 = next(s for s in act.sections if s.section_num == "3 §")
    assert (
        sec3.section_heading == "Osakkeenomistajan kunnossapitovastuu ja tietojenantovelvollisuus"
    )


def test_tsquery_is_sanitized() -> None:
    tsq = build_tsquery("Kuka vastaa? '); DROP TABLE x; --")
    assert tsq is not None
    assert set(tsq.split(" | ")) == {"drop:*", "table:*", "kunnossapitovastuu:*"}
    assert build_tsquery("?!") is None


def test_everyday_words_are_expanded_to_legal_terms() -> None:
    tsq = build_tsquery("Kuka vastaa kylpyhuoneen vedeneristyksestä?")
    assert tsq is not None
    terms = set(tsq.split(" | "))
    assert {"sisäosat:*", "eristeet:*", "kunnossapitovastuu:*"} <= terms
    assert "kuka:*" not in terms


def test_fetch_rejects_other_hosts() -> None:
    with pytest.raises(ValueError):
        fetch("https://evil.example/akn")
    assert consolidated_url(2009, 1599).endswith("/2009/1599/fin%40latest")


@pytest.mark.db
def test_reingest_same_content_creates_no_new_version(ingested: None) -> None:
    assert TEST_MIGRATION_DATABASE_URL
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    with engine.begin() as conn:
        result = ingest_act(
            conn,
            parse_akn(FIXTURE.read_bytes()),
            source_key="fi/statute/2009/1599",
            short_title="AOYL",
            public_url="https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2009/1599",
        )
    engine.dispose()
    assert result.created is False
    assert result.section_count == 15


def _app_session(user_id: uuid.UUID | None) -> Session:
    assert TEST_DATABASE_URL
    session = Session(create_engine(TEST_DATABASE_URL))
    session.begin()
    if user_id is not None:
        set_user_context(session, user_id)
    return session


@pytest.mark.db
def test_search_finds_maintenance_sections(ingested: None, seeded: dict[str, uuid.UUID]) -> None:
    session = _app_session(seeded["shareholder_a"])
    try:
        hits = search_sections(session, "Kuka vastaa kylpyhuoneen kunnossapitovastuusta?")
    finally:
        session.close()
    labels = [h.citation_label for h in hits]
    assert "AOYL 4 luku 2 §" in labels or "AOYL 4 luku 3 §" in labels
    top = hits[0]
    assert top.subsections, "pykälän kaikki momentit mukana"
    assert top.public_url.startswith("https://www.finlex.fi/")


@pytest.mark.db
def test_sources_require_login(ingested: None) -> None:
    session = _app_session(None)
    try:
        count = session.execute(text("SELECT count(*) FROM source_sections")).scalar_one()
    finally:
        session.close()
    assert count == 0
