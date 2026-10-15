"""Tekoälyn striimaus (Server-Sent Events). FakeProvider: oikeaa tekoälyä ei kutsuta."""

import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taloapuri.ai.provider import AiUnavailable, FakeProvider
from taloapuri.main import create_app
from taloapuri.web.chat_routes import get_ai_provider
from tests.conftest import as_user

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sample_pdf import make_text_pdf  # noqa: E402

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]
QUESTION = "Kuka vastaa kylpyhuoneen kunnossapitovastuusta?"


def parse_sse(body: str) -> list[tuple[str, dict[str, str]]]:
    events = []
    for chunk in body.strip().split("\n\n"):
        name = next(line[6:].strip() for line in chunk.splitlines() if line.startswith("event:"))
        data = next(line[5:].strip() for line in chunk.splitlines() if line.startswith("data:"))
        events.append((name, json.loads(data)))
    return events


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def ai_client(fake: FakeProvider) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: fake
    yield TestClient(app)


def test_chat_stream_sends_status_deltas_and_done(
    ai_client: TestClient, seeded: Ids, ingested: None
) -> None:
    response = ai_client.post(
        f"/yhtiot/{seeded['company_a']}/kysy/stream",
        data={"question": QUESTION},
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in response.headers["cache-control"]
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "status"
    assert "delta" in names
    assert names[-1] == "done"
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    assert "vastuu jakautuu lain mukaan" in streamed
    # Valmis vastaus on tallennettu ja lähdeviitteet tarkistettu, kun done saapuu.
    redirect = events[-1][1]["redirect"]
    page = ai_client.get(redirect.split("#")[0], headers=as_user(seeded["shareholder_a"])).text
    assert "Tekoälyn tuottama" in page
    assert "✓ lainaus tarkistettu" in page


def test_chat_stream_empty_question_gives_error_event(ai_client: TestClient, seeded: Ids) -> None:
    response = ai_client.post(
        f"/yhtiot/{seeded['company_a']}/kysy/stream",
        data={"question": " "},
        headers=as_user(seeded["shareholder_a"]),
    )
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert "Kirjoita kysymys" in events[-1][1]["message"]


def test_chat_stream_provider_failure_is_reported_as_unavailable(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids, ingested: None
) -> None:
    fake.error = AiUnavailable("timeout")
    response = ai_client.post(
        f"/yhtiot/{seeded['company_a']}/kysy/stream",
        data={"question": QUESTION},
        headers=as_user(seeded["shareholder_a"]),
    )
    events = parse_sse(response.text)
    assert events[-1][0] == "done"  # vastaus "ei käytettävissä" tallennettu
    page = ai_client.get(
        events[-1][1]["redirect"].split("#")[0], headers=as_user(seeded["shareholder_a"])
    ).text
    assert "ei ole juuri nyt käytettävissä" in page


def test_chat_stream_requires_login(ai_client: TestClient, seeded: Ids) -> None:
    response = ai_client.post(
        f"/yhtiot/{seeded['company_a']}/kysy/stream",
        data={"question": QUESTION},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _tender(client: TestClient, ids: Ids) -> str:
    response = client.post(
        f"/yhtiot/{ids['company_a']}/asiat",
        data={
            "case_type": "tender_request",
            "title": "Porrashuoneiden maalaus",
            "scope": "Seinät.",
        },
        headers=as_user(ids["manager"]),
        follow_redirects=False,
    )
    return response.headers["location"].split("?")[0]


def test_tender_draft_stream(ai_client: TestClient, seeded: Ids) -> None:
    url = _tender(ai_client, seeded)
    response = ai_client.post(f"{url}/luonnos/tekoaly/stream", headers=as_user(seeded["manager"]))
    events = parse_sse(response.text)
    assert events[-1][0] == "done"
    assert events[-1][1]["redirect"].endswith("?luonnos=tekoaly#luonnos")
    assert any(name == "delta" for name, _ in events)


def test_tender_stream_forbidden_for_shareholder(ai_client: TestClient, seeded: Ids) -> None:
    url = _tender(ai_client, seeded)
    response = ai_client.post(
        f"{url}/luonnos/tekoaly/stream", headers=as_user(seeded["shareholder_a"])
    )
    assert response.status_code in (403, 404)


def test_compare_stream_reports_missing_offers_as_error(ai_client: TestClient, seeded: Ids) -> None:
    url = _tender(ai_client, seeded)
    response = ai_client.post(f"{url}/vertailu/stream", headers=as_user(seeded["manager"]))
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert "vähintään kaksi tarjousta" in events[-1][1]["message"]


def test_compare_stream_with_offers(ai_client: TestClient, seeded: Ids) -> None:
    url = _tender(ai_client, seeded)
    for name in ("Maalaus Oy", "Pensseli Ky"):
        ai_client.post(
            f"{url}/tarjoukset",
            data={"contractor_name": name},
            files={
                "file": (
                    f"{name}.pdf",
                    make_text_pdf([[f"{name} tarjous 10 000 e"]]),
                    "application/pdf",
                )
            },
            headers=as_user(seeded["manager"]),
        )
    response = ai_client.post(f"{url}/vertailu/stream", headers=as_user(seeded["manager"]))
    events = parse_sse(response.text)
    assert [n for n, _ in events if n == "status"]
    assert events[-1][0] == "done"
    page = ai_client.get(url, headers=as_user(seeded["manager"])).text
    assert "Tarjousten vertailu" in page and "Tekoälyn tuottama" in page


def test_pages_include_stream_hooks_and_script(ai_client: TestClient, seeded: Ids) -> None:
    html = ai_client.get(
        f"/yhtiot/{seeded['company_a']}/kysy", headers=as_user(seeded["shareholder_a"])
    ).text
    assert 'src="/static/ai-stream.js"' in html
    assert 'data-ai-stream="/yhtiot/' in html
    assert 'class="ai-progress"' in html
    js = ai_client.get("/static/ai-stream.js")
    assert js.status_code == 200
