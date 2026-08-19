from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
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
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.profile import ResidentProfile
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.profiling import (
    profile_from_trace_file,
    render_profile_html,
    write_heatmap_csv,
)
from smart_home_sim.summary import ScenarioFacts, SummaryInputs, render_summary_html

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
    # Outline-first horizons carry their habit bands in the scenario, because the application
    # never sees the outline they came from. One row per band, with the activity mix measured
    # across the horizon: the answer sheet for a segmentation algorithm.
    "habit_ground_truth": ("scenario", "extensions.habitGroundTruth.habits.item"),
}

# The one role that is computed rather than projected. It reads the execution trace and answers a
# question no row of it can: what is this resident like. Its files do not follow the requested
# formats — a profile is a document, a page and a matrix — so it takes its own path through the
# export.
PROFILE_ROLE = "resident_profile"

# The second computed role, and the only one that reads artifacts no other role touches: the home
# model, the sensor model and the scenario never leave the workspace otherwise, so a researcher
# holding an export has the readings of a sensor field they cannot see. It is built last, because
# part of what it publishes is the index of everything else in the export.
SUMMARY_ROLE = "summary"

COMPUTED_ROLES = frozenset({PROFILE_ROLE, SUMMARY_ROLE})

# Fields the pipeline keeps internally but must not publish, by export role.
#
# `quality` says whether the noise model disturbed a reading. It is legitimate inside the
# simulator — the replay view uses it — but no real sensor log contains a column declaring which
# of its own readings are unreliable. Shipping it in the observable half hands the evaluator part
# of the answer: on one eight month run, 27.7% of readings arrived pre-labelled as noisy. It stays
# in `observable-sensor-log.json`, whose 1.0.0 contract is frozen and whose consumers rely on it,
# and is withheld from the dataset a researcher receives. The oracle keeps carrying the causal
# story, which is where an admission of noise belongs.
WITHHELD_FIELDS: dict[str, frozenset[str]] = {
    "observable": frozenset({"quality"}),
}

TIME_FIELDS = (
    "observedAt",
    "actualStart",
    "startedAt",
    "at",
    "evaluatedAt",
    "plannedStart",
)

# Rendered as `<date>` in XES rather than `<string>`. A superset of TIME_FIELDS, which cannot grow
# to hold the closing timestamps: `_record_time` takes the first match as *the* time of a record,
# so adding `actualEnd` there would silently change which records a windowed export keeps.
DATE_FIELDS = frozenset(TIME_FIELDS) | {
    "actualEnd",
    "endedAt",
    "plannedEnd",
    "time:timestamp",
}

XES_EXTENSIONS = (
    ("Concept", "concept", "http://www.xes-standard.org/concept.xesext"),
    ("Time", "time", "http://www.xes-standard.org/time.xesext"),
    ("Lifecycle", "lifecycle", "http://www.xes-standard.org/lifecycle.xesext"),
    ("Organizational", "org", "http://www.xes-standard.org/org.xesext"),
)

XES_CLASSIFIERS = (
    ("Activity", "concept:name"),
    ("Activity and transition", "concept:name lifecycle:transition"),
)


@dataclass(frozen=True)
class XesProfile:
    """How one export role becomes an XES event stream.

    The three keys a process miner actually reads — `concept:name`, `time:timestamp`,
    `lifecycle:transition` — are not in the data under those names, so each role has to say which
    of its own fields play those parts. Getting this wrong does not produce an invalid file, it
    produces a valid file that no algorithm can learn anything from, which is worse because the
    tool opens it without complaining.
    """

    name_fields: tuple[str, ...]
    start_fields: tuple[str, ...]
    end_fields: tuple[str, ...] = ()
    instance_fields: tuple[str, ...] = ()
    resource_fields: tuple[str, ...] = ()


