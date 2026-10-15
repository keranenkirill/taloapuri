"""Luo paikalliseen kehityskantaan kuvitteelliset testitiedot. EI todellisia henkilötietoja.

Käyttö (tietokanta käynnissä ja migraatiot ajettu):
    python scripts/seed_dev.py

Yhdistää taulut omistavalla roolilla (TALOAPURI_MIGRATION_DATABASE_URL), joka ohittaa RLS:n.
Tulostaa käyttäjien tunnisteet kehityskirjautumista varten.
"""

import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from sample_pdf import make_text_pdf
from sqlalchemy import Connection, create_engine, text

from taloapuri.sources.pdf_text import extract_pages

SEED_TABLES = (
    "direct_messages, message_participants, message_threads, "
    "case_attachment_files, case_attachments, case_messages, "
    "company_faq, company_document_pages, company_document_files, company_documents, "
    "tender_offer_pages, tender_offer_files, tender_offers, "
    "chat_citations, ai_runs, case_ai_outputs, chat_messages, chat_threads, "
    "audit_events, case_events, cases, apartment_occupancies, apartments, memberships, "
    "account_companies, users, housing_companies, accounts"
)


def seed(url: str) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4()
        for name in (
            "firm",
            "company_a",
            "company_b",
            "manager",
            "shareholder_a",
            "board_b",
            "former_board_a",
            "former_resident_a1",
            "resident_a2",
            "platform_admin",
            "apt_a1",
            "apt_a2",
            "old_case_a1",
        )
    }
    now = datetime.now(UTC)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {SEED_TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, account_type) VALUES (:id, :n, 'management_firm')"
            ),
            {"id": ids["firm"], "n": "Esimerkki-Isännöinti Oy"},
        )
        for key, name in (("company_a", "As Oy Esimerkkikoivu"), ("company_b", "As Oy Testimänty")):
            conn.execute(
                text("INSERT INTO housing_companies (id, name) VALUES (:id, :n)"),
                {"id": ids[key], "n": name},
            )
            conn.execute(
                text(
                    "INSERT INTO account_companies (account_id, housing_company_id, valid_from)"
                    " VALUES (:a, :c, :f)"
                ),
                {"a": ids["firm"], "c": ids[key], "f": now - timedelta(days=365)},
            )
        users = {
            "manager": ("Isa Isännöitsijä", "isa@esimerkki.fi"),
            "shareholder_a": ("Olli Osakas", "olli@esimerkki.fi"),
            "board_b": ("Hanna Hallitus", "hanna@esimerkki.fi"),
            "former_board_a": ("Entinen Jäsen", "entinen@esimerkki.fi"),
            "former_resident_a1": ("Maija Muuttanut", "maija@esimerkki.fi"),
            "resident_a2": ("Ville Vuokralainen", "ville@esimerkki.fi"),
        }
        for key, (name, email) in users.items():
            conn.execute(
                text("INSERT INTO users (id, display_name, email) VALUES (:id, :n, :e)"),
                {"id": ids[key], "n": name, "e": email},
            )
        # Palvelun ylläpitäjä: ei jäsenyyksiä eikä pääsyä yhtiöiden tietoihin; hallitsee lakeja.
        conn.execute(
            text(
                "INSERT INTO users (id, display_name, email, is_platform_admin)"
                " VALUES (:id, 'Palvelun ylläpitäjä', 'yllapito@esimerkki.fi', true)"
            ),
            {"id": ids["platform_admin"]},
        )
        memberships = (
            ("manager", "company_a", "property_manager", None),
            ("manager", "company_b", "property_manager", None),
            ("shareholder_a", "company_a", "shareholder", None),
            ("board_b", "company_b", "board_member", None),
            # Kausi päättyi eilen → ei pääsyä.
            ("former_board_a", "company_a", "board_member", now - timedelta(days=1)),
            # Muutti pois huoneistosta A 1 kuukausi sitten.
            ("former_resident_a1", "company_a", "shareholder", now - timedelta(days=30)),
            ("resident_a2", "company_a", "resident", None),
        )
        for user, company, role, valid_to in memberships:
            conn.execute(
                text(
                    "INSERT INTO memberships"
                    " (user_id, housing_company_id, role, valid_from, valid_to)"
                    " VALUES (:u, :c, :r, :f, :t)"
                ),
                {
                    "u": ids[user],
                    "c": ids[company],
                    "r": role,
                    "f": now - timedelta(days=400),
                    "t": valid_to,
                },
            )
        _seed_apartments(conn, ids, now)
        _seed_documents(conn, ids, now)
        _seed_faq(conn, ids)
    engine.dispose()
    return ids


