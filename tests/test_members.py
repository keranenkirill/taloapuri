"""Asukkaiden hallinta ja huoneiston historia (vaiheet 2–3). Vaativat PostgreSQL:n."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]


def _api(company: uuid.UUID, path: str = "") -> str:
    return f"/api/v1/companies/{company}{path}"


def _add_resident(client: TestClient, ids: Ids, apartment: str = "apt_a1") -> uuid.UUID:
    response = client.post(
        _api(ids["company_a"], "/members"),
        json={
            "display_name": "Uusi Asukas",
            "role": "shareholder",
            "apartment_id": str(ids[apartment]),
        },
        headers=as_user(ids["manager"]),
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["membership_id"])


def _user_of(client: TestClient, ids: Ids, membership_id: uuid.UUID) -> uuid.UUID:
    members = client.get(_api(ids["company_a"], "/members"), headers=as_user(ids["manager"]))
    row = next(m for m in members.json() if m["membership_id"] == str(membership_id))
    return uuid.UUID(row["user_id"])


# --- Jäsenten hallinta ---


def test_manager_adds_resident_who_can_then_access(client: TestClient, seeded: Ids) -> None:
    membership_id = _add_resident(client, seeded)
    new_user = _user_of(client, seeded, membership_id)
    response = client.get(_api(seeded["company_a"], "/cases"), headers=as_user(new_user))
    assert response.status_code == 200


def test_member_list_shows_apartments_and_status(client: TestClient, seeded: Ids) -> None:
    rows = client.get(
        _api(seeded["company_a"], "/members"), headers=as_user(seeded["manager"])
    ).json()
    olli = next(r for r in rows if r["display_name"] == "Olli Osakas")
    assert olli["apartments"] == ["A 1"]
    assert olli["active"] is True
    maija = next(r for r in rows if r["display_name"] == "Maija Muuttanut")
    assert maija["active"] is False


def test_shareholder_cannot_list_or_add_members(client: TestClient, seeded: Ids) -> None:
    headers = as_user(seeded["shareholder_a"])
    assert client.get(_api(seeded["company_a"], "/members"), headers=headers).status_code == 403
    response = client.post(
        _api(seeded["company_a"], "/members"),
        json={"display_name": "X", "role": "resident"},
        headers=headers,
    )
    assert response.status_code == 403
    web = client.get(f"/yhtiot/{seeded['company_a']}/asukkaat", headers=headers)
    assert web.status_code == 403
    assert "Sinulla ei ole oikeutta" in web.text


def test_manager_cannot_add_board_roles(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        _api(seeded["company_a"], "/members"),
        json={"display_name": "X", "role": "board_member"},
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 422


def test_ended_membership_loses_access_immediately(client: TestClient, seeded: Ids) -> None:
    membership_id = _add_resident(client, seeded)
    new_user = _user_of(client, seeded, membership_id)
    ended = client.post(
        _api(seeded["company_a"], f"/members/{membership_id}/end"),
        headers=as_user(seeded["manager"]),
    )
    assert ended.status_code == 204
    response = client.get(_api(seeded["company_a"], "/cases"), headers=as_user(new_user))
    assert response.status_code == 404


def test_manager_cannot_end_own_membership(client: TestClient, seeded: Ids) -> None:
    rows = client.get(
        _api(seeded["company_a"], "/members"), headers=as_user(seeded["manager"])
    ).json()
    own = next(r for r in rows if r["user_id"] == str(seeded["manager"]))
    response = client.post(
        _api(seeded["company_a"], f"/members/{own['membership_id']}/end"),
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 403


def test_cross_company_member_management_is_blocked(client: TestClient, seeded: Ids) -> None:
    # board_b on hallituksen jäsen B:ssä, ei isännöitsijä → ei oikeutta lisätä.
    response = client.post(
        _api(seeded["company_b"], "/members"),
        json={"display_name": "X", "role": "resident"},
        headers=as_user(seeded["board_b"]),
    )
    assert response.status_code == 403
    # Isännöitsijä ei voi liittää yhtiön A huoneistoa yhtiön B jäseneen.
    response = client.post(
        _api(seeded["company_b"], "/members"),
        json={"display_name": "X", "role": "resident", "apartment_id": str(seeded["apt_a1"])},
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 422


def test_rls_denies_membership_insert_by_non_manager(seeded: Ids) -> None:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with pytest.raises(DBAPIError, match="row-level security"), engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(seeded["shareholder_a"])},
            )
            conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"),
                {"c": str(seeded["company_a"])},
            )
            conn.execute(
                text(
                    "INSERT INTO memberships (user_id, housing_company_id, role, invited_by)"
                    " VALUES (:u, :c, 'property_manager', :u)"
                ),
                {"u": str(seeded["shareholder_a"]), "c": str(seeded["company_a"])},
            )
    finally:
        engine.dispose()


# --- Huoneiston historia ---


def _history(client: TestClient, ids: Ids, user: str, apartment: str) -> list[dict[str, Any]]:
    response = client.get(
        _api(ids["company_a"], f"/apartments/{ids[apartment]}/history"),
        headers=as_user(ids[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_new_occupant_sees_history_without_personal_data(client: TestClient, seeded: Ids) -> None:
    history = _history(client, seeded, "shareholder_a", "apt_a1")
    assert len(history) == 1
    row = history[0]
    assert row["case_type"] == "damage"
    assert row["status"] == "closed"
    assert row["history_note"] == "Keittiön lattia ja kaapisto uusittu vesivahingon jälkeen."
    assert row["closed_at"] is not None
    assert set(row) == {"case_type", "status", "event_date", "closed_at", "history_note"}


def test_history_is_behind_button_and_hides_private_text(client: TestClient, seeded: Ids) -> None:
    headers = as_user(seeded["shareholder_a"])
    dashboard = client.get(f"/yhtiot/{seeded['company_a']}", headers=headers).text
    assert "Huoneiston historia" in dashboard
    assert "Keittiön lattia ja kaapisto uusittu" not in dashboard
    html = client.get(f"/yhtiot/{seeded['company_a']}/huoneistohistoria", headers=headers).text
    assert "Huoneisto A 1" in html
    assert "Keittiön lattia ja kaapisto uusittu" in html
    assert "Maijan astianpesukone" not in html
    assert "Yksityinen kuvaus" not in html
    assert "Maija" not in html


def test_manager_without_apartment_sees_no_history_button(client: TestClient, seeded: Ids) -> None:
    html = client.get(f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])).text
    assert "huoneistohistoria" not in html


def test_new_occupant_cannot_open_previous_occupants_case(client: TestClient, seeded: Ids) -> None:
    response = client.get(
        _api(seeded["company_a"], f"/cases/{seeded['old_case_a1']}"),
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 404


def test_other_apartment_occupant_sees_no_history(client: TestClient, seeded: Ids) -> None:
    assert _history(client, seeded, "resident_a2", "apt_a1") == []


def test_former_occupant_has_no_access(client: TestClient, seeded: Ids) -> None:
    response = client.get(
        _api(seeded["company_a"], f"/apartments/{seeded['apt_a1']}/history"),
        headers=as_user(seeded["former_resident_a1"]),
    )
    assert response.status_code == 404


def test_manager_sees_history_on_apartments_page(client: TestClient, seeded: Ids) -> None:
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/huoneistot", headers=as_user(seeded["manager"])
    ).text
    assert "Keittiön lattia ja kaapisto uusittu" in html


def test_shareholder_can_link_case_only_to_own_apartment(client: TestClient, seeded: Ids) -> None:
    headers = as_user(seeded["shareholder_a"])
    body = {"case_type": "damage", "title": "Vuoto", "event_date": "2026-10-01"}
    own = client.post(
        _api(seeded["company_a"], "/cases"),
        json={**body, "apartment_id": str(seeded["apt_a1"])},
        headers=headers,
    )
    assert own.status_code == 201
    other = client.post(
        _api(seeded["company_a"], "/cases"),
        json={**body, "apartment_id": str(seeded["apt_a2"])},
        headers=headers,
    )
    assert other.status_code == 422


def test_only_manager_can_write_history_note(client: TestClient, seeded: Ids) -> None:
    case = client.get(
        _api(seeded["company_a"], f"/cases/{seeded['old_case_a1']}"),
        headers=as_user(seeded["manager"]),
    ).json()
    url = f"/yhtiot/{seeded['company_a']}/asiat/{seeded['old_case_a1']}/historiamerkinta"
    data = {"history_note": "Uusi merkintä", "expected_version": str(case["version"])}
    denied = client.post(
        url, data=data, headers=as_user(seeded["shareholder_a"]), follow_redirects=False
    )
    assert denied.status_code in (403, 404)
    ok = client.post(url, data=data, headers=as_user(seeded["manager"]), follow_redirects=False)
    assert ok.status_code == 303
    assert _history(client, seeded, "shareholder_a", "apt_a1")[0]["history_note"] == "Uusi merkintä"
