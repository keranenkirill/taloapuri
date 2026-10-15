"""Tarjouspyynnöt: tapahtumat hallitukselle, tekoälyluonnos, tarjoukset ja vertailu.

FakeProvider: oikeaa tekoälyä ei kutsuta. Vaativat PostgreSQL:n.
"""

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taloapuri.ai.prompts import OFFER_COMPARE_PROMPT
from taloapuri.ai.provider import AiCitation, AiDocument, AiResult, AiSegment, FakeProvider
from taloapuri.main import create_app
from taloapuri.web.chat_routes import get_ai_provider
from tests.conftest import as_user

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sample_pdf import make_text_pdf  # noqa: E402

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]

OFFER_A = make_text_pdf(
    [["Maalaus Oy - Tarjous", "Kokonaishinta 18 400 euroa (alv 0 %).", "Takuu 2 vuotta."]]
)
OFFER_B = make_text_pdf(
    [["Pensseli Ky - Tarjous", "Kokonaishinta 16 900 euroa.", "Telineet eivät sisälly hintaan."]]
)


class OfferCitingProvider(FakeProvider):
    """Viittaa ensimmäiseen tarjousdokumenttiin."""

    def answer(  # type: ignore[override]
        self, system: str, documents: list[AiDocument], question: str, max_tokens: int | None = None
    ) -> AiResult:
        self.calls.append((system, documents, question))
        index = next(i for i, d in enumerate(documents) if d.title.startswith("Urakkatarjous"))
        return AiResult(
            segments=[
                AiSegment("Hinta: Maalaus Oy"),
                AiSegment(
                    " 18 400 euroa.", [AiCitation(index, 0, 1, "Kokonaishinta 18 400 euroa")]
                ),
                AiSegment(" Päätöksen tekee hallitus."),
            ],
            stop_reason="end_turn",
            model="fake",
        )


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def ai_client(fake: FakeProvider) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: fake
    yield TestClient(app)


def _create_tender(client: TestClient, ids: Ids, company: str = "company_a") -> str:
    response = client.post(
        f"/yhtiot/{ids[company]}/asiat",
        data={
            "case_type": "tender_request",
            "title": "Porrashuoneiden maalaus",
            "scope": "A- ja B-portaiden seinät ja katot, noin 600 m2.",
            "offers_due": "2026-12-01",
            "budget_note": "SALAINEN BUDJETTI 20000",
        },
        headers=as_user(ids["manager"]),
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0]


def _upload(
    client: TestClient, ids: Ids, url: str, name: str, pdf: bytes, user: str = "manager"
) -> int:
    return client.post(
        f"{url}/tarjoukset",
        data={"contractor_name": name, "total_price": "18 400,00"},
        files={"file": (f"{name}.pdf", pdf, "application/pdf")},
        headers=as_user(ids[user]),
        follow_redirects=False,
    ).status_code


def test_new_tender_is_event_for_board_not_residents(client: TestClient, seeded: Ids) -> None:
    _create_tender(client, seeded, company="company_b")
    board = client.get(f"/yhtiot/{seeded['company_b']}", headers=as_user(seeded["board_b"])).text
    assert "Uusi tarjouspyyntö:" in board and "Porrashuoneiden maalaus" in board
    _create_tender(client, seeded)
    resident = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Porrashuoneiden maalaus" not in resident


