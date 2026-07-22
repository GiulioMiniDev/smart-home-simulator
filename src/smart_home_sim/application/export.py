from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import XMLGenerator

import ijson

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    ExportFormat,
    ExportManifest,
    ExportManifestFile,
    ExportRequest,
    utc_now,
)

ROLE_SOURCES: dict[str, tuple[str, str]] = {
    "observable": ("observable_sensor_log", "records.item"),
    "oracle": ("oracle_mapping", "links.item"),
    "activities": ("execution_trace", "activityExecutions.item"),
    "actions": ("execution_trace", "actionExecutions.item"),
    "movements": ("execution_trace", "movements.item"),
    "state_transitions": ("execution_trace", "stateTransitions.item"),
    "resources": ("execution_trace", "resourceEvents.item"),
    "runtime_events": ("execution_trace", "runtimeEvents.item"),
    "plan_deviations": ("execution_trace", "planDeviations.item"),
    "final_state": ("execution_trace", "finalState"),
}

TIME_FIELDS = (
    "observedAt",
    "actualStart",
    "startedAt",
    "at",
    "evaluatedAt",
    "plannedStart",
)


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _items(path: Path, prefix: str) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        for item in ijson.items(handle, prefix, use_float=True):
            if not isinstance(item, dict):
                raise WorkspaceError(f"export source '{prefix}' is not a record sequence")
            yield item


def _metadata(path: Path, name: str) -> Any:
    with path.open("rb") as handle:
        return next(ijson.items(handle, name, use_float=True), None)


def _record_time(record: dict[str, Any]) -> datetime | None:
    for name in TIME_FIELDS:
        value = record.get(name)
        if isinstance(value, str):
            return datetime.fromisoformat(value)
    return None


def _filtered(
    records: Iterable[dict[str, Any]], request: ExportRequest
) -> Iterator[dict[str, Any]]:
    for record in records:
        at = _record_time(record)
        if at is not None and request.include_start and at < request.include_start:
            continue
        if at is not None and request.include_end and at > request.include_end:
            continue
        yield record


def _jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return count


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _csv(path: Path, records: Iterable[dict[str, Any]]) -> int:
    iterator = iter(records)
    first = next(iterator, None)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if first is None:
            return 0
        fields = list(first)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerow({key: _csv_value(first.get(key)) for key in fields})
        count = 1
        for record in iterator:
            if set(record) != set(fields):
                raise WorkspaceError("CSV records do not have a stable field set")
            writer.writerow({key: _csv_value(record.get(key)) for key in fields})
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return count


def _xes_attribute(xml: XMLGenerator, key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        tag = "boolean"
        rendered = "true" if value else "false"
    elif isinstance(value, (int, float)):
        tag = "float"
        rendered = str(value)
    elif key in TIME_FIELDS and isinstance(value, str):
        tag = "date"
        rendered = value
    else:
        tag = "string"
        rendered = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value)
        )
    xml.startElement(tag, {"key": key, "value": rendered})
    xml.endElement(tag)


def _xes(path: Path, role: str, records: Iterable[dict[str, Any]], run_id: str) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        xml = XMLGenerator(handle, encoding="utf-8", short_empty_elements=True)
        xml.startDocument()
        xml.startElement(
            "log",
            {
                "xes.version": "1.0",
                "xes.features": "nested-attributes",
                "xmlns": "http://www.xes-standard.org/",
            },
        )
        _xes_attribute(xml, "concept:name", f"{run_id}:{role}")
        xml.startElement("trace", {})
        _xes_attribute(xml, "concept:name", run_id)
        count = 0
        for record in records:
            xml.startElement("event", {})
            event_name = next(
                (
                    record[name]
                    for name in ("intent", "actionType", "measurement", "operation", "kind")
                    if record.get(name) is not None
                ),
                role,
            )
            _xes_attribute(xml, "concept:name", event_name)
            for key, value in record.items():
                _xes_attribute(xml, key, value)
            xml.endElement("event")
            count += 1
        xml.endElement("trace")
        xml.endElement("log")
        xml.endDocument()
        handle.flush()
        os.fsync(handle.fileno())
    return count


