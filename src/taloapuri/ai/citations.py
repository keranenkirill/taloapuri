"""Viitattavat lähteet ja tekoälyn lähdeviitteiden tarkistus.

Jokainen lähde lähetetään tekoälylle yhtenä dokumenttina, jonka lohkot ovat lain momentteja
tai PDF:n sivuja. Claude palauttaa viitteen muodossa (dokumentti, lohkoväli, lainaus).
Viite on "tarkistettu" vain, jos lainaus löytyy sanatarkasti viitatuista lohkoista.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from taloapuri.ai.provider import AiCitation, AiDocument, AiResult

SourceKind = Literal["law", "minutes", "offer", "form"]
_WS = re.compile(r"\s+")


def normalize(value: str) -> str:
    return _WS.sub(" ", value).strip()


@dataclass(frozen=True)
class CitableBlock:
    text: str
    number: int | None  # momentti tai sivunumero
    ref_id: uuid.UUID | None = None  # esim. source_sections.id


@dataclass
class CitableSource:
    kind: SourceKind
    label: str  # "AOYL 4 luku 2 §", "Pöytäkirja: Hallituksen kokous 4/2026"
    title: str  # tekoälylle näytettävä otsikko
    context: str  # tekoälylle, ei viitattavissa
    link: str | None
    blocks: list[CitableBlock] = field(default_factory=list)

    @property
    def unit(self) -> str:
        return "mom." if self.kind == "law" else "s."


@dataclass(frozen=True)
class ResolvedCitation:
    ord: int
    kind: SourceKind | Literal["unknown"]
    label: str
    cited_text: str
    verified: bool
    link: str | None
    ref_id: uuid.UUID | None


def to_documents(sources: list[CitableSource]) -> list[AiDocument]:
    return [
        AiDocument(title=s.title, context=s.context, blocks=[b.text for b in s.blocks])
        for s in sources
    ]


def resolve(sources: list[CitableSource], citation: AiCitation, ord_: int) -> ResolvedCitation:
    if not 0 <= citation.document_index < len(sources):
        return ResolvedCitation(
            ord_, "unknown", "Tuntematon lähde", citation.cited_text, False, None, None
        )
    source = sources[citation.document_index]
    start, end = citation.start_block_index, citation.end_block_index
    blocks = source.blocks[start:end] if 0 <= start < end else []
    label = source.label
    numbers = [b.number for b in blocks if b.number is not None]
    if numbers:
        span = str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}"
        label = (
            f"{label} {span} {source.unit}"
            if source.kind == "law"
            else f"{label}, {source.unit} {span}"
        )
    verified = bool(blocks) and normalize(citation.cited_text) in normalize(
        " ".join(b.text for b in blocks)
    )
    return ResolvedCitation(
        ord_,
        source.kind,
        label[:100],
        citation.cited_text,
        verified,
        source.link,
        blocks[0].ref_id if blocks else None,
    )


def resolve_all(
    sources: list[CitableSource], result: AiResult
) -> tuple[list[dict[str, Any]], list[ResolvedCitation]]:
    """Palauttaa (segmentit viitenumeroineen, viitteet)."""
    segments: list[dict[str, Any]] = []
    citations: list[ResolvedCitation] = []
    for segment in result.segments:
        refs = []
        for c in segment.citations:
            resolved = resolve(sources, c, len(citations) + 1)
            citations.append(resolved)
            refs.append(resolved.ord)
        segments.append({"text": segment.text, "citations": refs})
    return segments, citations
