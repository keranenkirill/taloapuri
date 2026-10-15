"""Lakilähteiden hallinta: vain palvelun ylläpitäjä. Ei verkkoyhteyttä (tiedostopohjainen hakija).

Vaatii PostgreSQL:n.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from taloapuri.ai.provider import FakeProvider
from taloapuri.config import get_settings
from taloapuri.db import set_company_context, set_user_context
from taloapuri.main import create_app
from taloapuri.services.sources import search_sections
from taloapuri.sources import updater
from taloapuri.sources.finlex import ActNotFound, FinlexError
from taloapuri.web.admin_routes import get_law_fetcher
from taloapuri.web.chat_routes import get_ai_provider
from tests.conftest import (
    KTJL_FIXTURE,
    TEST_DATABASE_URL,
    TEST_MIGRATION_DATABASE_URL,
    FakeLawFetcher,
    as_user,
    changed_aoyl_xml,
    reset_laws,
)

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]
AOYL_PATH = "2009/1599"
KTJL_PATH = "2002/453"


@pytest.fixture(autouse=True)
def clean_laws(ingested: None) -> Iterator[None]:
    reset_laws()
    yield
    reset_laws()


@pytest.fixture
def fetcher() -> FakeLawFetcher:
    return FakeLawFetcher()


@pytest.fixture
def no_cooldown(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TALOAPURI_LAW_CHECK_COOLDOWN_SECONDS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(fetcher: FakeLawFetcher) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_law_fetcher] = lambda: fetcher
    app.dependency_overrides[get_ai_provider] = lambda: FakeProvider()
    return TestClient(app)


def _owner_query(sql: str, **params: object) -> list[tuple[object, ...]]:
    assert TEST_MIGRATION_DATABASE_URL
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    with engine.connect() as conn:
        rows = [tuple(r) for r in conn.execute(text(sql), params)]
    engine.dispose()
    return rows


def _add_ktjl(client: TestClient, ids: Ids) -> None:
    admin = as_user(ids["platform_admin"])
    preview = client.post(
        "/yllapito/lait/esikatsele",
        data={"year": "2002", "number": "453", "short_title": "KTJL"},
        headers=admin,
    )
    assert preview.status_code == 200, preview.text
    sha = preview.text.split('name="sha256" value="')[1].split('"')[0]
    added = client.post(
        "/yllapito/lait/lisaa",
        data={"year": "2002", "number": "453", "short_title": "KTJL", "sha256": sha},
        headers=admin,
        follow_redirects=False,
    )
    assert added.status_code == 303, added.text


@contextmanager
def app_session(ids: Ids, user: str = "shareholder_a") -> Iterator[Session]:
    """Sovellusroolin istunto, jossa käyttäjä- ja yhtiökonteksti on asetettu (RLS pätee)."""
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    db = Session(engine)
    db.begin()
    set_user_context(db, ids[user])
    set_company_context(db, ids["company_a"])
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        engine.dispose()


# --- Pääsy ---


def test_only_platform_admin_can_open_admin_pages(client: TestClient, seeded: Ids) -> None:
    assert client.get("/yllapito/lait", headers=as_user(seeded["manager"])).status_code == 404
    assert client.get("/yllapito/lait", headers=as_user(seeded["shareholder_a"])).status_code == 404
    assert client.get("/yllapito/lait", follow_redirects=False).status_code == 303
    page = client.get("/yllapito/lait", headers=as_user(seeded["platform_admin"]))
    assert page.status_code == 200
    assert "AOYL" in page.text and "Ydinlaki" in page.text


def test_non_admin_cannot_post_admin_actions(client: TestClient, seeded: Ids) -> None:
    for url, data in (
        ("/yllapito/lait/esikatsele", {"year": "2002", "number": "453"}),
        (f"/yllapito/lait/{AOYL_PATH}/tarkista", {}),
        ("/yllapito/lait/tarkista-kaikki", {}),
    ):
        response = client.post(url, data=data, headers=as_user(seeded["manager"]))
        assert response.status_code == 404, url


def test_admin_sees_no_company_data(client: TestClient, seeded: Ids) -> None:
    admin = as_user(seeded["platform_admin"])
    assert client.get(f"/yhtiot/{seeded['company_a']}", headers=admin).status_code == 404
    front = client.get("/", headers=admin).text
    assert "Palvelun ylläpito" in front and "/yllapito/lait" in front
    assert "Valitse taloyhtiö" not in front
    assert 'href="/yllapito/lait">Ylläpito</a>' in front
    resident = client.get("/", headers=as_user(seeded["shareholder_a"])).text
    assert "Palvelun ylläpito" not in resident


def test_members_get_read_only_list(client: TestClient, seeded: Ids) -> None:
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/lait", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Tekoälyn lakilähteet" in html and "AOYL" in html
    assert "Tarkista päivitykset" not in html


# --- Lisääminen ---


def test_add_law_via_preview_and_confirm(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids
) -> None:
    admin = as_user(seeded["platform_admin"])
    preview = client.post(
        "/yllapito/lait/esikatsele",
        data={"year": "2002", "number": "453", "short_title": "KTJL"},
        headers=admin,
    )
    assert preview.status_code == 200
    assert (
        "Laki kiinteistötietojärjestelmästä ja siitä tuotettavasta tietopalvelusta" in preview.text
    )
    assert "13 pykälää" in preview.text and "Vahvista lisäys" in preview.text
    # Esikatselu ei tallenna mitään.
    assert (
        _owner_query("SELECT count(*) FROM sources WHERE source_key = 'fi/statute/2002/453'")[0][0]
        == 0
    )
    _add_ktjl(client, seeded)
    rows = _owner_query(
        "SELECT short_title, is_core, active, act_year, act_number FROM sources"
        " WHERE source_key = 'fi/statute/2002/453'"
    )
    assert rows == [("KTJL", False, True, 2002, 453)]
    page = client.get("/yllapito/lait?viesti=lisatty", headers=admin).text
    assert "KTJL" in page and "Laki on lisätty" in page
    audit = _owner_query("SELECT action FROM audit_events WHERE action = 'source.added'")
    assert audit


def test_add_requires_matching_preview_hash(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        "/yllapito/lait/lisaa",
        data={"year": "2002", "number": "453", "short_title": "KTJL", "sha256": "0" * 64},
        headers=as_user(seeded["platform_admin"]),
    )
    assert response.status_code == 422
    assert "ehti muuttua" in response.text
    assert _owner_query("SELECT count(*) FROM sources")[0][0] == 1


def test_add_duplicate_and_bad_input_are_rejected(client: TestClient, seeded: Ids) -> None:
    admin = as_user(seeded["platform_admin"])
    dup = client.post(
        "/yllapito/lait/esikatsele", data={"year": "2009", "number": "1599"}, headers=admin
    )
    assert dup.status_code == 422 and "jo lisätty" in dup.text
    for year, number in (("abc", "453"), ("2002", ""), ("1500", "1"), ("2002", "0")):
        bad = client.post(
            "/yllapito/lait/esikatsele", data={"year": year, "number": number}, headers=admin
        )
        assert bad.status_code == 422, (year, number)


def test_unknown_act_gives_friendly_error(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        "/yllapito/lait/esikatsele",
        data={"year": "1999", "number": "999"},
        headers=as_user(seeded["platform_admin"]),
    )
    assert response.status_code == 422
    assert "ei löytynyt" in response.text


def test_short_name_must_be_unique(client: TestClient, seeded: Ids) -> None:
    admin = as_user(seeded["platform_admin"])
    preview = client.post(
        "/yllapito/lait/esikatsele",
        data={"year": "2002", "number": "453", "short_title": "aoyl"},
        headers=admin,
    )
    sha = preview.text.split('name="sha256" value="')[1].split('"')[0]
    response = client.post(
        "/yllapito/lait/lisaa",
        data={"year": "2002", "number": "453", "short_title": "aoyl", "sha256": sha},
        headers=admin,
    )
    assert response.status_code == 422 and "jo toisen lain käytössä" in response.text


# --- Päivitys ---


def test_unchanged_check_creates_no_new_version(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        f"/yllapito/lait/{AOYL_PATH}/tarkista",
        headers=as_user(seeded["platform_admin"]),
        follow_redirects=False,
    )
    assert response.status_code == 303 and "ei-muutoksia" in response.headers["location"]
    assert (
        _owner_query(
            "SELECT count(*) FROM source_versions v JOIN sources s ON s.id = v.source_id WHERE s.is_core"
        )[0][0]
        == 1
    )
    assert (
        _owner_query("SELECT last_checked_at IS NOT NULL FROM sources WHERE is_core")[0][0] is True
    )


def test_changed_text_becomes_current_and_old_is_kept(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids, no_cooldown: None
) -> None:
    fetcher.files[(2009, 1599)] = changed_aoyl_xml()
    admin = as_user(seeded["platform_admin"])
    response = client.post(
        f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=admin, follow_redirects=False
    )
    assert response.status_code == 303 and "paivitetty" in response.headers["location"]
    versions = _owner_query(
        "SELECT v.version_label, v.change_summary FROM source_versions v"
        " JOIN sources s ON s.id = v.source_id WHERE s.is_core ORDER BY v.fetched_at"
    )
    assert [v[0] for v in versions] == ["20260535", "20270101"]  # vanha säilyy historiana
    summary = versions[1][1]
    assert isinstance(summary, dict)
    assert (summary["changed"], summary["added"], summary["removed"]) == (1, 0, 0)
    assert summary["items"][0] == {"kind": "muuttunut", "label": "4 luku 2 § 1 mom."}
    current = _owner_query(
        "SELECT v.version_label FROM sources s JOIN source_versions v ON v.id = s.current_version_id"
        " WHERE s.is_core"
    )
    assert current == [("20270101",)]
    page = client.get("/yllapito/lait", headers=admin).text
    assert "1 muuttunut" in page and "4 luku 2 § 1 mom." in page and "2 versiota" in page


def test_search_uses_only_the_new_version(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids, no_cooldown: None
) -> None:
    fetcher.files[(2009, 1599)] = changed_aoyl_xml()
    client.post(f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=as_user(seeded["platform_admin"]))
    with app_session(seeded) as db:
        hits = search_sections(db, "yhtiön kunnossapitovastuu luotettavuudesta")
    sec2 = [h for h in hits if h.citation_label == "AOYL 4 luku 2 §"]
    assert len(sec2) == 1  # ei kaksoiskappaleita vanhasta versiosta
    assert "uusi testilause luotettavuudesta" in sec2[0].subsections[0].text
    assert sec2[0].version_label == "20270101"


def test_old_ai_citations_still_render_after_update(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids, no_cooldown: None
) -> None:
    ask = client.post(
        f"/yhtiot/{seeded['company_a']}/kysy",
        data={"question": "Kuka vastaa kylpyhuoneen kunnossapitovastuusta?"},
        headers=as_user(seeded["shareholder_a"]),
        follow_redirects=False,
    )
    thread_url = ask.headers["location"].split("#")[0]
    fetcher.files[(2009, 1599)] = changed_aoyl_xml()
    client.post(f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=as_user(seeded["platform_admin"]))
    page = client.get(thread_url, headers=as_user(seeded["shareholder_a"]))
    assert page.status_code == 200
    assert "AOYL 4 luku" in page.text and "✓ lainaus tarkistettu" in page.text


def test_check_has_cooldown(
    client: TestClient, seeded: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALOAPURI_LAW_CHECK_COOLDOWN_SECONDS", "300")
    get_settings.cache_clear()
    try:
        admin = as_user(seeded["platform_admin"])
        first = client.post(
            f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=admin, follow_redirects=False
        )
        assert first.status_code == 303
        second = client.post(f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=admin)
        assert second.status_code == 429
        assert "tarkistettiin juuri äsken" in second.text
    finally:
        get_settings.cache_clear()


def test_check_all_reports_per_law_and_survives_one_failure(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids, no_cooldown: None
) -> None:
    _add_ktjl(client, seeded)
    fetcher.files[(2002, 453)] = FinlexError("Finlexiin ei saatu yhteyttä.")
    response = client.post(
        "/yllapito/lait/tarkista-kaikki", headers=as_user(seeded["platform_admin"])
    )
    assert response.status_code == 200
    assert "AOYL</strong>:" in response.text and "ei muutoksia" in response.text
    assert "Finlexiin ei saatu yhteyttä." in response.text


def test_suspicious_shrink_is_refused(
    client: TestClient,
    fetcher: FakeLawFetcher,
    seeded: Ids,
    no_cooldown: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updater, "MIN_SIZE_RATIO", 1.5)  # "uuden pitää olla 1,5× vanha" → hylätään
    fetcher.files[(2009, 1599)] = changed_aoyl_xml()
    response = client.post(
        f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=as_user(seeded["platform_admin"])
    )
    assert response.status_code == 422 and "huomattavasti pienempi" in response.text
    current = _owner_query(
        "SELECT v.version_label FROM sources s JOIN source_versions v ON v.id = s.current_version_id"
        " WHERE s.is_core"
    )
    assert current == [("20260535",)]


def test_fetch_failure_does_not_change_anything(
    client: TestClient, fetcher: FakeLawFetcher, seeded: Ids, no_cooldown: None
) -> None:
    fetcher.files[(2009, 1599)] = ActNotFound("Säädöstä ei löytynyt ajantasaisena versiona.")
    response = client.post(
        f"/yllapito/lait/{AOYL_PATH}/tarkista", headers=as_user(seeded["platform_admin"])
    )
    assert response.status_code == 422 and "ei löytynyt" in response.text
    assert _owner_query("SELECT count(*) FROM source_versions")[0][0] == 1


# --- Käytöstä poisto ---


def test_core_law_cannot_be_deactivated(client: TestClient, seeded: Ids) -> None:
    admin = as_user(seeded["platform_admin"])
    assert (
        client.get(f"/yllapito/lait/{AOYL_PATH}/poista-kaytosta", headers=admin).status_code == 404
    )
    response = client.post(
        f"/yllapito/lait/{AOYL_PATH}/kaytossa", data={"active": "0"}, headers=admin
    )
    assert response.status_code == 404
    assert _owner_query("SELECT active FROM sources WHERE is_core")[0][0] is True


def test_inactive_law_is_not_searched_and_can_be_restored(client: TestClient, seeded: Ids) -> None:
    _add_ktjl(client, seeded)
    admin = as_user(seeded["platform_admin"])
    question = "kiinteistötietojärjestelmän tarkoitus"

    def ktjl_found() -> bool:
        with app_session(seeded) as db:
            return any(h.citation_label.startswith("KTJL") for h in search_sections(db, question))

    assert ktjl_found()
    confirm = client.get(f"/yllapito/lait/{KTJL_PATH}/poista-kaytosta", headers=admin)
    assert confirm.status_code == 200 and "Poistetaanko" in confirm.text
    off = client.post(
        f"/yllapito/lait/{KTJL_PATH}/kaytossa",
        data={"active": "0"},
        headers=admin,
        follow_redirects=False,
    )
    assert off.status_code == 303
    assert not ktjl_found()
    client.post(f"/yllapito/lait/{KTJL_PATH}/kaytossa", data={"active": "1"}, headers=admin)
    assert ktjl_found()
    actions = {
        r[0] for r in _owner_query("SELECT action FROM audit_events WHERE action LIKE 'source.%'")
    }
    assert {"source.added", "source.deactivated", "source.activated"} <= actions


def test_aoyl_still_ranks_first_with_second_law_present(client: TestClient, seeded: Ids) -> None:
    _add_ktjl(client, seeded)
    with app_session(seeded) as db:
        for question in (
            "Kuka vastaa kylpyhuoneen kunnossapitovastuusta?",
            "Kenen vastuulla on yhtiön kunnossapito?",
        ):
            hits = search_sections(db, question)
            assert hits and hits[0].citation_label.startswith("AOYL"), question


# --- Tietokantatason suojaukset ---


def _as_app(ids: Ids, user: str, sql: str, **params: object) -> None:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"), {"u": str(ids[user])}
            )
            conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"),
                {"c": str(ids["company_a"])},
            )
            conn.execute(text(sql), params)
    finally:
        engine.dispose()


def test_manager_cannot_write_law_tables_directly(seeded: Ids) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        _as_app(
            seeded,
            "manager",
            "INSERT INTO sources (source_key, title, short_title, public_url, act_year, act_number)"
            " VALUES ('fi/statute/1999/1', 'x', 'X', 'https://x', 1999, 1)",
        )
    # RLS: luvaton UPDATE ei virhe vaan koskee nolla riviä – tieto pysyy ennallaan.
    _as_app(seeded, "manager", "UPDATE sources SET active = false")
    assert _owner_query("SELECT active FROM sources WHERE is_core")[0][0] is True


def test_nobody_can_delete_law_data(seeded: Ids) -> None:
    for user in ("platform_admin", "manager"):
        with pytest.raises(DBAPIError, match="permission denied"):
            _as_app(seeded, user, "DELETE FROM source_sections")


def test_manager_cannot_create_or_become_platform_admin(seeded: Ids) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        _as_app(
            seeded,
            "manager",
            "INSERT INTO users (id, display_name, is_platform_admin)"
            " VALUES (gen_random_uuid(), 'Pahantekijä', true)",
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        _as_app(
            seeded,
            "manager",
            "UPDATE users SET is_platform_admin = true WHERE id = :me",
            me=seeded["manager"],
        )
    # Tavallinen asukkaan lisäys toimii yhä (sarakekohtainen INSERT-oikeus riittää).
    response = TestClient(create_app()).post(
        f"/api/v1/companies/{seeded['company_a']}/members",
        json={"display_name": "Uusi Asukas", "role": "resident"},
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 201


def test_fetch_size_cap_and_host_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from taloapuri.sources import finlex

    with pytest.raises(ValueError):
        finlex.fetch("https://evil.example/akn")

    class Huge:
        def __enter__(self) -> "Huge":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, n: int = -1) -> bytes:
            return b"x" * (finlex.MAX_RESPONSE_BYTES + 1)

    monkeypatch.setattr(finlex.urllib.request, "urlopen", lambda *a, **k: Huge())
    with pytest.raises(FinlexError, match="liian suuri"):
        finlex.fetch(finlex.consolidated_url(2009, 1599))


def test_fetch_decompresses_gzip_and_caps_unpacked_size(monkeypatch: pytest.MonkeyPatch) -> None:
    import gzip

    from taloapuri.sources import finlex

    class Body:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __enter__(self) -> "Body":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, n: int = -1) -> bytes:
            return self.data

    url = finlex.consolidated_url(2002, 453)
    monkeypatch.setattr(
        finlex.urllib.request,
        "urlopen",
        lambda *a, **k: Body(gzip.compress(KTJL_FIXTURE.read_bytes())),
    )
    assert finlex.parse_akn(finlex.fetch(url)).sections

    bomb = gzip.compress(b"x" * (finlex.MAX_RESPONSE_BYTES + 10))
    monkeypatch.setattr(finlex.urllib.request, "urlopen", lambda *a, **k: Body(bomb))
    with pytest.raises(FinlexError, match="liian suuri"):
        finlex.fetch(url)


def test_compute_diff_matches_by_numbers_not_ids() -> None:
    from taloapuri.sources.finlex import ParsedSection

    def sec(sub: int, text_: str, eid: str) -> ParsedSection:
        return ParsedSection(1, eid, "4 luku", None, "2 §", None, sub, text_)

    old = {("4 luku", "2 §", 1): "a", ("4 luku", "2 §", 2): "b", ("4 luku", "2 §", 3): "c"}
    new = [sec(1, "a", "x"), sec(2, "B", "ykv2026"), sec(4, "d", "z")]
    diff = updater.compute_diff(old, new)
    assert (diff.added, diff.changed, diff.removed) == (1, 1, 1)
    assert {i["kind"] for i in diff.items} == {"lisätty", "muuttunut", "poistettu"}
