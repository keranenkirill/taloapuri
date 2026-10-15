"""Sähköpostikirjautuminen, yläpalkin käyttäjätiedot ja asetukset. Vaativat PostgreSQL:n."""

import uuid

import pytest
from fastapi.testclient import TestClient

from taloapuri.config import get_settings
from tests.conftest import as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]


def _login(client: TestClient, email: str) -> int:
    response = client.post("/dev/kirjaudu", data={"email": email}, follow_redirects=False)
    assert response.status_code == 303
    return 0 if "virhe" in response.headers["location"] else 1


def test_email_login_is_case_insensitive(client: TestClient, seeded: Ids) -> None:
    assert _login(client, "  OLLI@Esimerkki.FI ") == 1
    html = client.get("/").text
    assert "As Oy Esimerkkikoivu" in html
    assert "Olli Osakas" in html  # yläpalkki


def test_unknown_email_shows_error(client: TestClient, seeded: Ids) -> None:
    assert _login(client, "ei-ole@esimerkki.fi") == 0
    html = client.get("/?virhe=kirjautuminen").text
    assert "Sähköpostiosoitteella ei löytynyt käyttäjää" in html
    assert client.cookies.get("dev_user_id") is None


def test_login_disabled_outside_dev(
    client: TestClient, seeded: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALOAPURI_ENV", "production")
    get_settings.cache_clear()
    try:
        response = client.post("/dev/kirjaudu", data={"email": "olli@esimerkki.fi"})
        assert response.status_code == 404
    finally:
        monkeypatch.setenv("TALOAPURI_ENV", "test")
        get_settings.cache_clear()


def test_header_shows_name_and_apartment(client: TestClient, seeded: Ids) -> None:
    html = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Olli Osakas" in html
    assert "Huoneisto A 1" in html
    assert 'href="/asetukset?takaisin=' in html
    # Isännöitsijällä ei ole huoneistoa: vain nimi.
    manager = client.get(f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["manager"])).text
    assert "Isa Isännöitsijä" in manager
    assert "Huoneisto A" not in manager.split("</header>")[0]


def test_settings_requires_login(client: TestClient) -> None:
    response = client.get("/asetukset", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_change_email_and_login_with_new_address(client: TestClient, seeded: Ids) -> None:
    headers = as_user(seeded["shareholder_a"])
    page = client.get("/asetukset", headers=headers).text
    assert "olli@esimerkki.fi" in page
    response = client.post(
        "/asetukset/sahkoposti",
        data={"email": "olli.uusi@gmail.com", "takaisin": "/"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert _login(client, "olli.uusi@gmail.com") == 1
    assert _login(client, "olli@esimerkki.fi") == 0


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("ei-sahkoposti", "Tarkista sähköpostiosoite"),
        ("ISA@esimerkki.fi", "jo toisen käyttäjän käytössä"),
    ],
)
def test_invalid_or_duplicate_email_is_rejected(
    client: TestClient, seeded: Ids, email: str, message: str
) -> None:
    response = client.post(
        "/asetukset/sahkoposti",
        data={"email": email},
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 422
    assert message in response.text


def test_logout_clears_login(client: TestClient, seeded: Ids) -> None:
    _login(client, "olli@esimerkki.fi")
    assert "Olli Osakas" in client.get("/").text
    client.post("/dev/kirjaudu-ulos")
    html = client.get("/").text
    assert "Olli Osakas" not in html
    assert "Kirjaudu sisään" in html


def test_settings_page_has_theme_and_logout(client: TestClient, seeded: Ids) -> None:
    html = client.get("/asetukset", headers=as_user(seeded["shareholder_a"])).text
    assert 'action="/asetukset/teema"' in html
    assert 'action="/dev/kirjaudu-ulos"' in html
