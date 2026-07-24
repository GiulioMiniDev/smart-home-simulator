"""Minimal OpenAI-compatible client for a local LM Studio endpoint.

The client favours free-form JSON output plus deterministic post-validation over constrained
``response_format`` decoding: on a small local model the constrained grammar over a large,
deeply nested schema is prohibitively slow, whereas free-form output with tolerant extraction
and an external repair loop reaches the same correctness far faster. Only the standard library
is used, so the runtime keeps no new dependency.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_MODEL = "qwen2.5-coder-7b-instruct"

# A transport turns a POST (url, body, timeout) into the response body text. It may raise the
# urllib errors below, which the client maps, or an ``LMStudioError`` directly. Injectable so the
# generators can be exercised deterministically without a live endpoint.
Transport = Callable[[str, bytes, float], str]


class LMStudioError(Exception):
    """Base class for every recoverable LM Studio failure."""


class LMStudioUnavailableError(LMStudioError):
    """The endpoint could not be reached, refused the connection, or timed out."""


class LMStudioResponseError(LMStudioError):
    """The endpoint answered but the HTTP status or response envelope was unusable."""


class LMStudioContentError(LMStudioError):
    """The model answered but no JSON object could be extracted from its content."""


@dataclass(frozen=True)
class LMStudioConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 8192
    timeout_seconds: float = 1800.0
    seed: int | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class LMStudioCompletion:
    """Raw textual completion plus the reproducible request and response envelopes."""

    content: str
    request: dict[str, Any]
    response: dict[str, Any]
    duration_seconds: float
    finish_reason: str | None
    usage: dict[str, Any] | None


@dataclass(frozen=True)
class LMStudioJSONCompletion(LMStudioCompletion):
    """A completion whose content was successfully parsed into a JSON value."""

    data: Any = field(default=None)


def _urllib_transport(url: str, body: bytes, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (local only)
        return response.read().decode("utf-8")


class LMStudioClient:
    """Thin OpenAI-compatible chat client for one local LM Studio model."""

    def __init__(self, config: LMStudioConfig | None = None, *, transport: Transport | None = None):
        self.config = config or LMStudioConfig()
        self._transport = transport or _urllib_transport

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> LMStudioCompletion:
        """Send one chat completion request and return its raw textual content."""
        request_body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.as_payload() for message in messages],
            "temperature": self.config.temperature if temperature is None else temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        effective_seed = self.config.seed if seed is None else seed
        if effective_seed is not None:
            request_body["seed"] = effective_seed

        payload = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        started = time.perf_counter()
        raw = self._post(payload)
        duration = round(time.perf_counter() - started, 3)

        try:
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            content = choice["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise LMStudioResponseError(
                f"Malformed LM Studio response envelope: {error}"
            ) from error
        if not isinstance(content, str):
            raise LMStudioResponseError("LM Studio response content was not text")

        return LMStudioCompletion(
            content=content,
            request=request_body,
            response=envelope,
            duration_seconds=duration,
            finish_reason=choice.get("finish_reason"),
            usage=envelope.get("usage"),
        )

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> LMStudioJSONCompletion:
        """Complete and extract the first JSON value, tolerating fences and surrounding prose."""
        completion = self.complete(
            messages, temperature=temperature, seed=seed, max_tokens=max_tokens
        )
        data = extract_json_value(completion.content)
        return LMStudioJSONCompletion(
            content=completion.content,
            request=completion.request,
            response=completion.response,
            duration_seconds=completion.duration_seconds,
            finish_reason=completion.finish_reason,
            usage=completion.usage,
            data=data,
        )

    def _post(self, payload: bytes) -> str:
        try:
            return self._transport(self.config.endpoint, payload, self.config.timeout_seconds)
        except urllib.error.HTTPError as error:
            raise LMStudioResponseError(
                f"LM Studio returned HTTP {error.code}: {error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise LMStudioUnavailableError(
                f"Cannot reach LM Studio at {self.config.endpoint}: {error}"
            ) from error


_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.IGNORECASE | re.DOTALL)


def extract_json_value(text: str) -> Any:
    """Extract the first JSON object or array from model text.

    Handles three common shapes a small model produces: a bare JSON document, a document wrapped
    in a ```json fenced block, and a document surrounded by explanatory prose. Raises
    :class:`LMStudioContentError` when no balanced JSON value is present.
    """
    for candidate in _json_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise LMStudioContentError("No JSON object or array found in model output")


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for region in _answer_regions(text):
        stripped = region.strip()
        if stripped:
            candidates.append(stripped)
        for match in _FENCE_PATTERN.finditer(region):
            body = match.group("body").strip()
            if body:
                candidates.append(body)
        balanced = _scan_balanced(region)
        if balanced is not None:
            candidates.append(balanced)
    return candidates


def _answer_regions(text: str) -> list[str]:
    """Prefer the answer after a reasoning model's final ``</think>``, then the whole text.

    Reasoning models (e.g. qwen3.5-9b) stream a ``<think>...</think>`` preamble before the answer.
    That preamble often contains braces, so the JSON must be sought after the final ``</think>``
    first; the whole text remains a fallback for non-reasoning models.
    """
    if "</think>" in text:
        return [text.rsplit("</think>", 1)[-1], text]
    return [text]


def _scan_balanced(text: str) -> str | None:
    """Return the first balanced ``{...}`` or ``[...]`` span, ignoring braces inside strings."""
    openers = {"{": "}", "[": "]"}
    start = next((index for index, char in enumerate(text) if char in openers), None)
    if start is None:
        return None
    opener = text[start]
    closer = openers[opener]
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