# Roles whose shape has not been pinned down — the ones a run often leaves empty. Ordered guesses,
# so that an unexpected role still exports something a miner can open.
GENERIC_PROFILE = XesProfile(
    name_fields=("intent", "actionType", "kind", "fact", "operation", "measurement"),
    start_fields=TIME_FIELDS,
    end_fields=("actualEnd", "endedAt"),
    instance_fields=("activityExecutionId", "actionExecutionId", "movementId", "transitionId"),
    resource_fields=("actorId", "subjectId"),
)

XES_PROFILES: dict[str, XesProfile] = {
    "observable": XesProfile(
        # Named after the sensor, not after `measurement`. Across a ninety-three day export the
        # latter takes three values — motion, temperature, contact — so it collapses 72k PIR
        # firings into a single activity and hands a miner a log with nothing to discover. The
        # sensor is the unit of observable behaviour here, exactly as M003 is in CASAS Aruba.
        name_fields=("sensorId",),
        start_fields=("observedAt",),
        instance_fields=("observationId",),
    ),
    "activities": XesProfile(
        name_fields=("intent",),
        start_fields=("actualStart", "plannedStart"),
        end_fields=("actualEnd",),
        instance_fields=("activityExecutionId",),
        resource_fields=("actorId",),
    ),
    "actions": XesProfile(
        name_fields=("actionType",),
        start_fields=("startedAt",),
        end_fields=("endedAt",),
        instance_fields=("actionExecutionId",),
        resource_fields=("actorId",),
    ),
    "movements": XesProfile(
        # Where the resident arrived: a trajectory log whose events are all called `move_to`
        # describes no trajectory.
        name_fields=("destinationRegionId",),
        start_fields=("startedAt",),
        end_fields=("endedAt",),
        instance_fields=("movementId",),
        resource_fields=("actorId",),
    ),
    "state_transitions": XesProfile(
        name_fields=("fact",),
        start_fields=("at",),
        instance_fields=("transitionId",),
        resource_fields=("subjectId",),
    ),
}


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
    records: Iterable[dict[str, Any]], request: ExportRequest, role: str = ""
) -> Iterator[dict[str, Any]]:
    withheld = WITHHELD_FIELDS.get(role, frozenset())
    for record in records:
        at = _record_time(record)
        if at is not None and request.include_start and at < request.include_start:
            continue
        if at is not None and request.include_end and at > request.include_end:
            continue
        yield (
            {key: value for key, value in record.items() if key not in withheld}
            if withheld
            else record
        )


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
    elif key in DATE_FIELDS and isinstance(value, str):
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


def _field(record: dict[str, Any], fields: Iterable[str]) -> Any:
    for name in fields:
        value = record.get(name)
        if value is not None and value != "":
            return value
    return None


def _xes_moments(record: dict[str, Any], profile: XesProfile) -> list[tuple[str, str]]:
    """The one or two XES events a record becomes, as (timestamp, lifecycle transition).

    A record that spans an interval becomes the standard pair, because that is the only encoding
    the tooling understands: `sessionSegmentation.py` in the activity-segmentation reference reads
    `lifecycle:transition` directly and pairs each `start` with the `complete` that follows it.
    A closing timestamp equal to the opening one is a point in time wearing an interval's clothes,
    and emitting the pair for it would invent a duration the simulator never produced.
    """
    start = _field(record, profile.start_fields)
    if not isinstance(start, str):
        return []
    end = _field(record, profile.end_fields)
    if isinstance(end, str) and end != start:
        return [(start, "start"), (end, "complete")]
    return [(start, "complete")]


def _xes_event(
    xml: XMLGenerator,
    record: dict[str, Any],
    profile: XesProfile,
    role: str,
    moment: tuple[str, str] | None,
) -> None:
    xml.startElement("event", {})
    _xes_attribute(xml, "concept:name", _field(record, profile.name_fields) or role)
    _xes_attribute(xml, "concept:instance", _field(record, profile.instance_fields))
    if moment is not None:
        _xes_attribute(xml, "time:timestamp", moment[0])
        _xes_attribute(xml, "lifecycle:transition", moment[1])
    _xes_attribute(xml, "org:resource", _field(record, profile.resource_fields))
    for key, value in record.items():
        _xes_attribute(xml, key, value)
    xml.endElement("event")


