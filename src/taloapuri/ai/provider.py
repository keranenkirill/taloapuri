"""Tekoälypalvelun adapteri. Sovellus ei riipu suoraan mallintoimittajasta.

Tekoälyllä ei ole työkaluja eikä sivuvaikutuksia: se saa vain kysymyksen ja julkiset lakitekstit
ja palauttaa tekstin lähdeviitteineen. Testit käyttävät FakeProvideria (ei maksullisia kutsuja).
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
from anthropic.types import ContentBlockParam, MessageParam, TextBlockParam

from taloapuri.config import Settings


@dataclass(frozen=True)
class AiDocument:
    """Yksi pykälä; jokainen momentti on oma lohkonsa (viitteet kohdistuvat momentteihin)."""

    title: str
    context: str
    blocks: list[str]


@dataclass(frozen=True)
class AiCitation:
    document_index: int
    start_block_index: int
    end_block_index: int  # ei sisälly
    cited_text: str


@dataclass(frozen=True)
class AiSegment:
    text: str
    citations: list[AiCitation] = field(default_factory=list)


@dataclass
class AiResult:
    segments: list[AiSegment]
    stop_reason: str | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None


class AiUnavailable(Exception):
    """Tekoälypalvelu ei vastannut. `reason` tallennetaan ai_runs-tauluun (ei henkilötietoja)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


StreamItem = str | AiResult  # tekstipala tai lopuksi koko tulos


class AiProvider(Protocol):
    def answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> AiResult: ...

    def stream_answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> Iterator[StreamItem]:
        """Tuottaa tekstipaloja sitä mukaa kuin ne syntyvät ja lopuksi koko AiResultin."""
        ...


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "authentication"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(exc, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection"
    if isinstance(exc, anthropic.APIStatusError):
        return f"status_{exc.status_code}"
    return "error"


_SDK_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.APIStatusError,
)


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Avain tulee asetuksista (.env / ANTHROPIC_API_KEY); sitä ei tallenneta eikä lokiteta.
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.ai_timeout_seconds,
            max_retries=2,
        )

    def _request(
        self, system: str, documents: list[AiDocument], question: str, max_tokens: int | None
    ) -> dict[str, Any]:
        content: list[ContentBlockParam] = [
            {
                "type": "document",
                "source": {
                    "type": "content",
                    "content": [{"type": "text", "text": block} for block in doc.blocks],
                },
                "title": doc.title,
                "context": doc.context,
                "citations": {"enabled": True},
            }
            for doc in documents
        ]
        content.append({"type": "text", "text": question})
        # Pysyvä järjestelmäkehote välimuistiin (jää välimuistin ulkopuolelle, jos lyhyt).
        system_blocks: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        messages: list[MessageParam] = [{"role": "user", "content": content}]
        return {
            "model": self._settings.ai_model,
            "max_tokens": max_tokens or self._settings.ai_max_output_tokens,
            "system": system_blocks,
            "output_config": {"effort": self._settings.ai_effort},
            "messages": messages,
        }

    @staticmethod
    def _to_result(response: Any, latency_ms: int) -> AiResult:
        segments: list[AiSegment] = []
        for block in response.content:
            if block.type != "text":
                continue  # ajattelulohkoja ei näytetä käyttäjälle
            citations = [
                AiCitation(
                    document_index=c.document_index,
                    start_block_index=c.start_block_index,
                    end_block_index=c.end_block_index,
                    cited_text=c.cited_text,
                )
                for c in (block.citations or [])
                if c.type == "content_block_location"
            ]
            segments.append(AiSegment(text=block.text, citations=citations))
        usage = response.usage
        return AiResult(
            segments=segments,
            stop_reason=response.stop_reason,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            latency_ms=latency_ms,
            request_id=getattr(response, "_request_id", None),
        )

    def answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> AiResult:
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                **self._request(system, documents, question, max_tokens)
            )
        except _SDK_ERRORS as exc:
            raise AiUnavailable(_error_reason(exc)) from exc
        return self._to_result(response, int((time.monotonic() - started) * 1000))

    def stream_answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> Iterator[StreamItem]:
        """Anthropicin striimaus: tekstipalat heti, lopullinen viesti (viitteineen) lopuksi."""
        started = time.monotonic()
        try:
            with self._client.messages.stream(
                **self._request(system, documents, question, max_tokens)
            ) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
        except _SDK_ERRORS as exc:
            raise AiUnavailable(_error_reason(exc)) from exc
        yield self._to_result(final, int((time.monotonic() - started) * 1000))


@dataclass
class FakeProvider:
    """Testeihin: palauttaa ennalta määritellyn vastauksen ja tallentaa saamansa syötteen."""

    result: AiResult | None = None
    error: AiUnavailable | None = None
    calls: list[tuple[str, list[AiDocument], str]] = field(default_factory=list)

    def answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> AiResult:
        self.calls.append((system, documents, question))
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        first = documents[0]
        return AiResult(
            segments=[
                AiSegment("Lyhyesti: "),
                AiSegment(
                    "vastuu jakautuu lain mukaan",
                    [AiCitation(0, 0, 1, first.blocks[0])],
                ),
                AiSegment(". Epävarmaa – tarkista: yhtiöjärjestys voi määrätä toisin."),
            ],
            stop_reason="end_turn",
            model="fake-model",
            input_tokens=1000,
            output_tokens=200,
        )

    def stream_answer(
        self,
        system: str,
        documents: list[AiDocument],
        question: str,
        max_tokens: int | None = None,
    ) -> Iterator[StreamItem]:
        """Pilkkoo answer()-tuloksen paloiksi kuten oikea striimi."""
        result = self.answer(system, documents, question, max_tokens)
        for segment in result.segments:
            for i in range(0, len(segment.text), 12):
                yield segment.text[i : i + 12]
        yield result
