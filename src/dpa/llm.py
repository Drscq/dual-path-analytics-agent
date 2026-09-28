"""LLM access behind one small async interface, plus a scripted fake for tests."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    async def generate(
        self, *, model: str, system: str, prompt: str, json_mode: bool = False
    ) -> LLMResponse:
        """One non-streaming completion. json_mode asks the model for a bare JSON object."""
        ...


class GeminiClient:
    """Real client over the google-genai SDK. Temperature 0 so runs are comparable."""

    def __init__(self, api_key: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)

    async def generate(
        self, *, model: str, system: str, prompt: str, json_mode: bool = False
    ) -> LLMResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json" if json_mode else None,
            # We never pass tools; turning AFC off keeps the call a single round trip.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        start = time.perf_counter()
        resp = await self._client.aio.models.generate_content(
            model=model, contents=prompt, config=config
        )
        latency_ms = (time.perf_counter() - start) * 1000
        usage = resp.usage_metadata
        return LLMResponse(
            text=resp.text or "",
            latency_ms=latency_ms,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            # Thinking tokens are billed as output, so count them here.
            output_tokens=(
                (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if usage else 0
            ),
        )


# --- fake ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """Reply `text` to calls whose model equals `model` (if set) and whose prompt contains
    `contains` (if set), after sleeping `delay_s`."""

    text: str
    model: str | None = None
    contains: str | None = None
    delay_s: float = 0.0


@dataclass(frozen=True)
class Call:
    model: str
    system: str
    prompt: str
    json_mode: bool


class NoMatchingRule(AssertionError):
    pass


@dataclass
class FakeLLM:
    """Deterministic LLMClient for tests: first matching rule wins; every call is recorded."""

    rules: list[Rule]
    calls: list[Call] = field(default_factory=list)

    async def generate(
        self, *, model: str, system: str, prompt: str, json_mode: bool = False
    ) -> LLMResponse:
        self.calls.append(Call(model, system, prompt, json_mode))
        for rule in self.rules:
            if rule.model is not None and rule.model != model:
                continue
            if rule.contains is not None and rule.contains not in prompt:
                continue
            start = time.perf_counter()
            if rule.delay_s:
                await asyncio.sleep(rule.delay_s)
            return LLMResponse(text=rule.text, latency_ms=(time.perf_counter() - start) * 1000)
        raise NoMatchingRule(f"no rule for model={model!r}, prompt starts {prompt[:80]!r}")