class ExportService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace

    def export(self, request: ExportRequest) -> ExportManifest:
        artifacts = self.workspace.run_artifacts(request.run_id)
        bundle = artifacts.get("simulation_bundle")
        trace = artifacts.get("execution_trace")
        if bundle is None or trace is None:
            raise WorkspaceError("a reproducible export requires bundle and execution trace")
        trace_path = self.workspace.artifact_path(trace.artifact_id)
        source_bundle_sha256 = _metadata(trace_path, "sourceBundleSha256")
        trace_digest = _metadata(trace_path, "semanticDigest")
        seed = _metadata(trace_path, "seed")
        if not isinstance(source_bundle_sha256, str) or not isinstance(trace_digest, str):
            raise WorkspaceError("execution trace provenance is incomplete")
        if not isinstance(seed, int):
            raise WorkspaceError("execution trace seed is invalid")
        export_id = f"export_{uuid4().hex[:16]}"
        target = self.workspace.exports_path / export_id
        staging = Path(tempfile.mkdtemp(prefix=f".{export_id}.", dir=self.workspace.exports_path))
        files: list[ExportManifestFile] = []
        try:
            for role in request.roles:
                artifact_role, prefix = ROLE_SOURCES[role]
                source = artifacts.get(artifact_role)
                if source is None:
                    raise WorkspaceError(f"run has no artifact required for '{role}' export")
                source_path = self.workspace.artifact_path(source.artifact_id)
                for output_format in request.formats:
                    output = staging / f"{role}.{output_format.value}"
                    records = _filtered(_items(source_path, prefix), request)
                    if output_format is ExportFormat.jsonl:
                        count = _jsonl(output, records)
                        media_type = "application/x-ndjson"
                    elif output_format is ExportFormat.csv:
                        count = _csv(output, records)
                        media_type = "text/csv"
                    else:
                        count = _xes(output, role, records, request.run_id)
                        media_type = "application/xml"
                    files.append(
                        ExportManifestFile(
                            role=role,
                            format=output_format,
                            relative_path=f"{export_id}/{output.name}",
                            media_type=media_type,
                            record_count=count,
                            size_bytes=output.stat().st_size,
                            sha256=_digest(output),
                        )
                    )
            manifest = ExportManifest(
                export_id=export_id,
                run_id=request.run_id,
                source_bundle_sha256=source_bundle_sha256,
                source_trace_semantic_digest=trace_digest,
                seed=seed,
                created_at=utc_now(),
                files=files,
            )
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(
                manifest.model_dump_json(by_alias=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            staging.replace(target)
            for item in files:
                path = self.workspace.exports_path / item.relative_path
                self.workspace.register_artifact(
                    path,
                    role=f"export_{item.role}_{item.format.value}",
                    media_type=item.media_type,
                    run_id=request.run_id,
                )
            manifest_artifact = self.workspace.register_artifact(
                target / "manifest.json",
                role="export_manifest",
                media_type="application/json",
                schema_version="1.0.0",
                run_id=request.run_id,
            )
            with self.workspace.transaction() as connection:
                connection.execute(
                    """INSERT INTO exports(
                        export_id, run_id, request_json, manifest_artifact_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        export_id,
                        request.run_id,
                        request.model_dump_json(by_alias=True),
                        manifest_artifact.artifact_id,
                        manifest.created_at.isoformat(),
                    ),
                )
            return manifest
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise

    def verify_manifest(self, export_id: str) -> ExportManifest:
        directory = (self.workspace.exports_path / export_id).resolve()
        if directory.parent != self.workspace.exports_path.resolve():
            raise WorkspaceError("export identifier escapes the workspace")
        manifest_path = directory / "manifest.json"
        try:
            manifest = ExportManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WorkspaceError(f"cannot read export manifest: {error}") from error
        for item in manifest.files:
            path = (self.workspace.exports_path / item.relative_path).resolve()
            try:
                path.relative_to(directory)
            except ValueError as error:
                raise WorkspaceError("export manifest contains an unsafe path") from error
            if (
                not path.is_file()
                or path.stat().st_size != item.size_bytes
                or _digest(path) != item.sha256
            ):
                raise WorkspaceError(f"export file '{item.relative_path}' failed integrity checks")
        return manifest
