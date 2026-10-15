"""Tenant-eristyksen ja käyttöoikeuksien testit (US-6). Vaativat PostgreSQL:n.

Ajo: docker compose up -d && pytest -m db
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]


def _cases_url(company: uuid.UUID) -> str:
    return f"/api/v1/companies/{company}/cases"


def _create(client: TestClient, user: uuid.UUID, company: uuid.UUID, title: str) -> dict:  # type: ignore[type-arg]
    response = client.post(
        _cases_url(company),
        json={"case_type": "damage", "title": title, "event_date": "2026-10-01"},
        headers=as_user(user),
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_manager_sees_only_selected_company_cases(client: TestClient, seeded: Ids) -> None:
    _create(client, seeded["manager"], seeded["company_a"], "A:n vuoto")
    _create(client, seeded["manager"], seeded["company_b"], "B:n vuoto")

    titles_a = [
        c["title"]
        for c in client.get(
            _cases_url(seeded["company_a"]), headers=as_user(seeded["manager"])
        ).json()
    ]
    assert "A:n vuoto" in titles_a
    assert "B:n vuoto" not in titles_a


def test_non_member_gets_404_not_403(client: TestClient, seeded: Ids) -> None:
    response = client.get(_cases_url(seeded["company_b"]), headers=as_user(seeded["shareholder_a"]))
    assert response.status_code == 404


def test_case_id_from_other_company_is_not_found(client: TestClient, seeded: Ids) -> None:
    case_b = _create(client, seeded["manager"], seeded["company_b"], "B:n asia")
    response = client.get(
        f"{_cases_url(seeded['company_a'])}/{case_b['id']}",
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 404


def test_shareholder_sees_only_own_cases(client: TestClient, seeded: Ids) -> None:
    managers = _create(client, seeded["manager"], seeded["company_a"], "Hallituksen asia")
    _create(client, seeded["shareholder_a"], seeded["company_a"], "Oma vuoto")

    listed = client.get(
        _cases_url(seeded["company_a"]), headers=as_user(seeded["shareholder_a"])
    ).json()
    assert [c["title"] for c in listed] == ["Oma vuoto"]
    direct = client.get(
        f"{_cases_url(seeded['company_a'])}/{managers['id']}",
        headers=as_user(seeded["shareholder_a"]),
    )
    assert direct.status_code == 404


def test_expired_membership_has_no_access(client: TestClient, seeded: Ids) -> None:
    response = client.get(
        _cases_url(seeded["company_a"]), headers=as_user(seeded["former_board_a"])
    )
    assert response.status_code == 404


def test_shareholder_cannot_approve(client: TestClient, seeded: Ids) -> None:
    case = _create(client, seeded["shareholder_a"], seeded["company_a"], "Oma vuoto")
    url = f"{_cases_url(seeded['company_a'])}/{case['id']}/transitions"
    headers = as_user(seeded["shareholder_a"])
    submitted = client.post(url, json={"action": "submit", "expected_version": 1}, headers=headers)
    assert submitted.status_code == 200
    approve = client.post(url, json={"action": "approve", "expected_version": 2}, headers=headers)
    assert approve.status_code == 403


def test_stale_version_is_rejected(client: TestClient, seeded: Ids) -> None:
    case = _create(client, seeded["manager"], seeded["company_a"], "Vuoto")
    url = f"{_cases_url(seeded['company_a'])}/{case['id']}/transitions"
    headers = as_user(seeded["manager"])
    first = client.post(url, json={"action": "submit", "expected_version": 1}, headers=headers)
    assert first.status_code == 200
    # Toinen välilehti yrittää samaa vanhalla versiolla.
    second = client.post(url, json={"action": "cancel", "expected_version": 1}, headers=headers)
    assert second.status_code == 409


# --- Suorat tietokantatestit sovellusroolilla: RLS pitää, vaikka sovelluskoodi unohtaisi rajauksen.


@pytest.fixture
def app_engine():  # type: ignore[no-untyped-def]
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


def test_rls_without_context_returns_nothing(  # type: ignore[no-untyped-def]
    client: TestClient, seeded: Ids, app_engine
) -> None:
    _create(client, seeded["manager"], seeded["company_a"], "Vuoto")
    with app_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM housing_companies")).scalar_one() == 0


def test_rls_blocks_company_context_without_membership(  # type: ignore[no-untyped-def]
    client: TestClient, seeded: Ids, app_engine
) -> None:
    _create(client, seeded["manager"], seeded["company_b"], "B:n vuoto")
    with app_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_user_id', :u, true)"),
            {"u": str(seeded["shareholder_a"])},
        )
        conn.execute(
            text("SELECT set_config('app.current_company_id', :c, true)"),
            {"c": str(seeded["company_b"])},
        )
        assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 0


def test_context_does_not_leak_between_transactions(  # type: ignore[no-untyped-def]
    seeded: Ids, app_engine
) -> None:
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(seeded["manager"])},
            )
        with conn.begin():
            value = conn.execute(
                text("SELECT current_setting('app.current_user_id', true)")
            ).scalar_one()
            assert not value


def test_audit_log_is_append_only(  # type: ignore[no-untyped-def]
    client: TestClient, seeded: Ids, app_engine
) -> None:
    _create(client, seeded["manager"], seeded["company_a"], "Vuoto")
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET action = 'x'"))
    with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))


def test_case_event_cannot_point_to_other_company_case(  # type: ignore[no-untyped-def]
    client: TestClient, seeded: Ids, app_engine
) -> None:
    case_b = _create(client, seeded["manager"], seeded["company_b"], "B:n asia")
    with pytest.raises(DBAPIError), app_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_user_id', :u, true)"),
            {"u": str(seeded["manager"])},
        )
        conn.execute(
            text("SELECT set_config('app.current_company_id', :c, true)"),
            {"c": str(seeded["company_a"])},
        )
        conn.execute(
            text(
                "INSERT INTO case_events (housing_company_id, case_id, event_type, actor_user_id)"
                " VALUES (:c, :case, 'note', :u)"
            ),
            {"c": str(seeded["company_a"]), "case": case_b["id"], "u": str(seeded["manager"])},
        )
