"""Tekoälytoimintojen etenemistapahtumat (striimaus selaimeen Server-Sent Events -muodossa)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from taloapuri.ai.provider import AiDocument, AiProvider, AiResult

EventKind = Literal["status", "delta", "done", "error"]


@dataclass(frozen=True)
class StreamEvent:
    kind: EventKind
    text: str = ""  # status: selkokielinen vaihe; delta: tekstipala; error: virheviesti
    ref_id: uuid.UUID | None = None  # done: keskustelun tai tuotoksen tunniste
    data: dict[str, str] = field(default_factory=dict)


def stream_model(
    provider: AiProvider,
    system: str,
    documents: list[AiDocument],
    question: str,
    max_tokens: int | None,
    result_box: list[AiResult],
) -> Iterator[StreamEvent]:
    """Välittää mallin tekstipalat delta-tapahtumina; lopullinen tulos result_box-listaan."""
    for item in provider.stream_answer(system, documents, question, max_tokens):
        if isinstance(item, AiResult):
            result_box.append(item)
        elif item:
            yield StreamEvent("delta", item)