def _xes_header(xml: XMLGenerator, role: str, run_id: str) -> None:
    xml.startElement(
        "log",
        {
            "xes.version": "1.0",
            "xes.features": "nested-attributes",
            "xmlns": "http://www.xes-standard.org/",
        },
    )
    # Order is fixed by the standard: extensions, globals, classifiers, attributes, traces.
    for name, prefix, uri in XES_EXTENSIONS:
        xml.startElement("extension", {"name": name, "prefix": prefix, "uri": uri})
        xml.endElement("extension")
    xml.startElement("global", {"scope": "trace"})
    _xes_attribute(xml, "concept:name", "__INVALID__")
    xml.endElement("global")
    xml.startElement("global", {"scope": "event"})
    _xes_attribute(xml, "concept:name", "__INVALID__")
    _xes_attribute(xml, "time:timestamp", "1970-01-01T00:00:00+00:00")
    _xes_attribute(xml, "lifecycle:transition", "complete")
    xml.endElement("global")
    for name, keys in XES_CLASSIFIERS:
        xml.startElement("classifier", {"name": name, "keys": keys})
        xml.endElement("classifier")
    _xes_attribute(xml, "concept:name", f"{run_id}:{role}")
    _xes_attribute(xml, "lifecycle:model", "standard")


def _xes(path: Path, role: str, records: Iterable[dict[str, Any]], run_id: str) -> int:
    """One XES log, one trace per calendar day.

    The case notion is the day, which is what makes the file usable at all. Everything used to go
    into a single trace named after the run: valid XES, and worthless, because a log with one case
    has no variants to compare and the Inductive Miner returns the input back as a straight line.
    Habit segmentation in particular works by contrasting how different days behave in the same
    slot of the clock, so the day has to be the case.

    Days are cut at local midnight. A record that opens before midnight and closes after it stays
    whole, in the trace of the day it opened — a case should not be torn in half mid-activity.
    Habits that straddle midnight are handled downstream, where the discretisation algorithm
    already treats the twenty-four hours as a circle and merges the last slot with the first.

    The returned count is records consumed, not events written, so that the manifest agrees across
    formats. An interval record contributes two events to the file and one to this number.
    """
    profile = XES_PROFILES.get(role, GENERIC_PROFILE)
    iterator = iter(records)
    first = next(iterator, None)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        xml = XMLGenerator(handle, encoding="utf-8", short_empty_elements=True)
        xml.startDocument()
        _xes_header(xml, role, run_id)
        count = 0
        if first is not None:
            count = (
                _xes_dated_traces(xml, chain([first], iterator), profile, role)
                if _xes_moments(first, profile)
                # No timestamp anywhere in the record: the role is a join table (`oracle`) or a
                # snapshot (`final_state`), not a log. There is no day to cut it into, so it keeps
                # the old single-trace shape and simply carries no Time extension values.
                else _xes_undated_trace(xml, chain([first], iterator), profile, role, run_id)
            )
        xml.endElement("log")
        xml.endDocument()
        handle.flush()
        os.fsync(handle.fileno())
    return count


def _xes_undated_trace(
    xml: XMLGenerator,
    records: Iterable[dict[str, Any]],
    profile: XesProfile,
    role: str,
    run_id: str,
) -> int:
    xml.startElement("trace", {})
    _xes_attribute(xml, "concept:name", run_id)
    count = 0
    for record in records:
        _xes_event(xml, record, profile, role, None)
        count += 1
    xml.endElement("trace")
    return count


