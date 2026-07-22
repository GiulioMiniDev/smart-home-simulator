from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from smart_home_sim.domain.application import (
    ApplicationIssue,
    ArtifactDescriptor,
    HomeSummary,
    JobEvent,
    JobProgress,
    JobRecord,
    JobStatus,
    ResidentSummary,
    WorkspaceManifest,
    WorkspaceSummary,
    utc_now,
)

DATABASE_VERSION = 1


class WorkspaceError(RuntimeError):
    pass


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat()


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WorkspaceService:
    """Transactional metadata store plus immutable, digest-verified artifact files."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.database_path = self.root / "workspace.sqlite3"
        self.objects_path = self.root / "objects"
        self.runs_path = self.root / "runs"
        self.exports_path = self.root / "exports"
        self.staging_path = self.root / "staging"
        self.diagnostic_mode = False

    @classmethod
    def create(cls, root: Path, name: str) -> WorkspaceService:
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        service = cls(root)
        if service.database_path.exists():
            raise WorkspaceError(f"workspace already exists at '{root}'")
        for directory in (
            service.objects_path,
            service.runs_path,
            service.exports_path,
            service.staging_path,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        service._migrate(name=name)
        return service

    @classmethod
    def open(
        cls, root: Path, *, reconcile: bool = True, recover_jobs: bool = True
    ) -> WorkspaceService:
        service = cls(root)
        if not service.database_path.is_file():
            raise WorkspaceError(f"workspace database not found at '{service.database_path}'")
        service._migrate()
        if recover_jobs:
            service._recover_running_jobs()
        if reconcile:
            service.diagnostic_mode = bool(service.reconcile())
        return service

    def export_archive(self, target: Path) -> Path:
        """Create a portable, point-in-time workspace archive atomically."""
        if self.summary().active_job_count:
            raise WorkspaceError("wait for active jobs before archiving the workspace")
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        snapshot_root = Path(tempfile.mkdtemp(prefix="workspace-snapshot-", dir=self.staging_path))
        try:
            snapshot_database = snapshot_root / "workspace.sqlite3"
            source = self._connect()
            destination = sqlite3.connect(snapshot_database)
            try:
                source.backup(destination)
            finally:
                source.close()
                destination.close()
            for directory in ("objects", "runs", "exports"):
                source_directory = self.root / directory
                if source_directory.is_dir():
                    shutil.copytree(source_directory, snapshot_root / directory)
            manifest = self.manifest()
            (snapshot_root / "workspace-manifest.json").write_text(
                manifest.model_dump_json(by_alias=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for path in sorted(item for item in snapshot_root.rglob("*") if item.is_file()):
                    archive.write(path, path.relative_to(snapshot_root).as_posix())
            temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(snapshot_root, ignore_errors=True)

    @classmethod
    def import_archive(
        cls,
        archive_path: Path,
        destination: Path,
        *,
        maximum_files: int = 20_000,
        maximum_uncompressed_bytes: int = 20 * 1024**3,
    ) -> WorkspaceService:
        """Verify and atomically restore a portable workspace archive."""
        archive_path = archive_path.resolve()
        destination = destination.resolve()
        if destination.exists() and any(destination.iterdir()):
            raise WorkspaceError(f"workspace destination is not empty: '{destination}'")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.import-", dir=destination.parent)
        )
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                entries = archive.infolist()
                if len(entries) > maximum_files:
                    raise WorkspaceError("workspace archive contains too many files")
                names: set[str] = set()
                total = 0
                for entry in entries:
                    name = entry.filename.replace("\\", "/")
                    if name in names:
                        raise WorkspaceError("workspace archive contains duplicate paths")
                    names.add(name)
                    total += entry.file_size
                    if total > maximum_uncompressed_bytes:
                        raise WorkspaceError("workspace archive exceeds the extraction limit")
                    if entry.flag_bits & 0x1:
                        raise WorkspaceError("encrypted workspace archives are not supported")
                    mode = (entry.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise WorkspaceError("workspace archive contains a symbolic link")
                    output = (staging / name).resolve()
                    try:
                        output.relative_to(staging)
                    except ValueError as error:
                        raise WorkspaceError("workspace archive contains an unsafe path") from error
                archive.extractall(staging)
            if not (staging / "workspace.sqlite3").is_file():
                raise WorkspaceError("workspace archive has no database")
            candidate = cls.open(staging, recover_jobs=False)
            issues = candidate.reconcile()
            if issues:
                raise WorkspaceError(
                    "workspace archive failed integrity checks: " + "; ".join(issues)
                )
            if destination.exists():
                destination.rmdir()
            staging.replace(destination)
            return cls.open(destination)
        except (OSError, zipfile.BadZipFile) as error:
            raise WorkspaceError(f"cannot import workspace archive: {error}") from error
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a read connection and always release its file handle."""
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def ensure_writable(self) -> None:
        if self.diagnostic_mode:
            raise WorkspaceError(
                "workspace is in diagnostic mode; repair integrity issues before publishing"
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _migrate(self, *, name: str | None = None) -> None:
        first = not self.database_path.exists()
        connection = self._connect()
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()["version"]
            if current > DATABASE_VERSION:
                raise WorkspaceError(
                    f"workspace database version {current} is newer than supported "
                    f"version {DATABASE_VERSION}"
                )
            if not first and current < DATABASE_VERSION:
                backup = self.database_path.with_suffix(f".pre-v{DATABASE_VERSION}.bak")
                source = sqlite3.connect(self.database_path)
                target = sqlite3.connect(backup)
                try:
                    source.backup(target)
                finally:
                    source.close()
                    target.close()
            if current < 1:
                self._migration_1(connection, name or self.root.name)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, _iso()),
                )
        finally:
            connection.close()

    @staticmethod
    def _migration_1(connection: sqlite3.Connection, name: str) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE workspace (
                workspace_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                format_version TEXT NOT NULL CHECK(format_version = '1.0.0'),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE homes (
                home_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                current_home_artifact_id TEXT,
                current_sensor_artifact_id TEXT,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE residents (
                resident_id TEXT PRIMARY KEY,
                home_id TEXT NOT NULL REFERENCES homes(home_id),
                source_resident_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                scenario_artifact_id TEXT,
                behavior_artifact_id TEXT,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(home_id, source_resident_id)
            );
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                home_id TEXT REFERENCES homes(home_id),
                run_id TEXT,
                role TEXT NOT NULL,
                schema_version TEXT,
                media_type TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
                created_at TEXT NOT NULL
            );
            CREATE INDEX artifacts_home_role ON artifacts(home_id, role);
            CREATE INDEX artifacts_run_role ON artifacts(run_id, role);
            CREATE TABLE revisions (
                revision_id TEXT PRIMARY KEY,
                home_id TEXT NOT NULL REFERENCES homes(home_id),
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                artifact_id TEXT REFERENCES artifacts(artifact_id),
                parent_revision_id TEXT REFERENCES revisions(revision_id),
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                home_id TEXT REFERENCES homes(home_id),
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                percent REAL NOT NULL CHECK(percent >= 0 AND percent <= 100),
                completed_units INTEGER NOT NULL DEFAULT 0,
                total_units INTEGER,
                message TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                process_id INTEGER,
                result_reference TEXT,
                error_code TEXT,
                error_message TEXT,
                seed INTEGER,
                request_json TEXT NOT NULL
            );
            CREATE INDEX jobs_status_requested ON jobs(status, requested_at DESC);
            CREATE TABLE job_events (
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(job_id, sequence)
            );
            CREATE TABLE exports (
                export_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                job_id TEXT REFERENCES jobs(job_id),
                request_json TEXT NOT NULL,
                manifest_artifact_id TEXT REFERENCES artifacts(artifact_id),
                created_at TEXT NOT NULL
            );
            CREATE TABLE replay_sessions (
                replay_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                verified_digest TEXT,
                position_at TEXT,
                filters_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE validation_issues (
                issue_id TEXT PRIMARY KEY,
                home_id TEXT REFERENCES homes(home_id),
                revision_id TEXT REFERENCES revisions(revision_id),
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                stage TEXT NOT NULL,
                path TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT NOT NULL,
                graphical_reference_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            COMMIT;
            """
        )
        now = _iso()
        connection.execute(
            "INSERT INTO workspace VALUES (?, ?, '1.0.0', ?, ?)",
            (f"workspace_{uuid4().hex[:16]}", name.strip() or "Research workspace", now, now),
        )

    def _safe_path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise WorkspaceError("artifact path escapes the workspace") from error
        return path

    def put_object(
        self,
        content: bytes,
        *,
        role: str,
        media_type: str = "application/json",
        schema_version: str | None = None,
        home_id: str | None = None,
        run_id: str | None = None,
        suffix: str = ".json",
    ) -> ArtifactDescriptor:
        self.ensure_writable()
        sha256 = hashlib.sha256(content).hexdigest()
        relative = f"objects/{sha256}{suffix}"
        target = self._safe_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{sha256}.", delete=False
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return self.register_artifact(
            target,
            role=role,
            media_type=media_type,
            schema_version=schema_version,
            home_id=home_id,
            run_id=run_id,
        )

    def register_artifact(
        self,
        path: Path,
        *,
        role: str,
        media_type: str = "application/json",
        schema_version: str | None = None,
        home_id: str | None = None,
        run_id: str | None = None,
    ) -> ArtifactDescriptor:
        self.ensure_writable()
        path = path.resolve()
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError as error:
            raise WorkspaceError("cannot register an artifact outside the workspace") from error
        digest = _sha256(path)
        created = utc_now()
        artifact_id = f"artifact_{digest[:20]}"
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM artifacts WHERE relative_path = ?", (relative,)
            ).fetchone()
            if existing is not None:
                if existing["sha256"] != digest or existing["role"] != role:
                    raise WorkspaceError("registered artifact path changed content or role")
                return self._artifact(existing)
            collision = connection.execute(
                "SELECT relative_path, sha256 FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            if collision is not None:
                # Equal bytes may legitimately have different semantic roles or
                # run-local paths. Keep content-addressed storage while giving
                # each registered relationship its own stable database identity.
                identity = hashlib.sha256(f"{digest}:{relative}:{role}".encode()).hexdigest()[:12]
                artifact_id = f"artifact_{digest[:20]}_{identity}"
            connection.execute(
                """INSERT INTO artifacts(
                    artifact_id, home_id, run_id, role, schema_version, media_type,
                    relative_path, size_bytes, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    home_id,
                    run_id,
                    role,
                    schema_version,
                    media_type,
                    relative,
                    path.stat().st_size,
                    digest,
                    created.isoformat(),
                ),
            )
        return ArtifactDescriptor(
            artifact_id=artifact_id,
            role=role,
            schema_version=schema_version,
            media_type=media_type,
            relative_path=relative,
            size_bytes=path.stat().st_size,
            sha256=digest,
            created_at=created,
        )

    @staticmethod
    def _artifact(row: sqlite3.Row) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            artifact_id=row["artifact_id"],
            role=row["role"],
            schema_version=row["schema_version"],
            media_type=row["media_type"],
            relative_path=row["relative_path"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def read_artifact(self, artifact_id: str) -> bytes:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT relative_path, sha256 FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise WorkspaceError(f"unknown artifact '{artifact_id}'")
        path = self._safe_path(row["relative_path"])
        if not path.is_file() or _sha256(path) != row["sha256"]:
            raise WorkspaceError(f"artifact '{artifact_id}' is missing or corrupt")
        return path.read_bytes()

    def artifact_path(self, artifact_id: str) -> Path:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT relative_path, sha256 FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise WorkspaceError(f"unknown artifact '{artifact_id}'")
        path = self._safe_path(row["relative_path"])
        if not path.is_file() or _sha256(path) != row["sha256"]:
            raise WorkspaceError(f"artifact '{artifact_id}' is missing or corrupt")
        return path

    def create_home(self, name: str, description: str = "") -> HomeSummary:
        self.ensure_writable()
        if not name.strip():
            raise WorkspaceError("home name is required")
        home_id = f"home_{uuid4().hex[:16]}"
        now = _iso()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO homes(home_id, name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (home_id, name.strip(), description.strip(), now, now),
            )
            connection.execute("UPDATE workspace SET updated_at = ?", (now,))
        return self.get_home(home_id)

    def get_home(self, home_id: str) -> HomeSummary:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT h.*,
                    (SELECT COUNT(*) FROM residents r
                        WHERE r.home_id=h.home_id AND r.deleted_at IS NULL)
                        AS resident_count,
                    (SELECT COUNT(*) FROM jobs j WHERE j.home_id=h.home_id AND j.status='completed')
                        AS run_count,
                    (SELECT COUNT(*) FROM validation_issues i WHERE i.home_id=h.home_id)
                        AS issue_count
                FROM homes h WHERE h.home_id=? AND h.deleted_at IS NULL""",
                (home_id,),
            ).fetchone()
        if row is None:
            raise WorkspaceError(f"unknown home '{home_id}'")
        return HomeSummary(
            home_id=row["home_id"],
            name=row["name"],
            description=row["description"],
            resident_count=row["resident_count"],
            run_count=row["run_count"],
            issue_count=row["issue_count"],
            current_home_artifact_id=row["current_home_artifact_id"],
            current_sensor_artifact_id=row["current_sensor_artifact_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_homes(self, query: str = "") -> list[HomeSummary]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT home_id FROM homes WHERE deleted_at IS NULL AND name LIKE ? "
                "ORDER BY updated_at DESC, name",
                (f"%{query}%",),
            ).fetchall()
        return [self.get_home(row["home_id"]) for row in rows]

    def add_resident(
        self,
        home_id: str,
        source_resident_id: str,
        display_name: str,
        *,
        scenario_artifact_id: str | None = None,
        behavior_artifact_id: str | None = None,
    ) -> ResidentSummary:
        self.ensure_writable()
        self.get_home(home_id)
        resident_id = f"resident_{uuid4().hex[:16]}"
        created = utc_now()
        try:
            with self.transaction() as connection:
                connection.execute(
                    """INSERT INTO residents(
                        resident_id, home_id, source_resident_id, display_name,
                        scenario_artifact_id, behavior_artifact_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        resident_id,
                        home_id,
                        source_resident_id,
                        display_name.strip() or source_resident_id,
                        scenario_artifact_id,
                        behavior_artifact_id,
                        created.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise WorkspaceError("resident is already associated with this home") from error
        return ResidentSummary(
            resident_id=resident_id,
            home_id=home_id,
            source_resident_id=source_resident_id,
            display_name=display_name.strip() or source_resident_id,
            scenario_artifact_id=scenario_artifact_id,
            behavior_artifact_id=behavior_artifact_id,
            created_at=created,
        )

    def replace_authoring_residents(
        self,
        home_id: str,
        residents: list[tuple[str, str]],
        *,
        scenario_artifact_id: str,
        behavior_artifact_id: str,
    ) -> list[ResidentSummary]:
        """Synchronize a home's active residents with one accepted authoring revision."""
        self.ensure_writable()
        self.get_home(home_id)
        source_ids = [source_id for source_id, _ in residents]
        if len(source_ids) != len(set(source_ids)):
            raise WorkspaceError("accepted authoring contains duplicate resident identifiers")
        now = utc_now()
        with self.transaction() as connection:
            if source_ids:
                placeholders = ", ".join("?" for _ in source_ids)
                connection.execute(
                    f"""UPDATE residents SET deleted_at=?
                        WHERE home_id=? AND deleted_at IS NULL
                        AND source_resident_id NOT IN ({placeholders})""",  # noqa: S608
                    (now.isoformat(), home_id, *source_ids),
                )
            else:
                connection.execute(
                    "UPDATE residents SET deleted_at=? WHERE home_id=? AND deleted_at IS NULL",
                    (now.isoformat(), home_id),
                )
            for source_id, display_name in residents:
                row = connection.execute(
                    """SELECT resident_id, created_at FROM residents
                        WHERE home_id=? AND source_resident_id=?""",
                    (home_id, source_id),
                ).fetchone()
                normalized_name = display_name.strip() or source_id
                if row is None:
                    connection.execute(
                        """INSERT INTO residents(
                            resident_id, home_id, source_resident_id, display_name,
                            scenario_artifact_id, behavior_artifact_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"resident_{uuid4().hex[:16]}",
                            home_id,
                            source_id,
                            normalized_name,
                            scenario_artifact_id,
                            behavior_artifact_id,
                            now.isoformat(),
                        ),
                    )
                else:
                    connection.execute(
                        """UPDATE residents SET display_name=?, scenario_artifact_id=?,
                            behavior_artifact_id=?, deleted_at=NULL
                            WHERE resident_id=?""",
                        (
                            normalized_name,
                            scenario_artifact_id,
                            behavior_artifact_id,
                            row["resident_id"],
                        ),
                    )
        return self.list_residents(home_id)

    def list_residents(self, home_id: str | None = None) -> list[ResidentSummary]:
        query = "SELECT * FROM residents WHERE deleted_at IS NULL"
        parameters: tuple[Any, ...] = ()
        if home_id is not None:
            query += " AND home_id = ?"
            parameters = (home_id,)
        query += " ORDER BY display_name, resident_id"
        with self.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            ResidentSummary(
                resident_id=row["resident_id"],
                home_id=row["home_id"],
                source_resident_id=row["source_resident_id"],
                display_name=row["display_name"],
                scenario_artifact_id=row["scenario_artifact_id"],
                behavior_artifact_id=row["behavior_artifact_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def create_revision(
        self,
        home_id: str,
        kind: str,
        artifact_id: str | None,
        *,
        status: str,
        provenance: dict[str, Any] | None = None,
        parent_revision_id: str | None = None,
    ) -> str:
        self.ensure_writable()
        self.get_home(home_id)
        revision_id = f"revision_{uuid4().hex[:16]}"
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO revisions(
                    revision_id, home_id, kind, status, artifact_id, parent_revision_id,
                    provenance_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    revision_id,
                    home_id,
                    kind,
                    status,
                    artifact_id,
                    parent_revision_id,
                    json.dumps(provenance or {}, sort_keys=True),
                    _iso(),
                ),
            )
            column = {
                "home": "current_home_artifact_id",
                "sensor": "current_sensor_artifact_id",
            }.get(kind)
            if status == "valid" and artifact_id and column:
                connection.execute(
                    f"UPDATE homes SET {column}=?, updated_at=? WHERE home_id=?",  # noqa: S608
                    (artifact_id, _iso(), home_id),
                )
        return revision_id

    def create_job(
        self,
        kind: str,
        *,
        home_id: str | None = None,
        seed: int | None = None,
        request: dict[str, Any] | None = None,
    ) -> JobRecord:
        self.ensure_writable()
        if home_id is not None:
            self.get_home(home_id)
        job_id = f"job_{uuid4().hex[:16]}"
        requested = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO jobs(
                    job_id, home_id, kind, status, phase, percent, message,
                    requested_at, seed, request_json
                ) VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?, ?, ?)""",
                (
                    job_id,
                    home_id,
                    kind,
                    "Waiting for a local worker",
                    requested.isoformat(),
                    seed,
                    json.dumps(request or {}, sort_keys=True),
                ),
            )
        self.append_event(job_id, "status", "Job queued")
        return self.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        progress: JobProgress,
        *,
        process_id: int | None = None,
        result_reference: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRecord:
        current = self.get_job(job_id)
        terminal = status in {
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
            JobStatus.interrupted,
        }
        started = current.started_at or (utc_now() if status is JobStatus.running else None)
        finished = utc_now() if terminal else None
        with self.transaction() as connection:
            connection.execute(
                """UPDATE jobs SET status=?, phase=?, percent=?, completed_units=?,
                    total_units=?, message=?, started_at=?, finished_at=?, process_id=?,
                    result_reference=?, error_code=?, error_message=? WHERE job_id=?""",
                (
                    status.value,
                    progress.phase,
                    progress.percent,
                    progress.completed_units,
                    progress.total_units,
                    progress.message,
                    started.isoformat() if started else None,
                    finished.isoformat() if finished else None,
                    process_id,
                    result_reference,
                    error_code,
                    error_message,
                    job_id,
                ),
            )
        self.append_event(
            job_id,
            "status" if status != current.status else "progress",
            progress.message,
            payload={"status": status.value, "phase": progress.phase, "percent": progress.percent},
            level="error" if status is JobStatus.failed else "info",
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise WorkspaceError(f"unknown job '{job_id}'")
        return JobRecord(
            job_id=row["job_id"],
            home_id=row["home_id"],
            kind=row["kind"],
            status=JobStatus(row["status"]),
            progress=JobProgress(
                phase=row["phase"],
                percent=row["percent"],
                completed_units=row["completed_units"],
                total_units=row["total_units"],
                message=row["message"],
            ),
            requested_at=datetime.fromisoformat(row["requested_at"]),
            started_at=_datetime(row["started_at"]),
            finished_at=_datetime(row["finished_at"]),
            process_id=row["process_id"],
            result_reference=row["result_reference"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            seed=row["seed"],
        )

    def list_jobs(self, *, limit: int = 100, home_id: str | None = None) -> list[JobRecord]:
        query = "SELECT job_id FROM jobs"
        parameters: list[Any] = []
        if home_id is not None:
            query += " WHERE home_id=?"
            parameters.append(home_id)
        query += " ORDER BY requested_at DESC LIMIT ?"
        parameters.append(max(1, min(limit, 1000)))
        with self.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self.get_job(row["job_id"]) for row in rows]

    def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> JobEvent:
        occurred = utc_now()
        with self.transaction() as connection:
            if (
                connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                is None
            ):
                raise WorkspaceError(f"unknown job '{job_id}'")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM job_events WHERE job_id=?",
                (job_id,),
            ).fetchone()["sequence"]
            connection.execute(
                "INSERT INTO job_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    sequence,
                    occurred.isoformat(),
                    event_type,
                    level,
                    message,
                    json.dumps(payload or {}, sort_keys=True),
                ),
            )
        return JobEvent(
            job_id=job_id,
            sequence=sequence,
            occurred_at=occurred,
            event_type=event_type,  # type: ignore[arg-type]
            level=level,  # type: ignore[arg-type]
            message=message,
            payload=payload or {},
        )

    def list_events(self, job_id: str, after: int = 0) -> list[JobEvent]:
        self.get_job(job_id)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id=? AND sequence>? ORDER BY sequence",
                (job_id, after),
            ).fetchall()
        return [
            JobEvent(
                job_id=row["job_id"],
                sequence=row["sequence"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                event_type=row["event_type"],
                level=row["level"],
                message=row["message"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def job_request(self, job_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT request_json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise WorkspaceError(f"unknown job '{job_id}'")
        return json.loads(row["request_json"])

    def import_run_directory(self, job_id: str, run_directory: Path) -> list[ArtifactDescriptor]:
        run_directory = run_directory.resolve()
        expected = (self.runs_path / job_id).resolve()
        if run_directory != expected or not run_directory.is_dir():
            raise WorkspaceError("run directory is missing or outside the job location")
        job = self.get_job(job_id)
        descriptors: list[ArtifactDescriptor] = []
        for path in sorted(run_directory.glob("*.json")):
            role = path.stem.replace("-", "_")
            descriptors.append(
                self.register_artifact(path, role=role, home_id=job.home_id, run_id=job_id)
            )
        if not descriptors:
            raise WorkspaceError("completed run contains no artifacts")
        return descriptors

    def run_artifacts(self, run_id: str) -> dict[str, ArtifactDescriptor]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY role", (run_id,)
            ).fetchall()
        return {row["role"]: self._artifact(row) for row in rows}

    def replace_validation_issues(
        self,
        home_id: str,
        issues: list[ApplicationIssue],
        *,
        revision_id: str | None = None,
    ) -> None:
        """Persist the current authoritative validation result for one home."""
        self.ensure_writable()
        self.get_home(home_id)
        with self.transaction() as connection:
            connection.execute("DELETE FROM validation_issues WHERE home_id=?", (home_id,))
            for issue in issues:
                connection.execute(
                    """INSERT INTO validation_issues(
                        issue_id, home_id, revision_id, code, severity, stage, path,
                        message, details_json, graphical_reference_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"issue_{uuid4().hex[:16]}",
                        home_id,
                        revision_id,
                        issue.code,
                        issue.severity,
                        issue.stage,
                        issue.path,
                        issue.message,
                        json.dumps(issue.details, sort_keys=True),
                        (
                            issue.graphical_reference.model_dump_json(by_alias=True)
                            if issue.graphical_reference
                            else None
                        ),
                        _iso(),
                    ),
                )

    def list_validation_issues(self, home_id: str) -> list[ApplicationIssue]:
        self.get_home(home_id)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM validation_issues WHERE home_id=? ORDER BY created_at, issue_id",
                (home_id,),
            ).fetchall()
        return [
            ApplicationIssue.model_validate(
                {
                    "code": row["code"],
                    "severity": row["severity"],
                    "stage": row["stage"],
                    "path": row["path"],
                    "message": row["message"],
                    "details": json.loads(row["details_json"]),
                    "graphicalReference": (
                        json.loads(row["graphical_reference_json"])
                        if row["graphical_reference_json"]
                        else None
                    ),
                }
            )
            for row in rows
        ]

    def save_replay_session(
        self,
        run_id: str,
        *,
        verified_digest: str | None = None,
        position_at: datetime | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_writable()
        if not self.run_artifacts(run_id):
            raise WorkspaceError(f"unknown run '{run_id}'")
        previous = self.replay_session(run_id)
        effective_filters = previous.get("filters", {}) if filters is None else filters
        replay_id = f"replay_{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:16]}"
        now = _iso()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT created_at FROM replay_sessions WHERE replay_id=?", (replay_id,)
            ).fetchone()
            connection.execute(
                """INSERT INTO replay_sessions(
                    replay_id, run_id, verified_digest, position_at, filters_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(replay_id) DO UPDATE SET
                    verified_digest=COALESCE(excluded.verified_digest, verified_digest),
                    position_at=COALESCE(excluded.position_at, position_at),
                    filters_json=excluded.filters_json,
                    updated_at=excluded.updated_at""",
                (
                    replay_id,
                    run_id,
                    verified_digest,
                    position_at.isoformat() if position_at else None,
                    json.dumps(effective_filters, sort_keys=True),
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
        return self.replay_session(run_id)

    def replay_session(self, run_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM replay_sessions WHERE run_id=? ORDER BY updated_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            return {
                "runId": run_id,
                "verifiedDigest": None,
                "positionAt": None,
                "filters": {},
            }
        return {
            "replayId": row["replay_id"],
            "runId": row["run_id"],
            "verifiedDigest": row["verified_digest"],
            "positionAt": row["position_at"],
            "filters": json.loads(row["filters_json"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key=?", (key,)
            ).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def set_setting(self, key: str, value: Any) -> Any:
        self.ensure_writable()
        normalized = key.strip()
        if not normalized or len(normalized) > 100:
            raise WorkspaceError("setting key must contain between 1 and 100 characters")
        try:
            encoded = json.dumps(value, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise WorkspaceError("setting value must be valid JSON") from error
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                    updated_at=excluded.updated_at""",
                (normalized, encoded, _iso()),
            )
        return json.loads(encoded)

    def summary(self) -> WorkspaceSummary:
        with self.connection() as connection:
            workspace = connection.execute("SELECT * FROM workspace").fetchone()
            counts = connection.execute(
                """SELECT
                    (SELECT COUNT(*) FROM homes WHERE deleted_at IS NULL) AS homes,
                    (SELECT COUNT(*) FROM residents WHERE deleted_at IS NULL) AS residents,
                    (SELECT COUNT(*) FROM jobs WHERE status='completed') AS runs,
                    (SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')) AS active,
                    (SELECT COUNT(*) FROM artifacts) AS artifacts"""
            ).fetchone()
        return WorkspaceSummary(
            workspace_id=workspace["workspace_id"],
            name=workspace["name"],
            created_at=datetime.fromisoformat(workspace["created_at"]),
            updated_at=datetime.fromisoformat(workspace["updated_at"]),
            diagnostic_mode=self.diagnostic_mode,
            home_count=counts["homes"],
            resident_count=counts["residents"],
            run_count=counts["runs"],
            active_job_count=counts["active"],
            artifact_count=counts["artifacts"],
        )

    def manifest(self) -> WorkspaceManifest:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM artifacts ORDER BY relative_path").fetchall()
        return WorkspaceManifest(
            workspace=self.summary(),
            exported_at=utc_now(),
            homes=self.list_homes(),
            residents=self.list_residents(),
            artifacts=[self._artifact(row) for row in rows],
        )

    def reconcile(self) -> list[str]:
        issues: list[str] = []
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT artifact_id, relative_path, size_bytes, sha256 FROM artifacts"
            ).fetchall()
        known: set[Path] = set()
        for row in rows:
            try:
                path = self._safe_path(row["relative_path"])
            except WorkspaceError as error:
                issues.append(f"{row['artifact_id']}: {error}")
                continue
            known.add(path)
            if not path.is_file():
                issues.append(f"{row['artifact_id']}: file is missing")
            elif path.stat().st_size != row["size_bytes"] or _sha256(path) != row["sha256"]:
                issues.append(f"{row['artifact_id']}: size or digest mismatch")
        for base in (self.objects_path, self.runs_path, self.exports_path):
            if base.exists():
                for path in base.rglob("*"):
                    if (
                        path.is_file()
                        and path not in known
                        and path.name != "workspace-manifest.json"
                    ):
                        issues.append(f"orphan file: {path.relative_to(self.root).as_posix()}")
        self.diagnostic_mode = bool(issues)
        return sorted(issues)

    def _recover_running_jobs(self) -> None:
        if not self.database_path.exists():
            return
        with self.connection() as connection:
            rows = connection.execute("SELECT job_id FROM jobs WHERE status='running'").fetchall()
        for row in rows:
            self.update_job(
                row["job_id"],
                JobStatus.interrupted,
                JobProgress(
                    phase="interrupted",
                    percent=self.get_job(row["job_id"]).progress.percent,
                    message="The backend stopped before this job completed",
                ),
                error_code="BACKEND_INTERRUPTED",
                error_message="The backend stopped before this job completed",
            )

    def remove_staging_for(self, job_id: str) -> None:
        for path in self.runs_path.glob(f".{job_id}.*"):
            if path.is_dir() and path.parent.resolve() == self.runs_path.resolve():
                shutil.rmtree(path, ignore_errors=True)
