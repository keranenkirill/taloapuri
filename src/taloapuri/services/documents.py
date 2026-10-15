"""Hallituksen pöytäkirjat ja muut yhtiön asiakirjat.

- Vain isännöitsijä (MANAGER_ROLES) voi ladata, piilottaa ja poistaa.
- Isännöitsijä päättää tiedostokohtaisesti, näkevätkö osakkaat ja asukkaat asiakirjan.
  Hallitus ja isännöitsijä näkevät aina (RLS, migraatio 0005).
- Vain PDF (tarkistetaan tiedoston alusta, ei nimestä), enintään 10 Mt. Virustarkistus
  (ClamAV) lisätään, kun tiedostot siirtyvät objektitallennukseen.
"""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.services.audit import write_audit
from taloapuri.sources.pdf_text import extract_pages

MAX_BYTES = 10 * 1024 * 1024
PDF_MAGIC = b"%PDF-"


class NotAllowed(Exception):
    pass


class NotFound(Exception):
    pass


class InvalidUpload(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


@dataclass
class DocumentRow:
    id: uuid.UUID
    title: str
    meeting_date: date | None
    description: str | None
    visible_to_residents: bool
    uploaded_by_name: str
    uploaded_at: datetime
    filename: str
    size_bytes: int


@dataclass
class DocumentFile:
    filename: str
    content_type: str
    content: bytes


def safe_filename(name: str) -> str:
    """Poistaa polut ja erikoismerkit. Säilyttää ääkköset, pakottaa .pdf-päätteen."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .") or "asiakirja"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[-150:]


def upload_minutes(
    db: Session,
    ctx: CompanyContext,
    *,
    title: str,
    meeting_date: date | None,
    description: str,
    visible_to_residents: bool,
    filename: str,
    data: bytes,
) -> uuid.UUID:
    if not ctx.is_manager:
        raise NotAllowed
    errors: dict[str, str] = {}
    title = title.strip()
    if not title:
        errors["title"] = "Kirjoita otsikko, esimerkiksi ”Hallituksen kokous 3/2026”."
    elif len(title) > 200:
        errors["title"] = "Otsikko on liian pitkä. Käytä enintään 200 merkkiä."
    if len(description) > 1000:
        errors["description"] = "Kuvaus on liian pitkä. Käytä enintään 1000 merkkiä."
    if not data:
        errors["file"] = "Valitse ladattava PDF-tiedosto."
    elif len(data) > MAX_BYTES:
        errors["file"] = "Tiedosto on liian suuri. Enimmäiskoko on 10 Mt."
    elif not data.startswith(PDF_MAGIC):
        errors["file"] = "Tiedosto ei ole PDF. Tallenna pöytäkirja PDF-muodossa ja yritä uudelleen."
    if errors:
        raise InvalidUpload(errors)

    document_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO company_documents (id, housing_company_id, kind, title, meeting_date,"
            " description, visible_to_residents, uploaded_by, uploaded_by_name, filename,"
            " content_type, size_bytes, sha256)"
            " VALUES (:id, :c, 'board_minutes', :title, :md, :descr, :vis, :by, :by_name,"
            " :fn, 'application/pdf', :size, :sha)"
        ),
        {
            "id": document_id,
            "c": ctx.company_id,
            "title": title,
            "md": meeting_date,
            "descr": description.strip() or None,
            "vis": visible_to_residents,
            "by": ctx.user_id,
            "by_name": ctx.user_name or "Isännöitsijä",
            "fn": safe_filename(filename),
            "size": len(data),
            "sha": hashlib.sha256(data).hexdigest(),
        },
    )
    db.execute(
        text(
            "INSERT INTO company_document_files (document_id, housing_company_id, content)"
            " VALUES (:id, :c, :content)"
        ),
        {"id": document_id, "c": ctx.company_id, "content": data},
    )
    store_pages(db, ctx, document_id, extract_pages(data))
    write_audit(
        db,
        ctx,
        "document.uploaded",
        "document",
        document_id,
        kind="board_minutes",
        visible_to_residents=visible_to_residents,
    )
    return document_id


def list_documents(db: Session, ctx: CompanyContext, limit: int = 50) -> list[DocumentRow]:
    """RLS rajaa: asukkaat näkevät vain asukkaille näkyviksi merkityt."""
    rows = db.execute(
        text(
            "SELECT id, title, meeting_date, description, visible_to_residents,"
            " uploaded_by_name, uploaded_at, filename, size_bytes"
            " FROM company_documents WHERE housing_company_id = :c AND removed_at IS NULL"
            " ORDER BY uploaded_at DESC LIMIT :limit"
        ),
        {"c": ctx.company_id, "limit": limit},
    ).all()
    return [DocumentRow(*row) for row in rows]


def get_file(db: Session, ctx: CompanyContext, document_id: uuid.UUID) -> DocumentFile:
    row = db.execute(
        text(
            "SELECT d.filename, d.content_type, f.content"
            " FROM company_documents d JOIN company_document_files f ON f.document_id = d.id"
            " WHERE d.id = :id AND d.housing_company_id = :c AND d.removed_at IS NULL"
        ),
        {"id": document_id, "c": ctx.company_id},
    ).first()
    if row is None:
        raise NotFound(document_id)
    return DocumentFile(filename=row[0], content_type=row[1], content=bytes(row[2]))


def set_visibility(db: Session, ctx: CompanyContext, document_id: uuid.UUID, visible: bool) -> None:
    if not ctx.is_manager:
        raise NotAllowed
    result = db.execute(
        text(
            "UPDATE company_documents SET visible_to_residents = :v"
            " WHERE id = :id AND housing_company_id = :c AND removed_at IS NULL"
        ),
        {"v": visible, "id": document_id, "c": ctx.company_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound(document_id)
    write_audit(db, ctx, "document.visibility_changed", "document", document_id, visible=visible)


def remove(db: Session, ctx: CompanyContext, document_id: uuid.UUID) -> None:
    """Pehmeä poisto: asiakirja piilotetaan kaikilta, rivi ja audit säilyvät."""
    if not ctx.is_manager:
        raise NotAllowed
    result = db.execute(
        text(
            "UPDATE company_documents SET removed_at = now()"
            " WHERE id = :id AND housing_company_id = :c AND removed_at IS NULL"
        ),
        {"id": document_id, "c": ctx.company_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound(document_id)
    write_audit(db, ctx, "document.removed", "document", document_id)


def store_pages(db: Session, ctx: CompanyContext, document_id: uuid.UUID, pages: list[str]) -> None:
    """Tallentaa sivujen tekstit hakua ja tekoälyn lähdeviitteitä varten."""
    rows = [
        {"d": document_id, "c": ctx.company_id, "n": number, "t": page_text}
        for number, page_text in enumerate(pages, start=1)
        if page_text.strip()
    ]
    if rows:
        db.execute(
            text(
                "INSERT INTO company_document_pages"
                " (document_id, housing_company_id, page_no, text) VALUES (:d, :c, :n, :t)"
            ),
            rows,
        )


def has_text(db: Session, ctx: CompanyContext, document_id: uuid.UUID) -> bool:
    return bool(
        db.execute(
            text("SELECT EXISTS (SELECT 1 FROM company_document_pages WHERE document_id = :d)"),
            {"d": document_id},
        ).scalar_one()
    )