def _xes_dated_traces(
    xml: XMLGenerator,
    records: Iterable[dict[str, Any]],
    profile: XesProfile,
    role: str,
) -> int:
    """Write one trace per day, buffering a single day at a time.

    Buffering is unavoidable: an interval record emits its `complete` after events that opened
    later, so a trace can only be ordered once the day is closed. It is bounded by a day's records
    — roughly 1,300 for an observable log — not by the export, which runs to millions.
    """
    count = 0
    current: str | None = None
    closed: set[str] = set()
    buffer: list[tuple[datetime, int, int, tuple[str, str], dict[str, Any]]] = []
    for record in records:
        moments = _xes_moments(record, profile)
        if not moments:
            raise WorkspaceError(f"export role '{role}' has records with and without a timestamp")
        day = datetime.fromisoformat(moments[0][0]).date().isoformat()
        if day != current:
            if current is not None:
                _xes_flush(xml, current, buffer, profile, role)
                buffer = []
                closed.add(current)
            # The sources are written in chronological order and the day is derived from that
            # order, so a day coming back after it was closed means the ordering assumption this
            # function rests on is broken. Failing beats writing a log with two traces per day.
            if day in closed:
                raise WorkspaceError(f"export role '{role}' is not in chronological order")
            current = day
        for index, moment in enumerate(moments):
            buffer.append((datetime.fromisoformat(moment[0]), count, index, moment, record))
        count += 1
    if current is not None:
        _xes_flush(xml, current, buffer, profile, role)
    return count


def _xes_flush(
    xml: XMLGenerator,
    day: str,
    buffer: list[tuple[datetime, int, int, tuple[str, str], dict[str, Any]]],
    profile: XesProfile,
    role: str,
) -> None:
    xml.startElement("trace", {})
    _xes_attribute(xml, "concept:name", day)
    # Sorted on the timestamp, then on the order the records arrived: two events at the same
    # instant must come out the same way on every export, or the digest stops being reproducible.
    for _, _, _, moment, record in sorted(buffer, key=lambda item: item[:3]):
        _xes_event(xml, record, profile, role, moment)
    xml.endElement("trace")


