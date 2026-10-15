"""Lukemattomat asiat, uusimmat tapahtumat ja elävien päivitysten tilakysely."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from taloapuri.config import Settings
from tests.conftest import TEST_MIGRATION_DATABASE_URL, as_user

Ids = dict[str, uuid.UUID]


def _damage(client: TestClient, ids: Ids, title: str = "Pesukone vuotaa") -> str:
    response = client.post(
        f"/yhtiot/{ids['company_a']}/asiat",
        data={"case_type": "damage", "title": title, "event_date": "2026-10-01", "ongoing": "no"},
        headers=as_user(ids["shareholder_a"]),
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("?")[0]


def _status(client: TestClient, ids: Ids, user: str) -> dict[str, object]:
    response = client.get(f"/yhtiot/{ids['company_a']}/tilanne", headers=as_user(ids[user]))
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    return response.json()  # type: ignore[no-any-return]


@pytest.mark.db
def test_new_report_is_unread_for_manager_until_opened(client: TestClient, seeded: Ids) -> None:
    assert _status(client, seeded, "manager")["unread_cases"] == 0
    url = _damage(client, seeded)
    assert _status(client, seeded, "manager")["unread_cases"] == 1
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])
    ).text
    assert "Uusi vahinkoilmoitus:" in dashboard
    assert 'class="unread"' in dashboard
    feed = dashboard.split('id="uusimmat"')[1].split("</section>")[0]
    assert "Olli Osakas" in feed  # kuka teki ilmoituksen
    # Avaaminen merkitsee luetuksi; myös sivun oma yläpalkki näyttää jo 0.
    page = client.get(url, headers=as_user(seeded["manager"])).text
    assert "🔔" not in page  # yläpalkin kello poistettu: merkinnät ovat listassa
    assert _status(client, seeded, "manager")["unread_cases"] == 0
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])
    ).text
    assert 'class="unread"' not in dashboard


@pytest.mark.db
def test_own_case_is_never_unread(client: TestClient, seeded: Ids) -> None:
    _damage(client, seeded)
    assert _status(client, seeded, "shareholder_a")["unread_cases"] == 0


@pytest.mark.db
def test_info_request_marks_case_updated_for_reporter(client: TestClient, seeded: Ids) -> None:
    url = _damage(client, seeded)
    case_id = url.rsplit("/", 1)[-1]
    client.post(
        f"/api/v1/companies/{seeded['company_a']}/cases/{case_id}/transitions",
        json={"action": "submit", "expected_version": 1},
        headers=as_user(seeded["shareholder_a"]),
    )
    client.post(
        f"{url}/lisatietopyynto",
        data={"question": "Milloin vuoto alkoi?", "expected_version": "2"},
        headers=as_user(seeded["manager"]),
    )
    assert _status(client, seeded, "shareholder_a")["unread_cases"] == 1
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Päivitetty" in dashboard
    client.get(url, headers=as_user(seeded["shareholder_a"]))
    assert _status(client, seeded, "shareholder_a")["unread_cases"] == 0


@pytest.mark.db
def test_other_resident_never_sees_the_case(client: TestClient, seeded: Ids) -> None:
    _damage(client, seeded, title="Yksityinen vuoto")
    assert _status(client, seeded, "resident_a2")["unread_cases"] == 0
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["resident_a2"])
    ).text
    assert "Yksityinen vuoto" not in dashboard


@pytest.mark.db
def test_feed_version_changes_after_new_activity(client: TestClient, seeded: Ids) -> None:
    before = _status(client, seeded, "manager")["feed_version"]
    _damage(client, seeded)
    after = _status(client, seeded, "manager")["feed_version"]
    assert after and after != before


@pytest.mark.db
def test_status_requires_login(client: TestClient, seeded: Ids) -> None:
    response = client.get(f"/yhtiot/{seeded['company_a']}/tilanne", follow_redirects=False)
    assert response.status_code in (303, 401)


@pytest.mark.db
def test_old_unopened_case_is_not_unread(client: TestClient, seeded: Ids) -> None:
    url = _damage(client, seeded)
    case_id = url.rsplit("/", 1)[-1]
    assert TEST_MIGRATION_DATABASE_URL
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    with engine.begin() as conn:  # siirretään tapahtumat 40 päivää taaksepäin
        conn.execute(
            text("UPDATE case_events SET created_at = :t WHERE case_id = :c"),
            {"t": datetime.now(UTC) - timedelta(days=40), "c": case_id},
        )
    engine.dispose()
    assert _status(client, seeded, "manager")["unread_cases"] == 0


def test_company_pages_load_live_script_only_there(client: TestClient) -> None:
    front = client.get("/").text
    assert "live-updates.js" not in front


@pytest.mark.db
def test_company_page_has_live_hooks(client: TestClient, seeded: Ids) -> None:
    html = client.get(f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])).text
    assert 'src="/static/live-updates.js"' in html
    assert f'data-status-url="/yhtiot/{seeded["company_a"]}/tilanne"' in html
    assert client.get("/static/live-updates.js").status_code == 200


def test_api_key_is_read_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-test-123\nTALOAPURI_AI_ENABLED=true\n")
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.anthropic_api_key == "sk-ant-test-123"
    assert settings.ai_enabled is True


def test_real_ai_is_never_used_in_tests() -> None:
    from taloapuri.web.chat_routes import get_ai_provider

    assert get_ai_provider() is None