def test_ai_draft_excludes_budget_and_is_saved_only_by_human(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids
) -> None:
    url = _create_tender(ai_client, seeded)
    response = ai_client.post(
        f"{url}/luonnos/tekoaly", headers=as_user(seeded["manager"]), follow_redirects=False
    )
    assert response.status_code == 303
    assert "luonnos=tekoaly" in response.headers["location"]
    sent = " ".join(" ".join(d.blocks) for d in fake.calls[0][1])
    assert "SALAINEN BUDJETTI" not in sent
    assert "Isa" not in sent
    assert "Porrashuoneiden maalaus" in sent
    page = ai_client.get(f"{url}?luonnos=tekoaly", headers=as_user(seeded["manager"])).text
    assert "Tekoälyn tuottama luonnos" in page
    # Ei tallennettu ennen kuin ihminen tallentaa.
    case_id = url.rsplit("/", 1)[-1]
    api = ai_client.get(
        f"/api/v1/companies/{seeded['company_a']}/cases/{case_id}",
        headers=as_user(seeded["manager"]),
    ).json()
    assert api["details"]["draft_text"] == ""
    saved = ai_client.post(
        f"{url}/luonnos",
        data={
            "draft_text": "TARJOUSPYYNTÖ – Porrashuoneiden maalaus",
            "expected_version": str(api["version"]),
        },
        headers=as_user(seeded["manager"]),
        follow_redirects=False,
    )
    assert saved.status_code == 303
    api = ai_client.get(
        f"/api/v1/companies/{seeded['company_a']}/cases/{case_id}",
        headers=as_user(seeded["manager"]),
    ).json()
    assert api["details"]["draft_text"].startswith("TARJOUSPYYNTÖ")


def test_comparison_needs_two_offers(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids
) -> None:
    url = _create_tender(ai_client, seeded)
    assert _upload(ai_client, seeded, url, "Maalaus Oy", OFFER_A) == 303
    response = ai_client.post(f"{url}/vertailu", headers=as_user(seeded["manager"]))
    assert response.status_code == 422
    assert "vähintään kaksi tarjousta" in response.text
    assert fake.calls == []


def test_comparison_cites_offer_pages(seeded: Ids) -> None:
    provider = OfferCitingProvider()
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    client = TestClient(app)
    url = _create_tender(client, seeded)
    _upload(client, seeded, url, "Maalaus Oy", OFFER_A)
    _upload(client, seeded, url, "Pensseli Ky", OFFER_B)
    response = client.post(
        f"{url}/vertailu", headers=as_user(seeded["manager"]), follow_redirects=False
    )
    assert response.status_code == 303
    system, documents, _ = provider.calls[0]
    assert system == OFFER_COMPARE_PROMPT
    assert "ÄLÄ suosittele" in system
    assert sum(d.title.startswith("Urakkatarjous") for d in documents) == 2
    page = client.get(url, headers=as_user(seeded["manager"])).text
    assert "Tarjous: Maalaus Oy, s. 1" in page
    assert "✓ lainaus tarkistettu" in page
    assert "Päätöksen tekee hallitus." in page


def test_scanned_offer_blocks_comparison(ai_client: TestClient, seeded: Ids) -> None:
    url = _create_tender(ai_client, seeded)
    _upload(ai_client, seeded, url, "Maalaus Oy", OFFER_A)
    _upload(ai_client, seeded, url, "Skannaus Oy", b"%PDF-1.4\n%%EOF\n")
    response = ai_client.post(f"{url}/vertailu", headers=as_user(seeded["manager"]))
    assert response.status_code == 422
    assert "Skannaus Oy" in response.text


def test_shareholder_cannot_see_or_upload_offers(ai_client: TestClient, seeded: Ids) -> None:
    url = _create_tender(ai_client, seeded)
    assert ai_client.get(url, headers=as_user(seeded["shareholder_a"])).status_code == 404
    assert _upload(ai_client, seeded, url, "X", OFFER_A, user="shareholder_a") in (403, 404)


def test_ai_off_gives_clear_message(seeded: Ids) -> None:
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: None
    client = TestClient(app)
    url = _create_tender(client, seeded)
    response = client.post(f"{url}/luonnos/tekoaly", headers=as_user(seeded["manager"]))
    assert response.status_code == 422
    assert "Tekoäly ei ole juuri nyt käytettävissä" in response.text


def test_monthly_budget_blocks_tender_ai(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    from taloapuri.config import get_settings

    url = _create_tender(ai_client, seeded)
    monkeypatch.setenv("TALOAPURI_AI_MONTHLY_BUDGET_USD", "0")
    get_settings.cache_clear()
    try:
        response = ai_client.post(f"{url}/luonnos/tekoaly", headers=as_user(seeded["manager"]))
    finally:
        monkeypatch.delenv("TALOAPURI_AI_MONTHLY_BUDGET_USD")
        get_settings.cache_clear()
    assert response.status_code == 422
    assert "kuukausikiintiö" in response.text
    assert fake.calls == []