class ExportService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace

    def _reusable_export(self, request: ExportRequest) -> ExportManifest | None:
        """The identical export of the same run, if one is still on disk.

        Exporting is deterministic: the same run and the same request produce the same files. So a
        second request for them was writing a second copy — clicking the download button twice cost
        half a gigabyte, and a workspace that had exported eleven times was holding 4.5 GB of which
        roughly 4 was duplicates.

        Falls through when the directory has been deleted, which is how a researcher reclaims the
        space: the next export simply rebuilds it.
        """
        with self.workspace.transaction() as connection:
            rows = connection.execute(
                """SELECT export_id FROM exports
                   WHERE run_id = ? AND request_json = ?
                   ORDER BY created_at DESC""",
                (request.run_id, request.model_dump_json(by_alias=True)),
            ).fetchall()
        for row in rows:
            manifest_path = self.workspace.exports_path / row["export_id"] / "manifest.json"
            if manifest_path.is_file():
                return ExportManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        return None

    def list_exports(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """Every recorded export, newest first, with what is actually on disk for it.

        A researcher who wants the space back needs to see the exports they built in earlier
        sessions, not only the one this browser tab happens to have created.
        """
        query = "SELECT export_id, run_id, created_at FROM exports"
        parameters: tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            parameters = (run_id,)
        query += " ORDER BY created_at DESC, export_id"
        with self.workspace.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            directory = self.workspace.exports_path / row["export_id"]
            archive = self.workspace.exports_path / f"{row['export_id']}.zip"
            files = [item for item in directory.rglob("*") if item.is_file()]
            results.append(
                {
                    "exportId": row["export_id"],
                    "runId": row["run_id"],
                    "createdAt": row["created_at"],
                    "available": directory.is_dir(),
                    "archived": archive.is_file(),
                    "fileCount": len(files),
                    "sizeBytes": sum(item.stat().st_size for item in files)
                    + (archive.stat().st_size if archive.is_file() else 0),
                }
            )
        return results

    def _profile_files(
        self, staging: Path, export_id: str, profile: ResidentProfile
    ) -> list[ExportManifestFile]:
        """The resident profile, in the three shapes it is useful in.

        The window of the request applies here as it does everywhere else: an export cut to one
        month must not ship the profile of the whole horizon, or the page would describe a person
        the accompanying sensor log never shows.
        """
        document = staging / "resident_profile.json"
        document.write_text(
            profile.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        page = staging / "resident_profile.html"
        page.write_text(render_profile_html(profile), encoding="utf-8", newline="\n")
        matrix = staging / "resident_profile.csv"
        series = write_heatmap_csv(matrix, profile)
        return [
            ExportManifestFile(
                role=PROFILE_ROLE,
                format=output_format,
                relative_path=f"{export_id}/{path.name}",
                media_type=media_type,
                record_count=count,
                size_bytes=path.stat().st_size,
                sha256=_digest(path),
            )
            for path, output_format, media_type, count in (
                (document, ExportFormat.json, "application/json", len(profile.residents)),
                (page, ExportFormat.html, "text/html", len(profile.residents)),
                (matrix, ExportFormat.csv, "text/csv", series),
            )
        ]

    def _summary_sources(
        self, artifacts: dict[str, Any]
    ) -> tuple[
        HomeModel | None, SensorModel | None, ScenarioFacts | None, dict[str, Any], dict[str, Any]
    ]:
        """The four documents the summary reads besides the trace, every one of them optional.

        A run assembled before one of them existed, or a horizon whose merge left it out, still
        gets a page: a summary that refuses to build because a report is missing would be a summary
        nobody can rely on. The scenario is read key by key rather than validated, because five
        months of day plans are four megabytes of material with no place on this page, and the keys
        that do belong on it all sit ahead of those days in the document.
        """

        def path_of(role: str) -> Path | None:
            descriptor = artifacts.get(role)
            if descriptor is None:
                return None
            return self.workspace.artifact_path(descriptor.artifact_id)

        home_path, sensor_path = path_of("home_model"), path_of("sensor_model")
        home = (
            HomeModel.model_validate_json(home_path.read_text(encoding="utf-8"))
            if home_path is not None
            else None
        )
        sensors = (
            SensorModel.model_validate_json(sensor_path.read_text(encoding="utf-8"))
            if sensor_path is not None
            else None
        )
        scenario_path = path_of("scenario")
        scenario = None
        habits: dict[str, Any] = {}
        if scenario_path is not None:
            scenario = ScenarioFacts(
                title=_metadata(scenario_path, "title"),
                language=_metadata(scenario_path, "language"),
                time_zone=_metadata(scenario_path, "timeZone"),
                residents=list(_metadata(scenario_path, "residents") or []),
            )
            habits = _metadata(scenario_path, "extensions.habitGroundTruth") or {}
        report_path = path_of("sensor_projection_report")
        stats: dict[str, Any] = {}
        if report_path is not None:
            counters = json.loads(report_path.read_text(encoding="utf-8")).get("sensors") or []
            stats = {item["sensorId"]: item for item in counters if "sensorId" in item}
        return home, sensors, scenario, habits, stats

    def _summary_file(
        self,
        staging: Path,
        export_id: str,
        artifacts: dict[str, Any],
        request: ExportRequest,
        profile: ResidentProfile,
        manifest_files: Sequence[ExportManifestFile],
        seed: int,
        trace_digest: str,
    ) -> ExportManifestFile:
        """The dataset summary: one page, written last so it can index the rest of the export."""
        home, sensors, scenario, habits, stats = self._summary_sources(artifacts)
        page = staging / "summary.html"
        page.write_text(
            render_summary_html(
                SummaryInputs(
                    run_id=request.run_id,
                    seed=seed,
                    trace_digest=trace_digest,
                    profile=profile,
                    files=tuple(manifest_files),
                    home=home,
                    sensors=sensors,
                    scenario=scenario,
                    habits=habits,
                    sensor_stats=stats,
                    include_start=request.include_start,
                    include_end=request.include_end,
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        return ExportManifestFile(
            role=SUMMARY_ROLE,
            format=ExportFormat.html,
            relative_path=f"{export_id}/{page.name}",
            media_type="text/html",
            record_count=len(profile.residents),
            size_bytes=page.stat().st_size,
            sha256=_digest(page),
        )

    def export(self, request: ExportRequest) -> ExportManifest:
        existing = self._reusable_export(request)
        if existing is not None:
            return existing
        artifacts = self.workspace.run_artifacts(request.run_id)
        # A merged horizon run has no single bundle — its days were bundled and executed
        # independently — so its horizon manifest carries the equivalent source provenance.
        source = artifacts.get("simulation_bundle") or artifacts.get("horizon_manifest")
        trace = artifacts.get("execution_trace")
        if source is None or trace is None:
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
        self.workspace.exports_path.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{export_id}.", dir=self.workspace.exports_path))
        files: list[ExportManifestFile] = []
        profile: ResidentProfile | None = None

        def resident_profile() -> ResidentProfile:
            """Aggregated once and shared: both computed roles want the same document, and a second
            pass over an eight month trace costs more than everything else here put together."""
            nonlocal profile
            if profile is None:
                profile = profile_from_trace_file(
                    trace_path,
                    run_id=request.run_id,
                    start=request.include_start,
                    end=request.include_end,
                )
            return profile

        try:
            # The computed roles come last whatever order they were requested in: the summary
            # publishes an index of the export, and an index written halfway through lists half of
            # it.
            for role in [item for item in request.roles if item not in COMPUTED_ROLES]:
                artifact_role, prefix = ROLE_SOURCES[role]
                source = artifacts.get(artifact_role)
                if source is None:
                    raise WorkspaceError(f"run has no artifact required for '{role}' export")
                source_path = self.workspace.artifact_path(source.artifact_id)
                for output_format in request.formats:
                    output = staging / f"{role}.{output_format.value}"
                    records = _filtered(_items(source_path, prefix), request, role)
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
            if PROFILE_ROLE in request.roles:
                files.extend(self._profile_files(staging, export_id, resident_profile()))
            if SUMMARY_ROLE in request.roles:
                files.append(
                    self._summary_file(
                        staging,
                        export_id,
                        artifacts,
                        request,
                        resident_profile(),
                        files,
                        seed,
                        trace_digest,
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

    def archive_export(self, export_id: str) -> Path:
        export_dir = (self.workspace.exports_path / export_id).resolve()
        zip_path = (self.workspace.exports_path / f"{export_id}.zip").resolve()
        if not zip_path.is_file():
            # Verified when the archive is built, not on every request for it. A complete dataset is
            # a third of a gigabyte across thirty-odd files, so re-hashing all of it to hand back an
            # archive that already exists is work nobody asked for; the archive itself is registered
            # as an artifact and carries its own digest.
            self.verify_manifest(export_id)
            temporary = zip_path.with_name(f".{zip_path.name}.{uuid4().hex}.tmp")
            # Level 1 rather than the default 6: on one 350 MB export the archive took 6.3 s at
            # level 6 and 3.3 s at level 1, for 33 MB instead of 26. Half the wait before the
            # browser sees its first byte is worth 7 MB on a local download.
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for entry in sorted(export_dir.rglob("*")):
                    if entry.is_file():
                        archive.write(entry, arcname=f"{export_id}/{entry.relative_to(export_dir)}")
            temporary.replace(zip_path)
        self.workspace.register_artifact(
            zip_path,
            role="export_archive",
            media_type="application/zip",
            schema_version="1.0.0",
        )
        return zip_path
