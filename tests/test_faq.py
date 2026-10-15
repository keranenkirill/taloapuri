"""Usein kysytyt kysymykset: yleinen UKK lakilainauksineen ja taloyhtiön omat kysymykset.

Vaatii PostgreSQL:n (paitsi sisältöä koskevat yksikkötestit).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from taloapuri.web.faq_content import FAQ_ENTRIES, GROUP_ORDER, front_page_entries
from tests.conftest import (
    TEST_DATABASE_URL,
    TEST_MIGRATION_DATABASE_URL,
    as_user,
    reset_laws,
)

Ids = dict[str, uuid.UUID]


def _owner(sql: str, **params: object) -> list[tuple[object, ...]]:
    assert TEST_MIGRATION_DATABASE_URL
    engine = create_engine(TEST_MIGRATION_DATABASE_URL)
    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        rows = [tuple(r) for r in result] if result.returns_rows else []
    engine.dispose()
    return rows


def _entry_html(html: str, question: str) -> str:
    """Yhden UKK-kysymyksen <details>-lohko."""
    for block in html.split('<details class="faq-item"')[1:]:
        if question in block.split("</summary>")[0]:
            return block.split("</details>")[0]
    raise AssertionError(f"kysymystä ei löytynyt: {question}")


def _questions_in_order(html: str) -> list[str]:
    return [
        b.split("<summary>")[1].split("</summary>")[0]
        for b in html.split('<details class="faq-item"')[1:]
    ]


# --- Sisältö (ei tietokantaa) ---


def test_faq_content_is_consistent() -> None:
    ids = [e.id for e in FAQ_ENTRIES]
    assert len(ids) == len(set(ids))
    assert {e.group for e in FAQ_ENTRIES} <= set(GROUP_ORDER)
    # Etusivu on kirjautumaton ja tietokannaton: siellä ei saa olla lakiväitteitä.
    assert front_page_entries()
    assert all(not e.refs for e in front_page_entries())
    # Jokaisella lakiviitteellä on tarkka momenttirajaus (lainaus tukee vain väitettä).
    assert all(r.subsections for e in FAQ_ENTRIES for r in e.refs)


# --- Etusivu ja ensiohjeet ---


def test_front_page_has_faq_instead_of_water_banner(client: TestClient) -> None:
    html = client.get("/").text
    assert "Usein kysytyt kysymykset" in html
    assert "Onko vesi parhaillaan vuotamassa" not in html
    assert "Katso vesivahingon ensiohjeet" not in html
    # Vesivuodon ensiohjeet näkyvät heti ilman klikkausta (ensimmäinen kysymys on auki).
    assert '<details class="faq-item" open>' in html
    block = _entry_html(html, "Vesi vuotaa juuri nyt")
    assert "Pysäytä vesi" in block and "112" in block and "Luonnos" in block
    assert "Lain sanamuoto" not in html
    assert 'href="/ukk"' in html


def test_first_aid_page_uses_the_same_steps(client: TestClient) -> None:
    page = client.get("/ensiohjeet/vesivahinko").text
    faq = client.get("/").text
    for step in (
        "Pysäytä vesi.",
        "Varo sähköä.",
        "Ilmoita heti.",
        "Kuvaa vahinko.",
        "Kuivaa näkyvä vesi",
    ):
        assert step in page and step in faq


# --- Yleinen UKK ---


@pytest.mark.db
def test_public_faq_without_login_has_no_law_quotes(client: TestClient) -> None:
    html = client.get("/ukk").text
    assert "Kuka vastaa korjauksesta" in html
    assert "Lain sanamuoto" not in html
    assert "Kirjaudu sisään nähdäksesi" in html


@pytest.mark.db
def test_logged_in_faq_shows_live_law_quote_with_source(
    client: TestClient, seeded: Ids, ingested: None
) -> None:
    html = client.get("/ukk", headers=as_user(seeded["shareholder_a"])).text
    block = _entry_html(html, "Kuka vastaa korjauksesta")
    assert "Lain sanamuoto: AOYL 4 luku 2 §" in block
    assert "rakenteet, eristeet ja ikkunat" in block
    assert "Osakkeenomistajan on pidettävä kunnossa osakehuoneistonsa sisäosat" in block
    assert "ajantasaistettu 16.6.2026" in block
    assert 'href="https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2009/1599"' in block
    assert "ei vahvistettu lähteestä" not in block
    assert "Laki on päivittynyt" not in block


@pytest.mark.db
def test_missing_source_is_marked_unverified(
    client: TestClient, seeded: Ids, ingested: None
) -> None:
    # Testikannassa on vain AOYL:n 4 luvun näyte, joten 5 ja 24 luvun lainauksia ei löydy.
    html = client.get("/ukk", headers=as_user(seeded["shareholder_a"])).text
    for question in ("Tarvitsenko ilmoittaa remontista?", "Kuka maksaa vahingon"):
        block = _entry_html(html, question)
        assert "ei vahvistettu lähteestä" in block
        assert "Lain sanamuoto" not in block


@pytest.mark.db
def test_inactive_law_makes_answers_unverified(
    client: TestClient, seeded: Ids, ingested: None
) -> None:
    _owner("UPDATE sources SET active = false WHERE is_core")
    try:
        html = client.get("/ukk", headers=as_user(seeded["shareholder_a"])).text
        assert "ei vahvistettu lähteestä" in _entry_html(html, "Kuka vastaa korjauksesta")
    finally:
        reset_laws()


@pytest.mark.db
def test_updated_law_triggers_staleness_warning(
    client: TestClient, seeded: Ids, ingested: None
) -> None:
    _owner(
        "UPDATE source_versions SET version_label = '20990101'"
        " WHERE id = (SELECT current_version_id FROM sources WHERE is_core)"
    )
    try:
        html = client.get("/ukk", headers=as_user(seeded["shareholder_a"])).text
        block = _entry_html(html, "Kuka vastaa korjauksesta")
        assert "Laki on päivittynyt" in block
        assert "Lain sanamuoto" in block  # sanamuoto näytetään silti
    finally:
        _owner(
            "UPDATE source_versions SET version_label = '20260535'"
            " WHERE id = (SELECT current_version_id FROM sources WHERE is_core)"
        )


# --- Taloyhtiön omat kysymykset ---


@pytest.mark.db
def test_company_faq_visible_to_members_only(client: TestClient, seeded: Ids) -> None:
    resident = client.get(
        f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "Taloyhtiön omat kysymykset" in resident
    assert "Milloin sauna on varattavissa?" in resident
    assert "Muokkaa taloyhtiön kysymyksiä" not in resident
    manager = client.get(
        f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["manager"])
    ).text
    assert "Muokkaa taloyhtiön kysymyksiä" in manager
    # Toisen yhtiön jäsen ei pääse sisään eikä toisen yhtiön sivulla näy A:n kysymyksiä.
    assert (
        client.get(
            f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["board_b"])
        ).status_code
        == 404
    )
    other = client.get(
        f"/yhtiot/{seeded['company_b']}/ukk", headers=as_user(seeded["manager"])
    ).text
    assert "sauna" not in other.lower()


@pytest.mark.db
def test_manager_adds_question_resident_sees_it(client: TestClient, seeded: Ids) -> None:
    response = client.post(
        f"/yhtiot/{seeded['company_a']}/ukk",
        data={
            "question": "Missä pyykkitupa on?",
            "answer": "Kellarikerroksessa.\nAvain naulakossa.",
            "sort_order": "",
        },
        headers=as_user(seeded["manager"]),
        follow_redirects=False,
    )
    assert response.status_code == 303
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["shareholder_a"])
    ).text
    block = _entry_html(html, "Missä pyykkitupa on?")
    assert "Kellarikerroksessa." in block and "Avain naulakossa." in block
    assert _owner("SELECT count(*) FROM audit_events WHERE action = 'faq.added'")[0][0] >= 1


@pytest.mark.db
def test_invalid_faq_input_is_rejected(client: TestClient, seeded: Ids) -> None:
    url = f"/yhtiot/{seeded['company_a']}/ukk"
    manager = as_user(seeded["manager"])
    empty = client.post(url, data={"question": " ", "answer": ""}, headers=manager)
    assert empty.status_code == 422
    assert "Kirjoita kysymys" in empty.text and "Kirjoita vastaus" in empty.text
    long_q = client.post(url, data={"question": "x" * 201, "answer": "a"}, headers=manager)
    assert long_q.status_code == 422 and "liian pitkä" in long_q.text
    bad_order = client.post(
        url, data={"question": "k", "answer": "a", "sort_order": "abc"}, headers=manager
    )
    assert bad_order.status_code == 422 and "järjestysnumero" in bad_order.text


@pytest.mark.db
def test_faq_text_is_escaped(client: TestClient, seeded: Ids) -> None:
    client.post(
        f"/yhtiot/{seeded['company_a']}/ukk",
        data={"question": "<b>Lihava</b> kysymys?", "answer": "<script>alert(1)</script>"},
        headers=as_user(seeded["manager"]),
    )
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["shareholder_a"])
    ).text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>Lihava</b>" not in html


@pytest.mark.db
def test_sort_order_controls_display_order(client: TestClient, seeded: Ids) -> None:
    for question, order in (("Viimeisenä", "90"), ("Ensimmäisenä", "1")):
        client.post(
            f"/yhtiot/{seeded['company_a']}/ukk",
            data={"question": question, "answer": "a", "sort_order": order},
            headers=as_user(seeded["manager"]),
        )
    html = client.get(
        f"/yhtiot/{seeded['company_a']}/ukk", headers=as_user(seeded["shareholder_a"])
    ).text
    own = html.split('id="oma-ukk"')[1]
    order = list(
        _questions_in_order(
            '<details class="faq-item"' + own.split('<details class="faq-item"', 1)[1]
        )
    )
    assert (
        order.index("Ensimmäisenä")
        < order.index("Milloin sauna on varattavissa?")
        < order.index("Viimeisenä")
    )


def _faq_id(question: str) -> uuid.UUID:
    return uuid.UUID(
        str(_owner("SELECT id FROM company_faq WHERE question = :q", q=question)[0][0])
    )


@pytest.mark.db
def test_manager_can_edit_and_delete(client: TestClient, seeded: Ids) -> None:
    entry = _faq_id("Mihin laitan isot jätteet?")
    base = f"/yhtiot/{seeded['company_a']}/ukk/{entry}"
    manager = as_user(seeded["manager"])
    ok = client.post(
        base,
        data={"question": "Mihin isot jätteet?", "answer": "Jätekatokseen.", "sort_order": "5"},
        headers=manager,
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert _owner("SELECT question, sort_order FROM company_faq WHERE id = :i", i=entry) == [
        ("Mihin isot jätteet?", 5)
    ]
    bad = client.post(base, data={"question": "", "answer": "x"}, headers=manager)
    assert bad.status_code == 422 and "Kirjoita kysymys" in bad.text
    confirm = client.get(f"{base}/poista", headers=manager)
    assert confirm.status_code == 200 and "Poistetaanko tämä kysymys?" in confirm.text
    assert client.post(f"{base}/poista", headers=manager, follow_redirects=False).status_code == 303
    assert _owner("SELECT count(*) FROM company_faq WHERE id = :i", i=entry)[0][0] == 0


@pytest.mark.db
def test_resident_cannot_edit(client: TestClient, seeded: Ids) -> None:
    entry = _faq_id("Milloin sauna on varattavissa?")
    base = f"/yhtiot/{seeded['company_a']}/ukk"
    resident = as_user(seeded["shareholder_a"])
    assert client.get(f"{base}/muokkaa", headers=resident).status_code == 403
    assert (
        client.post(base, data={"question": "k", "answer": "a"}, headers=resident).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/{entry}", data={"question": "k", "answer": "a"}, headers=resident
        ).status_code
        == 403
    )
    assert client.post(f"{base}/{entry}/poista", headers=resident).status_code == 403
    assert _owner("SELECT count(*) FROM company_faq WHERE id = :i", i=entry)[0][0] == 1


@pytest.mark.db
def test_manager_cannot_touch_other_companys_entry(client: TestClient, seeded: Ids) -> None:
    entry = _faq_id("Milloin sauna on varattavissa?")  # yhtiön A kysymys
    manager = as_user(seeded["manager"])  # isännöi sekä A:ta että B:tä
    wrong = f"/yhtiot/{seeded['company_b']}/ukk/{entry}"
    assert client.post(f"{wrong}/poista", headers=manager).status_code == 404
    assert (
        client.post(wrong, data={"question": "k", "answer": "a"}, headers=manager).status_code
        == 404
    )
    assert _owner("SELECT count(*) FROM company_faq WHERE id = :i", i=entry)[0][0] == 1


@pytest.mark.db
def test_rls_denies_direct_insert_by_resident(seeded: Ids) -> None:
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
                    "INSERT INTO company_faq (housing_company_id, question, answer, created_by)"
                    " VALUES (:c, 'k', 'a', :u)"
                ),
                {"c": str(seeded["company_a"]), "u": str(seeded["shareholder_a"])},
            )
    finally:
        engine.dispose()


@pytest.mark.db
def test_dashboard_links_to_faq(client: TestClient, seeded: Ids) -> None:
    html = client.get(
        f"/yhtiot/{seeded['company_a']}", headers=as_user(seeded["shareholder_a"])
    ).text
    assert f'href="/yhtiot/{seeded["company_a"]}/ukk"' in html
    assert "Usein kysytyt kysymykset" in html
