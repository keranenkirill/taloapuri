"""Säädöksen tallennus tietokantaan. Ajetaan omistajaroolilla (ylläpito, ei sovelluspyyntö)."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from taloapuri.sources.finlex import ParsedAct

# Ydinlait: niitä ei voi poistaa käytöstä ylläpitosivulta.
CORE_SOURCE_KEYS = frozenset({"fi/statute/2009/1599"})


@dataclass(frozen=True)
class IngestResult:
    version_id: uuid.UUID
    created: bool
    section_count: int


def ingest_act(
    conn: Connection,
    act: ParsedAct,
    *,
    source_key: str,
    short_title: str,
    public_url: str,
    added_by: uuid.UUID | None = None,
    change_summary: dict[str, Any] | None = None,
) -> IngestResult:
    """Tallentaa uuden version vain, jos sisältö (SHA-256) on muuttunut.

    source_key on muotoa "fi/statute/{vuosi}/{numero}".
    """
    year, number = (int(part) for part in source_key.split("/")[2:4])
    source_id = conn.execute(
        text(
            "INSERT INTO sources (source_key, title, short_title, public_url, act_year, act_number,"
            " added_by, is_core)"
            " VALUES (:key, :title, :short, :url, :year, :number, :added_by, :core)"
            " ON CONFLICT (source_key) DO UPDATE SET title = EXCLUDED.title,"
            " short_title = EXCLUDED.short_title, public_url = EXCLUDED.public_url"
            " RETURNING id"
        ),
        {
            "key": source_key,
            "title": act.title,
            "short": short_title,
            "url": public_url,
            "year": year,
            "number": number,
            "added_by": added_by,
            "core": source_key in CORE_SOURCE_KEYS,
        },
    ).scalar_one()
    existing = conn.execute(
        text("SELECT id FROM source_versions WHERE source_id = :s AND sha256 = :h"),
        {"s": source_id, "h": act.sha256},
    ).scalar_one_or_none()
    if existing is not None:
        count = conn.execute(
            text("SELECT count(*) FROM source_sections WHERE version_id = :v"), {"v": existing}
        ).scalar_one()
        return IngestResult(version_id=existing, created=False, section_count=count)

    version_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO source_versions (id, source_id, version_label, consolidated_date, sha256,"
            " change_summary) VALUES (:id, :s, :label, :date, :h, CAST(:summary AS jsonb))"
        ),
        {
            "id": version_id,
            "s": source_id,
            "label": act.version_label,
            "date": act.consolidated_date,
            "h": act.sha256,
            "summary": json.dumps(change_summary, ensure_ascii=False) if change_summary else None,
        },
    )
    conn.execute(
        text(
            "INSERT INTO source_sections (version_id, ord, eid, chapter_num, chapter_heading,"
            " section_num, section_heading, subsection_no, text)"
            " VALUES (:v, :ord, :eid, :cn, :ch, :sn, :sh, :sub, :text)"
        ),
        [
            {
                "v": version_id,
                "ord": s.ord,
                "eid": s.eid,
                "cn": s.chapter_num,
                "ch": s.chapter_heading,
                "sn": s.section_num,
                "sh": s.section_heading,
                "sub": s.subsection_no,
                "text": s.text,
            }
            for s in act.sections
        ],
    )
    conn.execute(
        text("UPDATE sources SET current_version_id = :v WHERE id = :s"),
        {"v": version_id, "s": source_id},
    )
    return IngestResult(version_id=version_id, created=True, section_count=len(act.sections))
