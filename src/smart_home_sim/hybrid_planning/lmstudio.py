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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema_override or output_model.model_json_schema(by_alias=True),
                },
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
            parsed = output_model.model_validate_json(content)
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
