"""Oikean tekoälyn savutesti kehityskantaa vasten (MAKSULLINEN, noin 0,01–0,10 $).

Ajaa neljä oikeaa kutsua ja tulostaa lähdeviitteet tarkistusmerkintöineen sekä kustannukset:
  1. lakikysymys (osakas), 2. kysymys pöytäkirjasta (osakas),
  3. tarjouspyyntöluonnos (isännöitsijä), 4. kahden tarjouksen vertailu (isännöitsijä).

Edellytykset: alembic upgrade head, scripts/seed_dev.py ja scripts/ingest_finlex.py ajettu,
ANTHROPIC_API_KEY asetettu (ympäristöön tai .env-tiedostoon). Avainta ei tulosteta.
Tulokset tallentuvat kehityskantaan, joten ne näkyvät myös käyttöliittymässä.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sample_pdf import make_text_pdf
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from taloapuri.ai.provider import AnthropicProvider
from taloapuri.auth import CompanyContext
from taloapuri.config import Settings
from taloapuri.db import set_company_context, set_user_context
from taloapuri.domain.roles import Role
from taloapuri.services import cases as case_svc
from taloapuri.services import chat, tenders

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    load_dotenv(ROOT / ".env")


def _ctx(db: Session, email: str) -> CompanyContext:
    owner = create_engine(os.environ["TALOAPURI_MIGRATION_DATABASE_URL"])
    with owner.connect() as conn:
        user_id, name = conn.execute(
            text("SELECT id, display_name FROM users WHERE lower(email) = :e"), {"e": email}
        ).one()
        company_id, company_name = conn.execute(
            text("SELECT id, name FROM housing_companies WHERE name = 'As Oy Esimerkkikoivu'")
        ).one()
        roles = (
            conn.execute(
                text(
                    "SELECT role FROM memberships WHERE user_id = :u AND housing_company_id = :c"
                    " AND (valid_to IS NULL OR valid_to > now())"
                ),
                {"u": user_id, "c": company_id},
            )
            .scalars()
            .all()
        )
    owner.dispose()
    set_user_context(db, user_id)
    set_company_context(db, company_id)
    return CompanyContext(
        company_id, company_name, user_id, frozenset(Role(r) for r in roles), name
    )


def _print_citations(citations: list[dict[str, object]] | list[chat.CitationView]) -> int:
    unverified = 0
    for c in citations:
        verified = c["verified"] if isinstance(c, dict) else c.verified
        label = c["label"] if isinstance(c, dict) else c.label
        quote = str(c["cited_text"] if isinstance(c, dict) else c.cited_text)
        unverified += 0 if verified else 1
        print(f'    [{"✓" if verified else "⚠"}] {label}: "{quote[:90]}"')
    return unverified


def main() -> None:
    _load_dotenv()
    settings = Settings(ai_enabled=True)
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY puuttuu (.env tai ympäristö).")
    provider = AnthropicProvider(settings)
    engine = create_engine(settings.database_url)
    total_unverified = 0

    def run(email: str, title: str, fn) -> None:  # type: ignore[no-untyped-def]
        nonlocal total_unverified
        print(f"\n=== {title} ({email}) ===")
        try:
            with Session(engine) as db, db.begin():
                ctx = _ctx(db, email)
                total_unverified += fn(db, ctx)
        except tenders.TenderError as exc:
            print(f"  VIRHE: {exc}")

    def ask(question: str):  # type: ignore[no-untyped-def]
        def inner(db: Session, ctx: CompanyContext) -> int:
            thread = chat.ask(db, ctx, settings, provider, question)
            answer = chat.thread_messages(db, ctx, thread)[-1]
            print(f"  tila: {answer.status}")
            print("  " + answer.text.replace("\n", "\n  ")[:1200])
            return _print_citations(answer.citations)

        return inner

    def draft(db: Session, ctx: CompanyContext) -> int:
        case = case_svc.create_case(
            db,
            ctx,
            case_type="tender_request",
            title="Porrashuoneiden maalaus",
            description="",
            event_date=None,
            details={
                "target": "Porrashuoneiden maalaus",
                "scope": "A- ja B-portaiden seinät ja katot, noin 600 m2. Värisävy ennallaan.",
                "offers_due": "2026-12-01",
                "requirements": "Vastuuvakuutus.",
                "budget_note": "max 20 000 €",
            },
        )
        output_id = tenders.generate_draft(db, ctx, settings, provider, case.id)
        out = tenders.latest_output(db, ctx, case.id, "tender_draft")
        assert out is not None and out.id == output_id
        print("  " + out.text.replace("\n", "\n  ")[:1500])
        print(f"  (budjetti lähetettiin tekoälylle: {'20 000' in out.text})")
        offer_a = make_text_pdf(
            [
                [
                    "Maalaus Oy - Tarjous porrashuoneiden maalauksesta",
                    "Kokonaishinta 18 400 euroa (alv 0 %). Hinta sisältää telineet",
                    "ja suojaukset. Työ 3.-28.4.2027. Takuu 2 vuotta.",
                    "Maksuehto 14 pv netto, 30 % ennakko.",
                ]
            ]
        )
        offer_b = make_text_pdf(
            [
                [
                    "Pensseli Ky - Urakkatarjous",
                    "Hinta 16 900 euroa + alv. Telineet eivät sisälly hintaan.",
                    "Aloitus toukokuussa 2027. Takuu 1 vuosi.",
                    "Lisätyöt laskutetaan tuntityönä 52 euroa/h.",
                ]
            ]
        )
        tenders.upload_offer(
            db,
            ctx,
            case.id,
            contractor_name="Maalaus Oy",
            total_price="18400",
            filename="maalaus.pdf",
            data=offer_a,
        )
        tenders.upload_offer(
            db,
            ctx,
            case.id,
            contractor_name="Pensseli Ky",
            total_price="16900",
            filename="pensseli.pdf",
            data=offer_b,
        )
        tenders.compare_offers(db, ctx, settings, provider, case.id)
        comparison = tenders.latest_output(db, ctx, case.id, "offer_comparison")
        assert comparison is not None
        print("\n  --- vertailu ---")
        print("  " + comparison.text.replace("\n", "\n  ")[:2500])
        return _print_citations(out.citations) + _print_citations(comparison.citations)

    run("olli@esimerkki.fi", "1+2 Lakikysymys", ask("Kuka vastaa kylpyhuoneen vedeneristyksestä?"))
    run(
        "olli@esimerkki.fi",
        "Pöytäkirjakysymys",
        ask("Mitä hallitus on päättänyt porrashuoneiden maalauksesta?"),
    )
    run("isa@esimerkki.fi", "3+4 Tarjouspyyntö ja vertailu", draft)

    owner = create_engine(os.environ["TALOAPURI_MIGRATION_DATABASE_URL"])
    with owner.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT kind, model, input_tokens, output_tokens, cost_usd, error FROM ai_runs"
                " ORDER BY created_at DESC LIMIT 4"
            )
        ).all()
    owner.dispose()
    print("\n=== Kustannukset (arvio) ===")
    total = Decimal(0)
    for kind, model, tin, tout, cost, error in reversed(rows):
        total += cost
        print(f"  {kind:17} {model:20} in={tin:6} out={tout:5} ${cost}  {error or ''}")
    print(f"  Yhteensä ${total}. Vahvistamattomia viitteitä: {total_unverified}.")
    if any(error == "authentication" for *_, error in rows):
        print(
            "\n  API-avain hylättiin (401 invalid x-api-key). Tarkista avain osoitteessa"
            " console.anthropic.com → API Keys ja päivitä .env-tiedostoon."
        )
    engine.dispose()


if __name__ == "__main__":
    main()
