from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import smart_home_sim.validation.service as service
from smart_home_sim.validation.service import validate_file, validate_payload


def test_missing_file_is_reported(tmp_path: Path) -> None:
    report = validate_file(tmp_path / "missing.json")

    assert {item.code for item in report.issues} == {"FILE_NOT_FOUND"}


def test_os_read_error_is_reported(tmp_path: Path) -> None:
    report = validate_file(tmp_path)

    assert {item.code for item in report.issues} == {"FILE_READ_ERROR"}


def test_size_limit_is_checked_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(service, "MAX_SCENARIO_BYTES", 1)

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"FILE_TOO_LARGE"}
    assert report.issues[0].details == {"sizeBytes": 2, "limitBytes": 1}


def test_non_utf8_input_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "invalid-utf8.json"
    path.write_bytes(b"{\xff}")

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"FILE_ENCODING_ERROR"}
    assert report.issues[0].details["byteOffset"] == 1


def test_duplicate_json_keys_are_not_silently_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schemaVersion":"1.0.0","schemaVersion":"1.0.0"}', encoding="utf-8")

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"DUPLICATE_JSON_KEY"}
    assert report.issues[0].details["key"] == "schemaVersion"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(tmp_path: Path, constant: str) -> None:
    path = tmp_path / "constant.json"
    path.write_text(f'{{"value":{constant}}}', encoding="utf-8")

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"JSON_SYNTAX"}


def test_json_syntax_location_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "syntax.json"
    path.write_text('{"schemaVersion":', encoding="utf-8")

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"JSON_SYNTAX"}
    assert report.issues[0].details == {"line": 1, "column": 18}


def test_excessive_json_nesting_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "nested.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")

    report = validate_file(path)

    assert {item.code for item in report.issues} == {"JSON_NESTING_TOO_DEEP"}


def test_brackets_inside_json_strings_do_not_count_as_nesting(
    tmp_path: Path,
    valid_payload: dict[str, Any],
) -> None:
    valid_payload["title"] = "[" * 300
    path = tmp_path / "brackets-in-string.json"
    path.write_text(json.dumps(valid_payload), encoding="utf-8")

    assert validate_file(path).valid


def test_payload_must_be_an_object() -> None:
    report = validate_payload([])

    assert {item.code for item in report.issues} == {"STRUCTURE_INVALID"}


@pytest.mark.parametrize("version", [None, "0.1.0", 1])
def test_unsupported_or_missing_version_fails_fast(version: object) -> None:
    report = validate_payload({"schemaVersion": version})

    assert {item.code for item in report.issues} == {"UNSUPPORTED_SCHEMA_VERSION"}
