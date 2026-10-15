"""Hakee ja päivittää lakilähteet Finlexistä (ajantasainen lainsäädäntö).

Käyttö:
    python scripts/ingest_finlex.py                  # tarkista ja päivitä kaikki käytössä olevat
    python scripts/ingest_finlex.py --add 2002/453 --name KTJL   # lisää uusi laki (vuosi/numero)
    python scripts/ingest_finlex.py --file x.akn     # lue AOYL paikallisesta tiedostosta

Ensimmäisellä ajolla tallennetaan asunto-osakeyhtiölaki (1599/2009). Uusi versio tallennetaan vain,
jos Finlexin teksti on muuttunut; vanha versio säilyy historiana. Yhdistää omistajaroolilla
(TALOAPURI_MIGRATION_DATABASE_URL). Soveltuu ajastettavaksi (cron / Windowsin Tehtävien ajoitus):
poistumiskoodi on 1, jos jonkin lain päivitys epäonnistui.

Selaimesta tämän tekee palvelun ylläpitäjä sivulla /yllapito/lait.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, text

from taloapuri.sources import updater
from taloapuri.sources.finlex import FinlexError, fetch_act, parse_akn, public_url
from taloapuri.sources.ingest import ingest_act

CORE = (2009, 1599, "AOYL")


def _print_update(short: str, result: updater.UpdateResult) -> None:
    if not result.changed:
        print(f"{short}: ei muutoksia (versio {result.version_label}).")
        return
    s = result.summary
    detail = f" – {s.changed} muuttunut, {s.added} lisätty, {s.removed} poistettu" if s else ""
    print(f"{short}: päivitetty versioon {result.version_label}{detail}.")
    for item in (s.items if s else [])[:10]:
        print(f"    {item['kind']}: {item['label']}")


def _ensure_core(conn: Connection) -> None:
    year, number, short = CORE
    key = updater.source_key_for(year, number)
    if conn.execute(text("SELECT 1 FROM sources WHERE source_key = :k"), {"k": key}).first():
        return
    preview = updater.preview(year, number, fetch_act)
    updater.add_source(
        conn,
        year=year,
        number=number,
        short_title=short,
        expected_sha256=preview.sha256,
        fetcher=fetch_act,
        added_by=None,
    )
    print(f"{short}: lisätty ({preview.title}, versio {preview.version_label}).")


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--add", metavar="VUOSI/NUMERO", help="lisää laki, esim. 2002/453")
    parser.add_argument("--name", default="", help="lyhenne lähdeviitteisiin, esim. KTJL")
    parser.add_argument(
        "--file", help="paikallinen Akoma Ntoso -tiedosto AOYL:lle (ei verkkohakua)"
    )
    args = parser.parse_args()
    url = os.environ.get("TALOAPURI_MIGRATION_DATABASE_URL")
    if not url:
        print("Aseta TALOAPURI_MIGRATION_DATABASE_URL (ks. .env.example).", file=sys.stderr)
        return 2
    engine = create_engine(url)
    failures = 0
    try:
        if args.file:
            xml = Path(args.file).read_bytes()
            year, number, short = CORE
            with engine.begin() as conn:
                result = ingest_act(
                    conn,
                    parse_akn(xml),
                    source_key=updater.source_key_for(year, number),
                    short_title=short,
                    public_url=public_url(year, number),
                )
                conn.execute(
                    text(
                        "UPDATE sources SET current_version_id = :v, last_checked_at = now()"
                        " WHERE source_key = :k"
                    ),
                    {"v": result.version_id, "k": updater.source_key_for(year, number)},
                )
            print(f"{short}: {'uusi versio tallennettu' if result.created else 'ei muutoksia'}.")
            return 0
        if args.add:
            try:
                year_s, number_s = args.add.split("/")
                year, number = int(year_s), int(number_s)
            except ValueError:
                print("Anna laki muodossa VUOSI/NUMERO, esimerkiksi 2002/453.", file=sys.stderr)
                return 2
            with engine.begin() as conn:
                preview = updater.preview(year, number, fetch_act)
                updater.add_source(
                    conn,
                    year=year,
                    number=number,
                    short_title=args.name,
                    expected_sha256=preview.sha256,
                    fetcher=fetch_act,
                    added_by=None,
                )
            print(
                f"Lisätty: {preview.title} ({number}/{year}), versio {preview.version_label}, "
                f"{preview.row_count} momenttia."
            )
            return 0
        with engine.begin() as conn:
            _ensure_core(conn)
        with engine.connect() as conn:
            keys = conn.execute(
                text("SELECT source_key, short_title FROM sources WHERE active ORDER BY source_key")
            ).all()
        for key, short in keys:
            try:
                with engine.begin() as conn:
                    _print_update(short, updater.check_and_update(conn, key, fetch_act))
            except FinlexError as exc:
                failures += 1
                print(f"{short}: VIRHE – {exc}", file=sys.stderr)
    except FinlexError as exc:
        print(f"VIRHE – {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