def _seed_faq(conn: Connection, ids: dict[str, uuid.UUID]) -> None:
    entries = (
        (
            "Milloin sauna on varattavissa?",
            "Sauna on varattavissa ilmoitustaulun varauslistan mukaan. Vuoro kestää 2 tuntia.",
            10,
        ),
        (
            "Mihin laitan isot jätteet?",
            "Isot jätteet viedään jätekatokseen pihan perällä. Älä jätä niitä rappukäytävään.",
            20,
        ),
    )
    for question, answer, order in entries:
        conn.execute(
            text(
                "INSERT INTO company_faq (housing_company_id, question, answer, sort_order,"
                " created_by) VALUES (:c, :q, :a, :o, :u)"
            ),
            {"c": ids["company_a"], "q": question, "a": answer, "o": order, "u": ids["manager"]},
        )


def _seed_apartments(conn: Connection, ids: dict[str, uuid.UUID], now: datetime) -> None:
    for key, label in (("apt_a1", "A 1"), ("apt_a2", "A 2")):
        conn.execute(
            text("INSERT INTO apartments (id, housing_company_id, label) VALUES (:id, :c, :l)"),
            {"id": ids[key], "c": ids["company_a"], "l": label},
        )
    occupancies = (
        # Aiempi osakas asui A 1:ssä, nykyinen osakas muutti tilalle.
        ("former_resident_a1", "apt_a1", "shareholder", 800, now - timedelta(days=30)),
        ("shareholder_a", "apt_a1", "shareholder", 29, None),
        ("resident_a2", "apt_a2", "resident", 200, None),
    )
    for user, apt, relation, days_ago, valid_to in occupancies:
        conn.execute(
            text(
                "INSERT INTO apartment_occupancies"
                " (housing_company_id, apartment_id, user_id, relation, valid_from, valid_to)"
                " VALUES (:c, :a, :u, :r, :f, :t)"
            ),
            {
                "c": ids["company_a"],
                "a": ids[apt],
                "u": ids[user],
                "r": relation,
                "f": now - timedelta(days=days_ago),
                "t": valid_to,
            },
        )
    # Aiemman asukkaan suljettu vahinko: uusi asukas saa nähdä vain tyypin, tilan, päivät
    # ja isännöitsijän historiamerkinnän – ei otsikkoa, kuvausta eikä tekijää.
    conn.execute(
        text(
            "INSERT INTO cases (id, housing_company_id, case_type, title, description, status,"
            " event_date, created_by, apartment_id, history_note)"
            " VALUES (:id, :c, 'damage', :title, :descr, 'closed', :d, :u, :a, :note)"
        ),
        {
            "id": ids["old_case_a1"],
            "c": ids["company_a"],
            "title": "Maijan astianpesukone vuoti",
            "descr": "Yksityinen kuvaus, jota uusi asukas ei saa nähdä.",
            "d": (now - timedelta(days=300)).date(),
            "u": ids["former_resident_a1"],
            "a": ids["apt_a1"],
            "note": "Keittiön lattia ja kaapisto uusittu vesivahingon jälkeen.",
        },
    )
    conn.execute(
        text(
            "INSERT INTO case_events (housing_company_id, case_id, event_type, from_status,"
            " to_status, actor_user_id, actor_name, created_at)"
            " VALUES (:c, :case, 'close', 'sent', 'closed', :u, 'Isa Isännöitsijä', :t)"
        ),
        {
            "c": ids["company_a"],
            "case": ids["old_case_a1"],
            "u": ids["manager"],
            "t": now - timedelta(days=250),
        },
    )


