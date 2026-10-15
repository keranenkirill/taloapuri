"""Vahinkoilmoitus ja tarjouspyyntö omilla lomakkeillaan, lisätietopyynnöt ja valokuvat.

Vaativat PostgreSQL:n.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from taloapuri.services.attachments import process_image
from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]


def jpeg_with_gps(width: int = 400, height: int = 200, orientation: int = 6) -> bytes:
    """JPEG, jossa on GPS-sijainti ja EXIF-suunta (6 = käännä 90°)."""
    image = Image.new("RGB", (width, height), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (60.0, 10.0, 0.0)
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _damage(
    client: TestClient,
    ids: Ids,
    user: str = "shareholder_a",
    photos: list[tuple[str, bytes]] | None = None,
) -> tuple[int, str]:
    files = [("photos", (name, data, "image/jpeg")) for name, data in (photos or [])]
    response = client.post(
        f"/yhtiot/{ids['company_a']}/asiat",
        data={
            "case_type": "damage",
            "title": "Astianpesukone vuotaa",
            "event_date": "2026-10-01",
            "location_text": "keittiö",
            "ongoing": "no",
        },
        files=files or None,
        headers=as_user(ids[user]),
        follow_redirects=False,
    )
    location = response.headers.get("location", "")
    case_id = location.split("/asiat/")[-1].split("?")[0] if location else ""
    return response.status_code, case_id


def _case(client: TestClient, ids: Ids, case_id: str, user: str) -> dict[str, object]:
    response = client.get(
        f"/api/v1/companies/{ids['company_a']}/cases/{case_id}", headers=as_user(ids[user])
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


# --- Lomakkeet ---


def test_damage_and_tender_forms_differ(client: TestClient, seeded: Ids) -> None:
    base = f"/yhtiot/{seeded['company_a']}/asiat/uusi?tyyppi="
    damage = client.get(base + "damage", headers=as_user(seeded["shareholder_a"])).text
    assert 'name="photos"' in damage and 'name="ongoing"' in damage
    assert 'name="scope"' not in damage
    tender = client.get(base + "tender_request", headers=as_user(seeded["manager"])).text
    assert 'name="scope"' in tender and 'name="offers_due"' in tender
    assert 'name="photos"' not in tender


def test_damage_details_are_saved(client: TestClient, seeded: Ids) -> None:
    code, case_id = _damage(client, seeded)
    assert code == 303
    case = _case(client, seeded, case_id, "shareholder_a")
    assert case["details"] == {"location_text": "keittiö", "ongoing": "no"}


def test_shareholder_cannot_create_tender(client: TestClient, seeded: Ids) -> None:
    headers = as_user(seeded["shareholder_a"])
    dashboard = client.get(f"/yhtiot/{seeded['company_a']}", headers=headers).text
    assert "Laadi tarjouspyyntö" not in dashboard
    form = client.get(
        f"/yhtiot/{seeded['company_a']}/asiat/uusi?tyyppi=tender_request", headers=headers
    )
    assert form.status_code == 403
    api = client.post(
        f"/api/v1/companies/{seeded['company_a']}/cases",
        json={
            "case_type": "tender_request",
            "title": "X",
            "details": {"target": "X", "scope": "Y"},
        },
        headers=headers,
    )
    assert api.status_code == 403


def test_rls_denies_tender_insert_by_shareholder(seeded: Ids) -> None:
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
                    "INSERT INTO cases (housing_company_id, case_type, title, status, created_by)"
                    " VALUES (:c, 'tender_request', 'x', 'draft', :u)"
                ),
                {"u": str(seeded["shareholder_a"]), "c": str(seeded["company_a"])},
            )
    finally:
        engine.dispose()


def test_invalid_tender_details_rejected(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        f"/api/v1/companies/{seeded['company_a']}/cases",
        json={
            "case_type": "tender_request",
            "title": "Maalaus",
            "details": {"target": "Maalaus", "scope": "x", "unknown_field": 1},
        },
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 422


# --- Lisätietopyynnöt ---


def _submit(client: TestClient, ids: Ids, case_id: str) -> None:
    response = client.post(
        f"/api/v1/companies/{ids['company_a']}/cases/{case_id}/transitions",
        json={"action": "submit", "expected_version": 1},
        headers=as_user(ids["shareholder_a"]),
    )
    assert response.status_code == 200


def test_info_request_requires_question(client: TestClient, seeded: Ids) -> None:
    _, case_id = _damage(client, seeded)
    _submit(client, seeded, case_id)
    response = client.post(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}/lisatietopyynto",
        data={"question": "  ", "expected_version": "2"},
        headers=as_user(seeded["manager"]),
    )
    assert response.status_code == 422
    assert _case(client, seeded, case_id, "manager")["status"] == "in_review"


def test_reporter_sees_question_and_answers(client: TestClient, seeded: Ids) -> None:
    _, case_id = _damage(client, seeded)
    _submit(client, seeded, case_id)
    question = "Lisää kuva kaapin alta ja kerro, milloin vuoto alkoi."
    asked = client.post(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}/lisatietopyynto",
        data={"question": question, "expected_version": "2"},
        headers=as_user(seeded["manager"]),
        follow_redirects=False,
    )
    assert asked.status_code == 303
    page = client.get(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Isa Isännöitsijä pyytää lisätietoja" in page
    assert question in page
    dashboard = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Sinulta pyydetään lisätietoja" in dashboard

    answered = client.post(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}/vastaus",
        data={"answer": "Vuoto alkoi maanantaina.", "expected_version": "3"},
        files=[("photos", ("kaappi.jpg", jpeg_with_gps(), "image/jpeg"))],
        headers=as_user(seeded["shareholder_a"]),
        follow_redirects=False,
    )
    assert answered.status_code == 303
    case = _case(client, seeded, case_id, "manager")
    assert case["status"] == "in_review"
    manager_page = client.get(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}", headers=as_user(seeded["manager"])
    ).text
    assert "Vuoto alkoi maanantaina." in manager_page
    assert 'alt="Kuva 1: kaappi.jpg"' in manager_page


def test_empty_answer_is_rejected(client: TestClient, seeded: Ids) -> None:
    _, case_id = _damage(client, seeded)
    _submit(client, seeded, case_id)
    client.post(
        f"/api/v1/companies/{seeded['company_a']}/cases/{case_id}/transitions",
        json={"action": "request_info", "expected_version": 2, "message": "Milloin?"},
        headers=as_user(seeded["manager"]),
    )
    response = client.post(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}/vastaus",
        data={"answer": "", "expected_version": "3"},
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 422
    assert "Kirjoita vastaus" in response.text


def test_other_resident_cannot_see_dialogue(client: TestClient, seeded: Ids) -> None:
    _, case_id = _damage(client, seeded)
    response = client.get(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}", headers=as_user(seeded["resident_a2"])
    )
    assert response.status_code == 404


def test_stale_version_on_info_request(client: TestClient, seeded: Ids) -> None:
    _, case_id = _damage(client, seeded)
    _submit(client, seeded, case_id)
    response = client.post(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}/lisatietopyynto",
        data={"question": "Milloin?", "expected_version": "1"},
        headers=as_user(seeded["manager"]),
        follow_redirects=False,
    )
    assert "virhe=versio" in response.headers["location"]


# --- Valokuvat ---


def test_photo_metadata_is_stripped_and_orientation_applied() -> None:
    result = process_image(jpeg_with_gps(400, 200, orientation=6))
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == "JPEG"
        assert not image.getexif()
        assert (image.width, image.height) == (200, 400)  # käännetty


def test_damage_with_photos_and_download(client: TestClient, seeded: Ids) -> None:
    code, case_id = _damage(
        client, seeded, photos=[("a.jpg", jpeg_with_gps()), ("b.jpg", jpeg_with_gps())]
    )
    assert code == 303
    page = client.get(
        f"/yhtiot/{seeded['company_a']}/asiat/{case_id}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert page.count("<img ") == 2
    src = page.split('<img src="')[1].split('"')[0]
    image = client.get(src, headers=as_user(seeded["shareholder_a"]))
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert not decoded.getexif()
    other = client.get(src, headers=as_user(seeded["resident_a2"]))
    assert other.status_code == 404


def test_non_image_is_rejected_and_no_case_created(client: TestClient, seeded: Ids) -> None:
    before = len(
        client.get(
            f"/api/v1/companies/{seeded['company_a']}/cases",
            headers=as_user(seeded["shareholder_a"]),
        ).json()
    )
    code, _ = _damage(client, seeded, photos=[("virus.jpg", b"MZ\x90\x00not an image")])
    assert code == 422
    after = len(
        client.get(
            f"/api/v1/companies/{seeded['company_a']}/cases",
            headers=as_user(seeded["shareholder_a"]),
        ).json()
    )
    assert after == before


def test_too_many_photos_rejected(client: TestClient, seeded: Ids) -> None:
    photo = jpeg_with_gps(50, 50)
    code, _ = _damage(client, seeded, photos=[(f"{i}.jpg", photo) for i in range(11)])
    assert code == 422


def test_too_large_photo_rejected() -> None:
    from taloapuri.services.attachments import InvalidImage

    with pytest.raises(InvalidImage, match="liian suuri"):
        process_image(b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024))


def test_photos_never_in_apartment_history(client: TestClient, seeded: Ids) -> None:
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/huoneistohistoria", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "<img" not in html
