"""Lakilähteiden päivitys Finlexistä: esikatselu, lisäys, tarkistus ja muutosyhteenveto.

Toimii tietokantayhteydellä (Connection), joten sitä käyttävät sekä ylläpitäjän sivu (RLS:n
alla) että ylläpitoskripti (omistajarooli). Teksti tulee vain Finlexin virallisesta osoitteesta
(`finlex.fetch`), ei koskaan käyttäjän syötteestä.

Päivitys EI poista vanhaa versiota: uusi versio muuttuu käytössä olevaksi ja vanha säilyy
historiana, koska aiemmat tekoälyvastaukset viittaavat siihen.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from taloapuri.sources.finlex import (
    Fetcher,
    FinlexError,
    ParsedAct,
    ParsedSection,
    parse_akn,
    public_url,
)
from taloapuri.sources.ingest import ingest_act

MAX_LABELS = 20
# Jos uusi versio on tätä pienempi osa vanhasta, päivitystä ei tehdä itsestään (epäilyttävä).
MIN_SIZE_RATIO = 0.5
_SHORT_NAME = re.compile(r"^[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9 ./-]{0,31}$")

SectionKey = tuple[str, str, int]  # (luku, pykälä, momentti)


class SourceNotFound(FinlexError):
    pass


class AlreadyAdded(FinlexError):
    pass


class PreviewStale(FinlexError):
    pass


class InvalidAct(FinlexError):
    pass


@dataclass
class ChangeSummary:
    added: int = 0
    changed: int = 0
    removed: int = 0
    items: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "items": self.items,
        }

    @property
    def total(self) -> int:
        return self.added + self.changed + self.removed


@dataclass(frozen=True)
class SourceInfo:
    id: uuid.UUID
    source_key: str
    act_year: int
    act_number: int
    title: str
    short_title: str
    public_url: str
    active: bool
    is_core: bool
    last_checked_at: datetime | None
    added_at: datetime
    version_id: uuid.UUID | None
    version_label: str | None
    consolidated_date: date | None
    fetched_at: datetime | None
    change_summary: dict[str, Any] | None
    section_count: int
    version_count: int


@dataclass(frozen=True)
class PreviewResult:
    year: int
    number: int
    title: str
    version_label: str
    consolidated_date: date | None
    sha256: str
    row_count: int
    section_count: int
    sample_heading: str
    sample_text: str


@dataclass(frozen=True)
class UpdateResult:
    source_key: str
    changed: bool
    version_label: str
    consolidated_date: date | None
    summary: ChangeSummary | None
    checked_at: datetime


def source_key_for(year: int, number: int) -> str:
    return f"fi/statute/{year}/{number}"


def validate_act_number(year: int, number: int) -> None:
    current_year = date.today().year
    if not 1700 <= year <= current_year + 1:
        raise InvalidAct(f"Vuoden pitää olla väliltä 1700–{current_year + 1}.")
    if not 1 <= number <= 99999:
        raise InvalidAct("Säädöksen numeron pitää olla väliltä 1–99999.")


def _key(section: ParsedSection) -> SectionKey:
    return (section.chapter_num or "", section.section_num, section.subsection_no or 0)


def label_for(key: SectionKey) -> str:
    chapter, section, sub = key
    return " ".join(p for p in (chapter, section, f"{sub} mom." if sub else "") if p)


def compute_diff(old: dict[SectionKey, str], new_sections: list[ParsedSection]) -> ChangeSummary:
    """Vertaa versioita luvun, pykälän ja momentin numerolla (eId muuttuu muutoksen mukana)."""
    new = {_key(s): s.text for s in new_sections}
    summary = ChangeSummary()
    for key in sorted(new.keys() | old.keys()):
        if key in new and key not in old:
            kind = "lisätty"
            summary.added += 1
        elif key in old and key not in new:
            kind = "poistettu"
            summary.removed += 1
        elif old[key] != new[key]:
            kind = "muuttunut"
            summary.changed += 1
        else:
            continue
        if len(summary.items) < MAX_LABELS:
            summary.items.append({"kind": kind, "label": label_for(key)})
    return summary


def _load_sections(conn: Connection, version_id: uuid.UUID) -> dict[SectionKey, str]:
    rows = conn.execute(
        text(
            "SELECT coalesce(chapter_num, ''), section_num, coalesce(subsection_no, 0), text"
            " FROM source_sections WHERE version_id = :v"
        ),
        {"v": version_id},
    ).all()
    return {(r[0], r[1], r[2]): r[3] for r in rows}


def _parse_checked(fetcher: Fetcher, year: int, number: int) -> ParsedAct:
    parsed = parse_akn(fetcher(year, number))
    if not parsed.sections:
        raise FinlexError("Finlexin säädöksestä ei löytynyt yhtään pykälää. Päivitystä ei tehty.")
    return parsed


def preview(year: int, number: int, fetcher: Fetcher) -> PreviewResult:
    """Hakee ja jäsentää säädöksen tallentamatta mitään."""
    validate_act_number(year, number)
    parsed = _parse_checked(fetcher, year, number)
    first = parsed.sections[0]
    return PreviewResult(
        year=year,
        number=number,
        title=parsed.title,
        version_label=parsed.version_label,
        consolidated_date=parsed.consolidated_date,
        sha256=parsed.sha256,
        row_count=len(parsed.sections),
        section_count=len({(s.chapter_num, s.section_num) for s in parsed.sections}),
        sample_heading=" ".join(
            p for p in (first.chapter_num, first.section_num, first.section_heading) if p
        ),
        sample_text=first.text[:300],
    )


def add_source(
    conn: Connection,
    *,
    year: int,
    number: int,
    short_title: str,
    expected_sha256: str,
    fetcher: Fetcher,
    added_by: uuid.UUID | None,
) -> str:
    """Lisää uuden lain. Vaatii, että haettu teksti on sama kuin esikatselussa (SHA-256)."""
    validate_act_number(year, number)
    key = source_key_for(year, number)
    short = short_title.strip() or f"{number}/{year}"
    if not _SHORT_NAME.match(short):
        raise InvalidAct(
            "Lyhenne saa sisältää kirjaimia, numeroita sekä merkit . / - ja välilyönnin."
        )
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})
    if conn.execute(text("SELECT 1 FROM sources WHERE source_key = :k"), {"k": key}).first():
        raise AlreadyAdded("Tämä laki on jo lisätty.")
    if conn.execute(
        text("SELECT 1 FROM sources WHERE lower(short_title) = lower(:s)"), {"s": short}
    ).first():
        raise InvalidAct(f"Lyhenne ”{short}” on jo toisen lain käytössä. Valitse toinen lyhenne.")
    parsed = _parse_checked(fetcher, year, number)
    if parsed.sha256 != expected_sha256:
        raise PreviewStale(
            "Finlexin teksti ehti muuttua esikatselun jälkeen. Katso esikatselu uudelleen."
        )
    result = ingest_act(
        conn,
        parsed,
        source_key=key,
        short_title=short,
        public_url=public_url(year, number),
        added_by=added_by,
    )
    conn.execute(
        text(
            "UPDATE sources SET current_version_id = :v, last_checked_at = now()"
            " WHERE source_key = :k"
        ),
        {"v": result.version_id, "k": key},
    )
    return key


def check_and_update(conn: Connection, source_key: str, fetcher: Fetcher) -> UpdateResult:
    """Hakee uusimman ajantasaisen version. Muuttunut teksti tallennetaan ja otetaan käyttöön."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": source_key})
    row = conn.execute(
        text(
            "SELECT s.id, s.act_year, s.act_number, s.short_title, s.public_url,"
            " s.current_version_id, v.sha256, v.version_label, v.consolidated_date"
            " FROM sources s LEFT JOIN source_versions v ON v.id = s.current_version_id"
            " WHERE s.source_key = :k"
        ),
        {"k": source_key},
    ).one_or_none()
    if row is None:
        raise SourceNotFound("Lakia ei löytynyt.")
    source_id, year, number, short_title, url, current_id, current_sha, cur_label, cur_date = row
    parsed = _parse_checked(fetcher, year, number)

    if current_id is not None and current_sha == parsed.sha256:
        checked_at = conn.execute(
            text(
                "UPDATE sources SET last_checked_at = now() WHERE id = :s RETURNING last_checked_at"
            ),
            {"s": source_id},
        ).scalar_one()
        return UpdateResult(source_key, False, cur_label or "", cur_date, None, checked_at)

    old = _load_sections(conn, current_id) if current_id is not None else {}
    if old and len(parsed.sections) < len(old) * MIN_SIZE_RATIO:
        raise FinlexError(
            f"Uusi versio on huomattavasti pienempi ({len(old)} → {len(parsed.sections)} "
            "momenttia). "
            "Päivitystä ei tehty. Tarkista säädös Finlexistä."
        )
    summary = compute_diff(old, parsed.sections) if old else None
    result = ingest_act(
        conn,
        parsed,
        source_key=source_key,
        short_title=short_title,
        public_url=url,
        change_summary=summary.to_dict() if summary else None,
    )
    checked_at = conn.execute(
        text(
            "UPDATE sources SET current_version_id = :v, last_checked_at = now()"
            " WHERE id = :s RETURNING last_checked_at"
        ),
        {"v": result.version_id, "s": source_id},
    ).scalar_one()
    return UpdateResult(
        source_key, True, parsed.version_label, parsed.consolidated_date, summary, checked_at
    )


def set_active(conn: Connection, source_key: str, active: bool) -> None:
    result = conn.execute(
        text("UPDATE sources SET active = :a WHERE source_key = :k AND (:a OR NOT is_core)"),
        {"a": active, "k": source_key},
    )
    if result.rowcount == 0:
        raise SourceNotFound("Lakia ei löytynyt tai sitä ei voi poistaa käytöstä.")


def list_sources(conn: Connection) -> list[SourceInfo]:
    rows = conn.execute(
        text(
            """
            SELECT s.id, s.source_key, s.act_year, s.act_number, s.title, s.short_title,
                   s.public_url, s.active, s.is_core, s.last_checked_at, s.added_at,
                   v.id, v.version_label, v.consolidated_date, v.fetched_at, v.change_summary,
                   coalesce((SELECT count(*) FROM source_sections ss
                              WHERE ss.version_id = v.id), 0),
                   (SELECT count(*) FROM source_versions sv WHERE sv.source_id = s.id)
              FROM sources s
              LEFT JOIN source_versions v ON v.id = s.current_version_id
             ORDER BY s.is_core DESC, s.short_title
            """
        )
    ).all()
    return [SourceInfo(*row) for row in rows]