MINUTES_VISIBLE = [
    [
        "As Oy Esimerkkikoivu - Hallituksen kokous 4/2026",
        "Aika: 23.9.2026 klo 18.00. Paikka: kerhohuone.",
        "1. Kokouksen avaus ja laillisuus. Kokous todettiin lailliseksi.",
        "2. Porrashuoneiden maalaus.",
        "Hallitus päätti pyytää tarjoukset A- ja B-porrashuoneiden seinien ja kattojen",
        "maalauksesta. Työ tehdään keväällä 2027. Tarjoukset pyydetään vähintään kolmelta",
        "urakoitsijalta.",
    ],
    [
        "3. Ikkunoiden pesu.",
        "Ikkunat pestään syksyllä 2026. Osakkaille tiedotetaan aikataulusta porraskäytävässä.",
        "4. Kokouksen päättäminen klo 19.30.",
    ],
]
MINUTES_HIDDEN = [
    [
        "As Oy Esimerkkikoivu - Hallituksen kokous 5/2026 (luottamuksellinen)",
        "Käsiteltiin yhden osakkaan maksurästit. Asia siirretään perintään.",
    ]
]


def _seed_documents(conn: Connection, ids: dict[str, uuid.UUID], now: datetime) -> None:
    docs = (
        (
            "Hallituksen kokous 4/2026",
            True,
            "Päätettiin porrashuoneiden maalauksesta.",
            20,
            MINUTES_VISIBLE,
        ),
        ("Hallituksen kokous 5/2026 (luottamuksellinen)", False, None, 5, MINUTES_HIDDEN),
    )
    for title, visible, description, days_ago, pages in docs:
        doc_id = uuid.uuid4()
        pdf = make_text_pdf(pages)
        conn.execute(
            text(
                "INSERT INTO company_documents (id, housing_company_id, title, meeting_date,"
                " description, visible_to_residents, uploaded_by, uploaded_by_name, uploaded_at,"
                " filename, content_type, size_bytes, sha256)"
                " VALUES (:id, :c, :t, :md, :d, :v, :by, 'Isa Isännöitsijä', :at,"
                " 'poytakirja.pdf', 'application/pdf', :size, :sha)"
            ),
            {
                "id": doc_id,
                "c": ids["company_a"],
                "t": title,
                "md": (now - timedelta(days=days_ago + 2)).date(),
                "d": description,
                "v": visible,
                "by": ids["manager"],
                "at": now - timedelta(days=days_ago),
                "size": len(pdf),
                "sha": hashlib.sha256(pdf).hexdigest(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO company_document_files (document_id, housing_company_id, content)"
                " VALUES (:id, :c, :content)"
            ),
            {"id": doc_id, "c": ids["company_a"], "content": pdf},
        )
        for page_no, page_text in enumerate(extract_pages(pdf), start=1):
            conn.execute(
                text(
                    "INSERT INTO company_document_pages"
                    " (document_id, housing_company_id, page_no, text) VALUES (:d, :c, :n, :t)"
                ),
                {"d": doc_id, "c": ids["company_a"], "n": page_no, "t": page_text},
            )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ.get("TALOAPURI_MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("Aseta TALOAPURI_MIGRATION_DATABASE_URL (ks. .env.example).")
    seed(url)
    print("Testikäyttäjät – kirjaudu sähköpostilla:")
    print("  isa@esimerkki.fi       isännöitsijä (molemmat yhtiöt)")
    print("  olli@esimerkki.fi      osakas, huoneisto A 1")
    print("  ville@esimerkki.fi     asukas (vuokralainen), huoneisto A 2")
    print("  maija@esimerkki.fi     muuttanut pois A 1:stä – ei pääsyä")
    print("  entinen@esimerkki.fi   hallituskausi päättynyt – ei pääsyä")
    print("  hanna@esimerkki.fi     hallituksen jäsen, vain As Oy Testimänty")
    print("  yllapito@esimerkki.fi  palvelun ylläpitäjä (lakilähteet), ei yhtiöiden tietoja")


if __name__ == "__main__":
    main()
