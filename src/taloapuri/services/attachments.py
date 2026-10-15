"""Valokuvat asioihin.

Jokainen kuva avataan, käännetään EXIF-suunnan mukaan ja koodataan uudelleen JPEGiksi ilman
metatietoja (sijainti, laite). Näin myös mahdollinen haitallinen sisältö alkuperäisessä
tiedostossa ei päädy talteen. Kuvia ei koskaan lähetetä tekoälylle.
"""

import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from taloapuri.auth import CompanyContext
from taloapuri.models import CaseAttachment
from taloapuri.services.audit import write_audit
from taloapuri.services.documents import safe_filename

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 50_000_000  # suoja "pakkauspommeja" vastaan

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_CASE = 10
MAX_SIDE = 2560
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


class InvalidImage(Exception):
    pass


class NotFound(Exception):
    pass


def _stem(name: str) -> str:
    """Tiedostonimi ilman polkua ja päätettä (kuva tallennetaan aina .jpg-tiedostona)."""
    base = safe_filename(name)[: -len(".pdf")]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base or "kuva"


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class AttachmentFile:
    filename: str
    content: bytes


def process_image(raw: bytes) -> ProcessedImage:
    """Tarkistaa ja koodaa kuvan uudelleen.

    Nostaa InvalidImage-virheen selkokielisellä viestillä.
    """
    if not raw:
        raise InvalidImage("Kuvatiedosto on tyhjä.")
    if len(raw) > MAX_BYTES:
        raise InvalidImage("Kuva on liian suuri. Enimmäiskoko on 10 Mt.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise InvalidImage(
                "Kuvan muoto ei ole tuettu. Käytä JPEG-, PNG-, WebP- tai HEIC-kuvaa."
            )
        with Image.open(io.BytesIO(raw)) as image:
            oriented = ImageOps.exif_transpose(image)
            rgb = oriented.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise InvalidImage("Tiedosto ei ole kelvollinen kuva.") from exc
    rgb.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    # Uusi kuva ilman exif/icc/xmp-tietoja.
    rgb.save(out, format="JPEG", quality=85, optimize=True)
    return ProcessedImage(data=out.getvalue(), width=rgb.width, height=rgb.height)


def count_for_case(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(CaseAttachment)
            .where(
                CaseAttachment.case_id == case_id,
                CaseAttachment.housing_company_id == ctx.company_id,
            )
        ).scalar_one()
    )


def prepare_photos(files: list[tuple[str, bytes]]) -> list[tuple[str, ProcessedImage]]:
    """Tarkistaa ja käsittelee kuvat ennen kuin mitään tallennetaan tietokantaan.

    Kaikki tai ei mitään: virhe yhdessä kuvassa hylkää koko erän.
    """
    files = [(name, data) for name, data in files if data]
    if len(files) > MAX_PER_CASE:
        raise InvalidImage(f"Asiaan voi liittää enintään {MAX_PER_CASE} kuvaa.")
    processed = []
    for index, (name, data) in enumerate(files, start=1):
        try:
            processed.append((name, process_image(data)))
        except InvalidImage as exc:
            raise InvalidImage(f"Kuva {index} ({_stem(name)}): {exc}") from exc
    return processed


def add_photos(
    db: Session,
    ctx: CompanyContext,
    case_id: uuid.UUID,
    photos: list[tuple[str, ProcessedImage]],
) -> int:
    """Tallentaa valmiiksi käsitellyt kuvat (ks. prepare_photos)."""
    if not photos:
        return 0
    if count_for_case(db, ctx, case_id) + len(photos) > MAX_PER_CASE:
        raise InvalidImage(f"Asiaan voi liittää enintään {MAX_PER_CASE} kuvaa.")
    for name, image in photos:
        attachment_id = uuid.uuid4()
        base = _stem(name)
        db.execute(
            text(
                "INSERT INTO case_attachments (id, housing_company_id, case_id, uploaded_by,"
                " filename, content_type, size_bytes, width, height, sha256)"
                " VALUES (:id, :c, :case, :by, :fn, 'image/jpeg', :size, :w, :h, :sha)"
            ),
            {
                "id": attachment_id,
                "c": ctx.company_id,
                "case": case_id,
                "by": ctx.user_id,
                "fn": f"{base[:190]}.jpg",
                "size": len(image.data),
                "w": image.width,
                "h": image.height,
                "sha": hashlib.sha256(image.data).hexdigest(),
            },
        )
        db.execute(
            text(
                "INSERT INTO case_attachment_files (attachment_id, housing_company_id, content)"
                " VALUES (:id, :c, :content)"
            ),
            {"id": attachment_id, "c": ctx.company_id, "content": image.data},
        )
    write_audit(db, ctx, "case.photos_added", "case", case_id, count=len(photos))
    return len(photos)


def list_for_case(db: Session, ctx: CompanyContext, case_id: uuid.UUID) -> list[CaseAttachment]:
    return list(
        db.execute(
            select(CaseAttachment)
            .where(
                CaseAttachment.case_id == case_id,
                CaseAttachment.housing_company_id == ctx.company_id,
            )
            .order_by(CaseAttachment.created_at)
        ).scalars()
    )


def get_file(
    db: Session, ctx: CompanyContext, case_id: uuid.UUID, attachment_id: uuid.UUID
) -> AttachmentFile:
    row = db.execute(
        text(
            "SELECT a.filename, f.content FROM case_attachments a"
            " JOIN case_attachment_files f ON f.attachment_id = a.id"
            " WHERE a.id = :id AND a.case_id = :case AND a.housing_company_id = :c"
        ),
        {"id": attachment_id, "case": case_id, "c": ctx.company_id},
    ).first()
    if row is None:
        raise NotFound(attachment_id)
    return AttachmentFile(filename=row[0], content=bytes(row[1]))
