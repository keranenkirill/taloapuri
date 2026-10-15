"""Suorat viestit: säännöt, näkyvyys ja lukemattomat. Vaativat PostgreSQL:n."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]


def _send(client: TestClient, ids: Ids, sender: str, recipient: str, body: str = "Hei!") -> str:
    response = client.post(
        f"/yhtiot/{ids['company_a']}/viestit",
        data={"recipient": str(ids[recipient]), "subject": "Kysymys", "body": body},
        headers=as_user(ids[sender]),
        follow_redirects=False,
    )
    if response.status_code != 303:
        return ""
    return response.headers["location"].split("?")[0]


def _header(client: TestClient, ids: Ids, user: str) -> str:
    html = client.get(f"/yhtiot/{ids['company_a']}", headers=as_user(ids[user])).text
    return html.split("</header>")[0]


def _has_unread_messages(header: str) -> bool:
    return 'data-live="messages">' in header  # piilotettu laskuri: data-live="messages" hidden


def test_resident_messages_manager_and_manager_replies(client: TestClient, seeded: Ids) -> None:
    thread = _send(client, seeded, "shareholder_a", "manager", "Saako parvekkeelle laittaa lasit?")
    assert thread
    assert _has_unread_messages(_header(client, seeded, "manager"))
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])
    ).text
    assert "Uusi viesti:" in dashboard
    page = client.get(thread, headers=as_user(seeded["manager"])).text
    assert "Saako parvekkeelle laittaa lasit?" in page
    assert "Olli Osakas" in page
    # Luettu → laskuri nollautuu.
    assert not _has_unread_messages(_header(client, seeded, "manager"))
    client.post(
        thread, data={"body": "Kyllä, tee muutostyöilmoitus."}, headers=as_user(seeded["manager"])
    )
    assert _has_unread_messages(_header(client, seeded, "shareholder_a"))
    reply_page = client.get(thread, headers=as_user(seeded["shareholder_a"])).text
    assert "Kyllä, tee muutostyöilmoitus." in reply_page


def test_resident_cannot_message_resident(client: TestClient, seeded: Ids) -> None:
    form = client.get(
        f"/yhtiot/{seeded['company_a']}/viestit/uusi", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Ville Vuokralainen" not in form
    assert "Isa Isännöitsijä" in form
    assert _send(client, seeded, "shareholder_a", "resident_a2") == ""


def test_manager_can_message_any_member(client: TestClient, seeded: Ids) -> None:
    assert _send(client, seeded, "manager", "resident_a2")


def test_definer_function_enforces_rule(seeded: Ids) -> None:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with pytest.raises(DBAPIError, match="recipient not allowed"), engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(seeded["shareholder_a"])},
            )
            conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"),
                {"c": str(seeded["company_a"])},
            )
            conn.execute(
                text("SELECT app_start_thread(:r, 'x', 'y')"), {"r": str(seeded["resident_a2"])}
            )
    finally:
        engine.dispose()


def test_non_participant_cannot_read_or_reply(client: TestClient, seeded: Ids) -> None:
    thread = _send(client, seeded, "shareholder_a", "manager")
    assert client.get(thread, headers=as_user(seeded["resident_a2"])).status_code == 404
    response = client.post(thread, data={"body": "Hei"}, headers=as_user(seeded["resident_a2"]))
    assert response.status_code == 404


def test_other_company_cannot_open_thread(client: TestClient, seeded: Ids) -> None:
    thread = _send(client, seeded, "manager", "shareholder_a")
    other = thread.replace(str(seeded["company_a"]), str(seeded["company_b"]))
    assert client.get(other, headers=as_user(seeded["manager"])).status_code == 404


def test_empty_message_is_rejected(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        f"/yhtiot/{seeded['company_a']}/viestit",
        data={"recipient": str(seeded["manager"]), "subject": "", "body": ""},
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 422
    assert "Kirjoita viestille aihe" in response.text
