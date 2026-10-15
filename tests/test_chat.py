"""Tekoälychat (vaihe 5). Käyttää FakeProvideria: ei maksullisia API-kutsuja."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from taloapuri.ai.prompts import SYSTEM_PROMPT
from taloapuri.ai.provider import AiCitation, AiResult, AiSegment, AiUnavailable, FakeProvider
from taloapuri.auth import CompanyContext
from taloapuri.config import Settings
from taloapuri.db import set_company_context, set_user_context
from taloapuri.domain.roles import Role
from taloapuri.main import create_app
from taloapuri.services import chat
from taloapuri.web.chat_routes import get_ai_provider
from tests.conftest import TEST_DATABASE_URL, as_user

pytestmark = pytest.mark.db

Ids = dict[str, uuid.UUID]
QUESTION = "Kuka vastaa kylpyhuoneen kunnossapitovastuusta?"


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def ai_client(fake: FakeProvider) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: fake
    yield TestClient(app)


def _ask(
    client: TestClient, ids: Ids, user: str = "shareholder_a", question: str = QUESTION
) -> str:
    response = client.post(
        f"/yhtiot/{ids['company_a']}/kysy",
        data={"question": question},
        headers=as_user(ids[user]),
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    location: str = response.headers["location"]
    return location.split("#")[0]


@pytest.fixture
def session(seeded: Ids) -> Iterator[tuple[Session, CompanyContext]]:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    db = Session(engine)
    db.begin()
    set_user_context(db, seeded["shareholder_a"])
    set_company_context(db, seeded["company_a"])
    ctx = CompanyContext(
        company_id=seeded["company_a"],
        company_name="As Oy Esimerkkikoivu",
        user_id=seeded["shareholder_a"],
        roles=frozenset({Role.SHAREHOLDER}),
    )
    yield db, ctx
    db.rollback()
    db.close()
    engine.dispose()


def _statuses(db: Session) -> list[str]:
    return [r[0] for r in db.execute(text("SELECT status FROM chat_messages ORDER BY role DESC"))]


def test_answer_shows_ai_label_and_verified_citation(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids, ingested: None
) -> None:
    thread_url = _ask(ai_client, seeded)
    html = ai_client.get(thread_url, headers=as_user(seeded["shareholder_a"])).text
    assert "Tekoälyn tuottama" in html
    assert "Mihin tämä perustuu?" in html
    assert "AOYL 4 luku" in html
    assert "✓ lainaus tarkistettu" in html
    assert len(fake.calls) == 1


def test_provider_receives_only_law_text_and_wrapped_question(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids, ingested: None
) -> None:
    _ask(ai_client, seeded)
    system, documents, question = fake.calls[0]
    assert system == SYSTEM_PROMPT
    assert "eivät ohjeita" in system
    assert all(d.title.startswith("AOYL ") for d in documents)
    assert "<kysymys>" in question and QUESTION in question
    # Yhtiön asioita tai henkilöiden nimiä ei lähetetä.
    sent = " ".join(" ".join(d.blocks) + d.context for d in documents) + question
    assert "Olli" not in sent and "Esimerkkikoivu" not in sent


def test_fabricated_quote_is_marked_unverified(
    ai_client: TestClient, fake: FakeProvider, seeded: Ids, ingested: None
) -> None:
    fake.result = AiResult(
        segments=[AiSegment("Väite", [AiCitation(0, 0, 1, "Tätä lausetta ei ole laissa.")])],
        stop_reason="end_turn",
        model="fake",
    )
    html = ai_client.get(_ask(ai_client, seeded), headers=as_user(seeded["shareholder_a"])).text
    assert "lainausta ei voitu vahvistaa" in html


def test_out_of_range_document_index_is_unverified(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    fake.result = AiResult(
        segments=[AiSegment("Väite", [AiCitation(99, 0, 1, "x")])],
        stop_reason="end_turn",
        model="f",
    )
    thread = chat.ask(db, ctx, Settings(), fake, QUESTION)
    views = chat.thread_messages(db, ctx, thread)
    assert views[-1].citations[0].verified is False
    assert views[-1].citations[0].label == "Tuntematon lähde"


def test_ai_disabled_shows_fallback_without_calling(seeded: Ids, ingested: None) -> None:
    app = create_app()
    app.dependency_overrides[get_ai_provider] = lambda: None
    client = TestClient(app)
    html = client.get(_ask(client, seeded), headers=as_user(seeded["shareholder_a"])).text
    assert "ei ole juuri nyt käytettävissä" in html
    assert "ohjatuilla toiminnoilla" in html


def test_no_sources_means_no_ai_call(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    chat.ask(db, ctx, Settings(), fake, "qwxz zyxw vvvv")
    assert fake.calls == []
    assert "no_sources" in _statuses(db)


def test_daily_limit_is_enforced(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    settings = Settings(ai_daily_messages_per_user=1)
    thread = chat.ask(db, ctx, settings, fake, QUESTION)
    chat.ask(db, ctx, settings, fake, QUESTION, thread)
    assert len(fake.calls) == 1
    assert "over_quota" in _statuses(db)


def test_monthly_budget_is_enforced(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    settings = Settings(ai_monthly_budget_usd=0.0)
    chat.ask(db, ctx, settings, fake, QUESTION)
    assert fake.calls == []
    assert "over_quota" in _statuses(db)


def test_cost_is_recorded(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    chat.ask(db, ctx, Settings(), fake, QUESTION)
    # FakeProvider: 1000 syöte- ja 200 tulostokenia → 0,0001 + 0,0001 USD
    assert float(chat.month_cost(db, ctx)) == pytest.approx(0.0002)


def test_unavailable_provider_is_handled(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    fake.error = AiUnavailable("timeout")
    chat.ask(db, ctx, Settings(), fake, QUESTION)
    assert "unavailable" in _statuses(db)
    error = db.execute(text("SELECT error FROM ai_runs")).scalar_one()
    assert error == "timeout"


def test_refusal_is_handled(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session
    fake.result = AiResult(segments=[], stop_reason="refusal", model="fake")
    chat.ask(db, ctx, Settings(), fake, QUESTION)
    assert "refused" in _statuses(db)


def test_other_user_cannot_read_thread(ai_client: TestClient, seeded: Ids, ingested: None) -> None:
    thread_url = _ask(ai_client, seeded, user="shareholder_a")
    # Isännöitsijäkään ei näe asukkaan kysymyksiä.
    response = ai_client.get(thread_url, headers=as_user(seeded["manager"]))
    assert response.status_code == 404
    listing = ai_client.get(
        f"/yhtiot/{seeded['company_a']}/kysy", headers=as_user(seeded["manager"])
    ).text
    assert QUESTION not in listing


def test_empty_question_shows_error(ai_client: TestClient, seeded: Ids) -> None:
    response = ai_client.post(
        f"/yhtiot/{seeded['company_a']}/kysy",
        data={"question": " "},
        headers=as_user(seeded["shareholder_a"]),
    )
    assert response.status_code == 422
    assert "Korjaa kysymys" in response.text


# --- Pöytäkirjat lähteinä (vaihe 5) ---


class MinutesCitingProvider(FakeProvider):
    """Viittaa ensimmäiseen pöytäkirjadokumenttiin (sivu 1) lainaamalla sen tekstiä."""

    def __init__(self, quote: str | None = None) -> None:
        super().__init__()
        self.quote = quote

    def answer(  # type: ignore[override]
        self,
        system: str,
        documents: list,
        question: str,
        max_tokens: int | None = None,  # type: ignore[type-arg]
    ) -> AiResult:
        self.calls.append((system, documents, question))
        index = next(
            i for i, d in enumerate(documents) if d.title.startswith("Taloyhtiön asiakirja")
        )
        quote = self.quote or documents[index].blocks[0][:80]
        return AiResult(
            segments=[
                AiSegment("Lyhyesti: hallitus päätti pyytää tarjoukset"),
                AiSegment(" maalauksesta.", [AiCitation(index, 0, 1, quote)]),
            ],
            stop_reason="end_turn",
            model="fake",
        )


MINUTES_QUESTION = "Mitä hallitus päätti porrashuoneiden maalauksesta?"


def test_minutes_are_cited_with_page_and_verified(
    session: tuple[Session, CompanyContext], ingested: None
) -> None:
    db, ctx = session
    provider = MinutesCitingProvider()
    thread = chat.ask(db, ctx, Settings(), provider, MINUTES_QUESTION)
    citation = chat.thread_messages(db, ctx, thread)[-1].citations[0]
    assert citation.kind == "minutes"
    assert citation.label == "Pöytäkirja: Hallituksen kokous 4/2026, s. 1"
    assert citation.verified is True
    assert citation.public_url and citation.public_url.endswith("/lataa")


def test_fabricated_minutes_quote_is_unverified(
    session: tuple[Session, CompanyContext], ingested: None
) -> None:
    db, ctx = session
    provider = MinutesCitingProvider(quote="Hallitus päätti purkaa talon.")
    thread = chat.ask(db, ctx, Settings(), provider, MINUTES_QUESTION)
    assert chat.thread_messages(db, ctx, thread)[-1].citations[0].verified is False


def test_hidden_minutes_never_sent_for_resident(
    session: tuple[Session, CompanyContext], fake: FakeProvider, ingested: None
) -> None:
    db, ctx = session  # osakas
    chat.ask(db, ctx, Settings(), fake, "Mitä maksurästeistä ja perinnästä on päätetty?")
    sent = " ".join(" ".join(d.blocks) for call in fake.calls for d in call[1])
    assert "maksurästit" not in sent


def test_board_sees_hidden_minutes_as_source(seeded: Ids, ingested: None) -> None:
    assert TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    db = Session(engine)
    db.begin()
    try:
        set_user_context(db, seeded["manager"])
        set_company_context(db, seeded["company_a"])
        ctx = CompanyContext(
            company_id=seeded["company_a"],
            company_name="As Oy Esimerkkikoivu",
            user_id=seeded["manager"],
            roles=frozenset({Role.PROPERTY_MANAGER}),
        )
        fake = FakeProvider()
        chat.ask(db, ctx, Settings(), fake, "Mitä maksurästeistä ja perinnästä on päätetty?")
        sent = " ".join(" ".join(d.blocks) for call in fake.calls for d in call[1])
        assert "maksurästit" in sent
    finally:
        db.rollback()
        db.close()
        engine.dispose()
