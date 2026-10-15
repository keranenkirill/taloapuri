"""Hallituksen pöytäkirjat: lataus, näkyvyys ja eristys. Vaativat PostgreSQL:n."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]
PDF = b"%PDF-1.4\n% testi\n%%EOF\n"


def _upload(
    client: TestClient,
    ids: Ids,
    *,
    title: str = "Hallituksen kokous 6/2026",
    visible: bool = True,
    data: bytes = PDF,
    filename: str = "pöytäkirja 6.pdf",
    user: str = "manager",
) -> int:
    form = {"title": title, "meeting_date": "2026-10-01", "description": "Päätettiin katosta."}
    if visible:
        form["visible"] = "1"
    response = client.post(
        f"/yhtiot/{ids['company_a']}/poytakirjat",
        data=form,
        files={"file": (filename, data, "application/pdf")},
        headers=as_user(ids[user]),
        follow_redirects=False,
    )
    return response.status_code


def _docs(client: TestClient, ids: Ids, user: str) -> list[dict[str, object]]:
    response = client.get(
        f"/api/v1/companies/{ids['company_a']}/documents", headers=as_user(ids[user])
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def test_manager_upload_is_shown_to_shareholder_with_uploader(
    client: TestClient, seeded: Ids
) -> None:
    assert _upload(client, seeded) == 303
    html = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Uusimmat tapahtumat" in html
    assert "Hallituksen kokous 6/2026" in html
    assert "Lisännyt Isa Isännöitsijä" in html
    # Uusin ensin.
    assert html.index("6/2026") < html.index("4/2026")


def test_shareholder_downloads_exact_bytes_with_safe_headers(
    client: TestClient, seeded: Ids
) -> None:
    _upload(client, seeded)
    doc = next(
        d
        for d in _docs(client, seeded, "shareholder_a")
        if d["title"] == "Hallituksen kokous 6/2026"
    )
    response = client.get(str(doc["download_url"]), headers=as_user(seeded["shareholder_a"]))
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private" in response.headers["cache-control"]
    assert "attachment" in response.headers["content-disposition"]
    assert doc["filename"] == "pöytäkirja 6.pdf"


def test_hidden_document_only_for_board(client: TestClient, seeded: Ids) -> None:
    titles = [d["title"] for d in _docs(client, seeded, "shareholder_a")]
    assert "Hallituksen kokous 4/2026" in titles
    assert "Hallituksen kokous 5/2026 (luottamuksellinen)" not in titles
    manager_docs = _docs(client, seeded, "manager")
    hidden = next(d for d in manager_docs if "luottamuksellinen" in str(d["title"]))
    response = client.get(str(hidden["download_url"]), headers=as_user(seeded["shareholder_a"]))
    assert response.status_code == 404


def test_non_pdf_and_too_large_are_rejected(client: TestClient, seeded: Ids) -> None:
    assert _upload(client, seeded, data=b"MZ\x90\x00 not a pdf", filename="virus.pdf") == 422
    big = PDF + b"0" * (10 * 1024 * 1024)
    assert _upload(client, seeded, data=big) == 422
    titles = [d["title"] for d in _docs(client, seeded, "manager")]
    assert "Hallituksen kokous 6/2026" not in titles


def test_shareholder_cannot_upload(client: TestClient, seeded: Ids) -> None:
    assert _upload(client, seeded, user="shareholder_a") == 403


def test_other_company_cannot_download(client: TestClient, seeded: Ids) -> None:
    doc = _docs(client, seeded, "manager")[0]
    url = str(doc["download_url"]).replace(str(seeded["company_a"]), str(seeded["company_b"]))
    response = client.get(url, headers=as_user(seeded["board_b"]))
    assert response.status_code == 404


def test_visibility_toggle_and_remove(client: TestClient, seeded: Ids) -> None:
    hidden = next(d for d in _docs(client, seeded, "manager") if not d["visible_to_residents"])
    base = f"/yhtiot/{seeded['company_a']}/poytakirjat/{hidden['id']}"
    manager = as_user(seeded["manager"])
    client.post(f"{base}/nakyvyys", data={"visible": "1"}, headers=manager)
    assert hidden["title"] in [d["title"] for d in _docs(client, seeded, "shareholder_a")]
    client.post(f"{base}/poista", headers=manager)
    assert hidden["title"] not in [d["title"] for d in _docs(client, seeded, "manager")]
    denied = client.post(
        f"{base}/nakyvyys", data={"visible": "0"}, headers=as_user(seeded["shareholder_a"])
    )
    assert denied.status_code in (403, 404)


def test_rls_denies_document_insert_by_non_manager(seeded: Ids) -> None:
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
                    "INSERT INTO company_documents (housing_company_id, title, uploaded_by,"
                    " uploaded_by_name, filename, content_type, size_bytes, sha256)"
                    " VALUES (:c, 'x', :u, 'x', 'x.pdf', 'application/pdf', 1, repeat('0', 64))"
                ),
                {"u": str(seeded["shareholder_a"]), "c": str(seeded["company_a"])},
            )
    finally:
        engine.dispose()
