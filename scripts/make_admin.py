"""Antaa tai poistaa palvelun ylläpitäjän oikeuden käyttäjältä sähköpostiosoitteen perusteella.

Käyttö:
    python scripts/make_admin.py isa@esimerkki.fi
    python scripts/make_admin.py isa@esimerkki.fi --revoke

Palvelun ylläpitäjä hallitsee lakilähteitä (/yllapito/lait). Hän ei näe taloyhtiöiden tietoja.
Lippua ei voi asettaa sovelluksen kautta, vain tällä skriptillä (omistajarooli,
TALOAPURI_MIGRATION_DATABASE_URL).
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true", help="poista ylläpitäjän oikeus")
    args = parser.parse_args()
    url = os.environ.get("TALOAPURI_MIGRATION_DATABASE_URL")
    if not url:
        print("Aseta TALOAPURI_MIGRATION_DATABASE_URL (ks. .env.example).", file=sys.stderr)
        return 2
    engine = create_engine(url)
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET is_platform_admin = :a WHERE lower(email) = lower(:e)"),
            {"a": not args.revoke, "e": args.email.strip()},
        )
    engine.dispose()
    if result.rowcount == 0:
        print(f"Käyttäjää ei löytynyt sähköpostilla {args.email}.", file=sys.stderr)
        return 1
    print(f"{args.email}: ylläpitäjän oikeus {'poistettu' if args.revoke else 'annettu'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
