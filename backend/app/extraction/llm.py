"""The model behind one interface.

Call sites depend on StructuredExtractor, never on a vendor SDK. Adding a
provider later (e.g. Gemini, paid tier only: the free tier's terms allow human
review of submitted content) is one class and one registry key; no call site
changes. FakeExtractor makes every API and mapping test zero-cost without
monkeypatching the SDK.
"""

import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from app.config import extraction_model

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ExtractionOutcome(Generic[T]):
    parsed: T | None  # None when the model refused or returned nothing usable
    refusal: str | None
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class StructuredExtractor(Protocol):
    name: str  # registry key, e.g. "openai:gpt-4o-mini"

    def extract(
        self, *, system_prompt: str, user_text: str, schema: type[T]
    ) -> ExtractionOutcome[T]: ...


class OpenAIExtractor:
    """chat.completions.parse with a strict JSON schema derived from `schema`.
    temperature 0 and a fixed seed for repeatability (not a determinism
    guarantee; the eval reports agreement if run twice)."""

    def __init__(self, model: str):
        self.model = model
        self.name = f"openai:{model}"

    def extract(
        self, *, system_prompt: str, user_text: str, schema: type[T]
    ) -> ExtractionOutcome[T]:
        from app.ingestion.embedder import _get_client  # one client factory, as chat

        start = time.monotonic()
        response = _get_client().chat.completions.parse(
            model=self.model,
            temperature=0,
            seed=0,
            messages=[
                {"role": "system", "content": system_prompt},
                # Separate user message: the description is data, not instructions.
                {"role": "user", "content": user_text},
            ],
            response_format=schema,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        message = response.choices[0].message
        usage = response.usage
        return ExtractionOutcome(
            parsed=message.parsed,
            refusal=message.refusal,
            model=self.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            latency_ms=latency_ms,
        )


class FakeExtractor:
    """Tests and offline runs: returns a canned object, records what it saw."""

    name = "fake"

    def __init__(self, parsed: BaseModel | None, refusal: str | None = None):
        self._parsed = parsed
        self._refusal = refusal
        self.calls: list[tuple[str, str]] = []

    def extract(
        self, *, system_prompt: str, user_text: str, schema: type[T]
    ) -> ExtractionOutcome[T]:
        self.calls.append((system_prompt, user_text))
        parsed = self._parsed
        if parsed is not None and not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed.model_dump())
        return ExtractionOutcome(
            parsed=parsed,  # type: ignore[arg-type]
            refusal=self._refusal,
            model=self.name,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
        )


def get_extractor(name: str | None = None) -> StructuredExtractor:
    """Resolve "<provider>:<model>" (default: config.extraction_model())."""
    key = name or extraction_model()
    provider, _, model = key.partition(":")
    if provider == "openai" and model:
        return OpenAIExtractor(model)
    raise ValueError(f"unknown extractor {key!r}; expected 'openai:<model>'")
