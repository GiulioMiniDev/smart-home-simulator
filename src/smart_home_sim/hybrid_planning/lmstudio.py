from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from smart_home_sim.hybrid_planning.models import HybridPlanningConfig

ModelT = TypeVar("ModelT", bound=BaseModel)


class LMStudioError(RuntimeError):
    pass


def _extract_json_object(content: str) -> str:
    """Extract the first balanced JSON object from a free-form completion.

    Tolerates Markdown code fences and surrounding prose by scanning for the first
    ``{`` and returning up to its matching ``}`` (ignoring braces inside strings).
    """

    text = content.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    if start == -1:
        raise LMStudioError("no JSON object found in completion")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise LMStudioError("unterminated JSON object in completion")


@dataclass(frozen=True, slots=True)
class LMStudioExchange:
    request: dict[str, Any]
    api_response: dict[str, Any]
    raw_content: str


class LMStudioClient:
    def __init__(self, config: HybridPlanningConfig) -> None:
        self.config = config

    def complete_json(
        self,
        *,
        schema_name: str,
        output_model: type[ModelT],
        system_prompt: str,
        user_prompt: str,
        seed: int,
        schema_override: dict[str, Any] | None = None,
        enforce_schema: bool = True,
    ) -> tuple[ModelT, LMStudioExchange]:
        request_body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "seed": seed,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        if enforce_schema:
            # Constrained decoding against the full JSON schema. Reliable but slow for
            # large nested schemas; callers with big models may disable it and rely on
            # free-form JSON extraction plus deterministic validation instead.
            request_body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema_override or output_model.model_json_schema(by_alias=True),
                },
            }
        endpoint = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                api_response = json.loads(response.read().decode("utf-8"))
            content = api_response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("completion content is not text")
            if not content.strip():
                choice = api_response["choices"][0]
                raise LMStudioError(
                    "LM Studio returned empty content "
                    f"(finishReason={choice.get('finish_reason')}, "
                    f"usage={api_response.get('usage')})"
                )
            payload = content if enforce_schema else _extract_json_object(content)
            parsed = output_model.model_validate_json(payload)
        except urllib.error.URLError as error:
            raise LMStudioError(f"LM Studio is unavailable: {error}") from error
        except TimeoutError as error:
            raise LMStudioError("LM Studio request timed out") from error
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
        ) as error:
            raise LMStudioError(
                f"LM Studio returned an invalid structured response: {error}"
            ) from error
        return parsed, LMStudioExchange(request_body, api_response, content)
