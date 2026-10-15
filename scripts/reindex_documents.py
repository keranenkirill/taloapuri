"""Poimii sivutekstit asiakirjoille, joilta ne puuttuvat (esim. ennen migraatiota 0008 ladatut).

Käyttö: python scripts/reindex_documents.py   (omistajarooli, TALOAPURI_MIGRATION_DATABASE_URL)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from taloapuri.sources.pdf_text import extract_pages


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ.get("TALOAPURI_MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("Aseta TALOAPURI_MIGRATION_DATABASE_URL (ks. .env.example).")
    engine = create_engine(url)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT d.id, d.housing_company_id, f.content FROM company_documents d"
                " JOIN company_document_files f ON f.document_id = d.id"
                " WHERE NOT EXISTS (SELECT 1 FROM company_document_pages p"
                "                    WHERE p.document_id = d.id)"
            )
        ).all()
        for doc_id, company_id, content in rows:
            pages = extract_pages(bytes(content))
            for page_no, page_text in enumerate(pages, start=1):
                if page_text.strip():
                    conn.execute(
                        text(
                            "INSERT INTO company_document_pages"
                            " (document_id, housing_company_id, page_no, text)"
                            " VALUES (:d, :c, :n, :t)"
                        ),
                        {"d": doc_id, "c": company_id, "n": page_no, "t": page_text},
                    )
            state = f"{len(pages)} sivua" if pages else "ei tekstiä (skannattu?)"
            print(f"{doc_id}: {state}")
    engine.dispose()
    print(f"Käsitelty {len(rows)} asiakirjaa.")


if __name__ == "__main__":
    main()
