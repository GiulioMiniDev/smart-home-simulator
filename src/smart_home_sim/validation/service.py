from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.report import ValidationIssue, ValidationReport
from smart_home_sim.validation.issues import issue
from smart_home_sim.validation.rules import validate_rules

SUPPORTED_SCHEMA_VERSION = "1.0.0"
MAX_SCENARIO_BYTES = 50 * 1024 * 1024
MAX_JSON_NESTING = 256


class DuplicateJsonKeyError(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


class InvalidJsonConstantError(ValueError):
    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(value)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> None:
    raise InvalidJsonConstantError(value)


def _exceeds_json_nesting_limit(raw: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for character in raw:
        if escaped:
            escaped = False
        elif in_string and character == "\\":
            escaped = True
        elif character == '"':
            in_string = not in_string
        elif not in_string and character in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING:
                return True
        elif not in_string and character in "]}":
            depth -= 1
    return False


def _json_path(location: tuple[Any, ...]) -> str:
    result = "$"
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def _structure_report(
    error: ValidationError,
    schema_version: str | None = None,
    scenario_id: str | None = None,
) -> ValidationReport:
    issues = [
        issue(
            "STRUCTURE_INVALID",
            "structure",
            _json_path(item["loc"]),
            item["msg"],
            details={"type": item["type"]},
        )
        for item in error.errors(include_url=False, include_context=False, include_input=False)
    ]
    return ValidationReport.from_issues(
        issues,
        schema_version=schema_version,
        scenario_id=scenario_id,
    )


def validate_file(path: Path) -> ValidationReport:
    try:
        encoded = path.read_bytes()
    except FileNotFoundError:
        return ValidationReport.from_issues(
            [issue("FILE_NOT_FOUND", "structure", "$", f"Scenario file not found: {path}")]
        )
    except OSError as error:
        return ValidationReport.from_issues(
            [issue("FILE_READ_ERROR", "structure", "$", f"Cannot read scenario: {error}")]
        )

    if len(encoded) > MAX_SCENARIO_BYTES:
        return ValidationReport.from_issues(
            [
                issue(
                    "FILE_TOO_LARGE",
                    "structure",
                    "$",
                    f"Scenario exceeds the {MAX_SCENARIO_BYTES}-byte input limit.",
                    details={"sizeBytes": len(encoded), "limitBytes": MAX_SCENARIO_BYTES},
                )
            ]
        )

    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        return ValidationReport.from_issues(
            [
                issue(
                    "FILE_ENCODING_ERROR",
                    "structure",
                    "$",
                    "Scenario is not valid UTF-8.",
                    details={"byteOffset": error.start},
                )
            ]
        )

    if _exceeds_json_nesting_limit(raw):
        return ValidationReport.from_issues(
            [
                issue(
                    "JSON_NESTING_TOO_DEEP",
                    "structure",
                    "$",
                    f"JSON nesting exceeds the limit of {MAX_JSON_NESTING} levels.",
                    details={"limit": MAX_JSON_NESTING},
                )
            ]
        )

    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except DuplicateJsonKeyError as error:
        return ValidationReport.from_issues(
            [
                issue(
                    "DUPLICATE_JSON_KEY",
                    "structure",
                    "$",
                    f"JSON object repeats key '{error.key}'.",
                    details={"key": error.key},
                )
            ]
        )
    except InvalidJsonConstantError as error:
        return ValidationReport.from_issues(
            [
                issue(
                    "JSON_SYNTAX",
                    "structure",
                    "$",
                    f"Non-finite JSON number '{error.value}' is not allowed.",
                    details={"constant": error.value},
                )
            ]
        )
    except RecursionError:
        return ValidationReport.from_issues(
            [
                issue(
                    "JSON_NESTING_TOO_DEEP",
                    "structure",
                    "$",
                    "JSON nesting exceeds the parser's safe recursion depth.",
                )
            ]
        )
    except json.JSONDecodeError as error:
        return ValidationReport.from_issues(
            [
                issue(
                    "JSON_SYNTAX",
                    "structure",
                    "$",
                    f"Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}",
                    details={"line": error.lineno, "column": error.colno},
                )
            ]
        )
    return validate_payload(payload)


def validate_payload(payload: Any) -> ValidationReport:
    if not isinstance(payload, dict):
        return ValidationReport.from_issues(
            [issue("STRUCTURE_INVALID", "structure", "$", "Scenario must be a JSON object.")]
        )

    schema_version = payload.get("schemaVersion")
    scenario_id = payload.get("scenarioId")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        return ValidationReport.from_issues(
            [
                issue(
                    "UNSUPPORTED_SCHEMA_VERSION",
                    "structure",
                    "$.schemaVersion",
                    f"Expected schemaVersion '{SUPPORTED_SCHEMA_VERSION}', got '{schema_version}'.",
                )
            ],
            schema_version=str(schema_version) if schema_version is not None else None,
            scenario_id=str(scenario_id) if scenario_id is not None else None,
        )

    try:
        scenario = Scenario.model_validate_json(json.dumps(payload, separators=(",", ":")))
    except ValidationError as error:
        return _structure_report(
            error,
            schema_version=schema_version,
            scenario_id=scenario_id if isinstance(scenario_id, str) else None,
        )
    return validate_scenario(scenario)


def validate_scenario(scenario: Scenario) -> ValidationReport:
    issues: list[ValidationIssue] = validate_rules(scenario)
    return ValidationReport.from_issues(
        sorted(
            issues,
            key=lambda item: (
                item.path,
                item.code,
                item.message,
                json.dumps(item.details, sort_keys=True),
            ),
        ),
        schema_version=scenario.schema_version,
        scenario_id=scenario.scenario_id,
    )
