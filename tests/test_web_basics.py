"""Testit, jotka eivät tarvitse tietokantaa."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_is_versioned(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/companies/{company_id}/cases" in paths


def test_first_aid_page_works_without_database_or_ai(client: TestClient) -> None:
    response = client.get("/ensiohjeet/vesivahinko")
    assert response.status_code == 200
    assert "112" in response.text
    assert "Pysäytä vesi" in response.text


def test_pages_have_basic_accessibility_structure(client: TestClient) -> None:
    for path in ("/", "/ensiohjeet/vesivahinko"):
        html = client.get(path).text
        assert '<html lang="fi"' in html
        assert 'href="#sisalto"' in html  # ohituslinkki
        assert '<main id="sisalto"' in html
        assert html.count("<h1") == 1


def test_api_requires_login(client: TestClient) -> None:
    response = client.get("/api/v1/companies/00000000-0000-0000-0000-000000000000/cases")
    assert response.status_code == 401


def test_invalid_dev_user_id_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/companies/00000000-0000-0000-0000-000000000000/cases",
        headers={"X-Dev-User-Id": "not-a-uuid"},
    )
    assert response.status_code == 401


# --- Virhesivut (vaihe 0) ---


def test_web_page_without_login_redirects_to_front_page(client: TestClient) -> None:
    response = client.get("/yhtiot/00000000-0000-0000-0000-000000000000", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_web_404_is_friendly_html(client: TestClient) -> None:
    response = client.get("/ei-ole-olemassa")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Sivua ei löytynyt" in response.text


def test_api_404_stays_json(client: TestClient) -> None:
    response = client.get("/api/v1/ei-ole-olemassa")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


# --- Tumma tila ---


def test_theme_defaults_to_auto(client: TestClient) -> None:
    assert 'data-theme="auto"' in client.get("/").text


def test_theme_cookie_sets_dark(client: TestClient) -> None:
    response = client.post(
        "/asetukset/teema",
        data={"theme": "dark", "next": "/ensiohjeet/vesivahinko"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ensiohjeet/vesivahinko"
    assert 'data-theme="dark"' in client.get("/").text


def test_invalid_theme_falls_back_to_auto(client: TestClient) -> None:
    client.cookies.set("theme", "<script>")
    assert 'data-theme="auto"' in client.get("/").text


def test_theme_redirect_blocks_open_redirect(client: TestClient) -> None:
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example"):
        response = client.post(
            "/asetukset/teema", data={"theme": "light", "next": bad}, follow_redirects=False
        )
        assert response.headers["location"] == "/"
