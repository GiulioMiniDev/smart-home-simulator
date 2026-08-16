"""Where this installation keeps its files, and how a researcher moves them.

A workspace holds every execution trace, sensor log and export the application has ever produced,
so it grows without bound while the home directory it defaults into sits on the system drive. That
is the wrong drive to fill: the machine starts failing at things that have nothing to do with this
application. Everything here exists so the location is a decision the researcher makes in the
interface, once, and the application remembers.

The configuration file is the anchor. It lives at a fixed path that needs no configuration to find
(``~/.smart-home-simulator/configuration.json``, or ``SMART_HOME_SIM_HOME`` when set) and records
where everything else lives, so both the bootstrap script and the server agree without either one
having to be told.
"""

from __future__ import annotations

import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from smart_home_sim.domain.base import ContractModel, to_camel

CONFIGURATION_VERSION = 1
DEFAULT_PORT = 8765

HOME_VARIABLE = "SMART_HOME_SIM_HOME"
DATA_DIRECTORY_VARIABLE = "SMART_HOME_SIM_DATA_DIR"
WORKSPACE_VARIABLE = "SMART_HOME_SIM_WORKSPACE"
SUPERVISED_VARIABLE = "SMART_HOME_SIM_SUPERVISED"

#: Exit code the server uses to ask the bootstrap script to start it again.
RESTART_EXIT_CODE = 87

PathSource = Literal["command-line", "environment", "configuration", "default"]


class ConfigurationError(RuntimeError):
    """A location the application was asked to use that it cannot use."""


class PendingRelocation(BaseModel):
    """A move that has been agreed but not performed, because the workspace was still open."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    source: str
    destination: str


class StoredConfiguration(BaseModel):
    """The persisted file.

    Deliberately tolerant on read (``extra="ignore"``, every field optional): a configuration
    written by a later version must not stop this one from starting, and the worst outcome of an
    unreadable file is falling back to the defaults, never a refusal to run.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    version: int = CONFIGURATION_VERSION
    workspace_directory: str | None = None
    data_directory: str | None = None
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    open_browser: bool = True
    pending_relocation: PendingRelocation | None = None


class VolumeUsage(ContractModel):
    """How full the drive holding a path is."""

    root: str = Field(min_length=1)
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)


class StorageEntry(ContractModel):
    """One top-level item inside the workspace, with what it holds and why it is there."""

    name: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    description: str = Field(min_length=1)


class StorageReport(ContractModel):
    path: str = Field(min_length=1)
    exists: bool
    total_bytes: int = Field(ge=0)
    entries: list[StorageEntry] = Field(default_factory=list)
    volume: VolumeUsage | None = None


class DirectoryLocation(ContractModel):
    """A configured directory, and what decided it."""

    path: str = Field(min_length=1)
    source: PathSource
    exists: bool
    volume: VolumeUsage | None = None


class DestinationCheck(ContractModel):
    """Whether a candidate directory can receive the workspace, in the words the page shows."""

    path: str = Field(min_length=1)
    usable: bool
    message: str = Field(min_length=1)
    empty: bool = False
    holds_workspace: bool = False
    same_volume: bool = False
    volume: VolumeUsage | None = None


class ConfigurationView(ContractModel):
    """Everything the settings page needs to describe the installation.

    ``workspace`` is the folder this server actually has open; ``configured_workspace`` is the one
    the next start will use. They differ for exactly as long as a change has been saved and not yet
    applied, and keeping both is what lets the page say so instead of appearing to have lied.
    """

    configuration_path: str = Field(min_length=1)
    workspace: DirectoryLocation
    configured_workspace: DirectoryLocation
    data_directory: DirectoryLocation
    port: int = Field(ge=1, le=65535)
    open_browser: bool
    pending_relocation: PendingRelocation | None = None
    restart_required: bool = False
    supervised: bool = False
    volumes: list[VolumeUsage] = Field(default_factory=list)


#: The top-level contents of a workspace, in the order the settings page lists them. Anything not
#: named here is reported together as "Other files" rather than silently left out of the total.
WORKSPACE_CONTENTS: tuple[tuple[str, str, str], ...] = (
    (
        "runs",
        "Simulation runs",
        "Execution traces, sensor logs and reports. This is the evidence a run is read back from.",
    ),
    (
        "exports",
        "Exports",
        "Datasets built from runs. Reproducible: the same run and request rebuild them byte for "
        "byte, so deleting one costs only the time to export it again.",
    ),
    (
        "objects",
        "Stored inputs",
        "Authoring bundles, home models and sensor models, catalogued by digest.",
    ),
    (
        "generations",
        "Generations",
        "Working files for horizons generated from a brief.",
    ),
    (
        "staging",
        "Staging",
        "Temporary files for work in progress. Empty whenever nothing is running.",
    ),
    (
        "workspace.sqlite3",
        "Catalogue",
        "The metadata database: homes, runs, jobs and every artifact digest. Small, and the one "
        "file a workspace cannot be rebuilt without.",
    ),
)


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def application_home() -> Path:
    """Where the configuration file lives. Found without reading any configuration, by design."""
    return _environment_path(HOME_VARIABLE) or Path.home() / ".smart-home-simulator"


def configuration_path() -> Path:
    return application_home() / "configuration.json"


def load() -> StoredConfiguration:
    """Read the configuration, falling back to the defaults for anything unreadable."""
    try:
        payload = json.loads(configuration_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StoredConfiguration()
    if not isinstance(payload, dict):
        return StoredConfiguration()
    try:
        return StoredConfiguration.model_validate(payload)
    except ValueError:
        return StoredConfiguration()


def save(configuration: StoredConfiguration) -> StoredConfiguration:
    """Write the configuration atomically, so an interrupted save cannot leave a broken file."""
    path = configuration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = configuration.model_dump_json(by_alias=True, exclude_none=True, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return configuration


def resolve_data_directory(
    override: Path | None = None, configuration: StoredConfiguration | None = None
) -> tuple[Path, PathSource]:
    """Where the virtual environment and the bootstrap state live."""
    if override is not None:
        return override.expanduser().resolve(), "command-line"
    from_environment = _environment_path(DATA_DIRECTORY_VARIABLE)
    if from_environment is not None:
        return from_environment.resolve(), "environment"
    settings = load() if configuration is None else configuration
    if settings.data_directory:
        return Path(settings.data_directory).expanduser().resolve(), "configuration"
    return application_home().resolve(), "default"


def resolve_workspace_directory(
    override: Path | None = None, configuration: StoredConfiguration | None = None
) -> tuple[Path, PathSource]:
    """Where the research data lives: runs, exports, stored inputs and the catalogue."""
    if override is not None:
        return override.expanduser().resolve(), "command-line"
    from_environment = _environment_path(WORKSPACE_VARIABLE)
    if from_environment is not None:
        return from_environment.resolve(), "environment"
    settings = load() if configuration is None else configuration
    if settings.workspace_directory:
        return Path(settings.workspace_directory).expanduser().resolve(), "configuration"
    return resolve_data_directory(configuration=settings)[0] / "workspace", "default"


def _nearest_existing(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def volume_usage(path: Path) -> VolumeUsage | None:
    """How full the drive holding ``path`` is, or None when nothing on that drive exists yet."""
    anchor = _nearest_existing(path)
    if anchor is None:
        return None
    try:
        usage = shutil.disk_usage(anchor)
    except OSError:
        return None
    return VolumeUsage(
        root=str(Path(anchor).anchor or anchor), total_bytes=usage.total, free_bytes=usage.free
    )


def _volume_roots() -> Iterator[Path]:
    """Every mounted volume the researcher could plausibly choose."""
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            if root.exists():
                yield root
        return
    yield Path("/")
    for parent in (Path("/media"), Path("/mnt"), Path("/Volumes")):
        if not parent.is_dir():
            continue
        try:
            children = sorted(parent.iterdir())
        except OSError:  # pragma: no cover - an unreadable mount point is simply not offered
            continue
        for child in children:
            if child.is_dir():
                yield child


def available_volumes() -> list[VolumeUsage]:
    volumes: list[VolumeUsage] = []
    seen: set[str] = set()
    for root in _volume_roots():
        usage = volume_usage(root)
        if usage is None or usage.root in seen:
            continue
        seen.add(usage.root)
        volumes.append(usage)
    return volumes


def _measure(path: Path) -> tuple[int, int]:
    """Bytes and file count under ``path``, tolerating files that vanish while being counted."""
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:  # pragma: no cover - the file went away between listing and measuring
            return 0, 0
    total = 0
    files = 0
    for directory, _, names in os.walk(path):
        for name in names:
            try:
                total += (Path(directory) / name).stat().st_size
            except OSError:  # pragma: no cover - same race, one file lighter
                continue
            files += 1
    return total, files


def storage_report(root: Path) -> StorageReport:
    """What the workspace is holding, broken down by what each part is for."""
    root = root.expanduser()
    if not root.is_dir():
        return StorageReport(path=str(root), exists=False, total_bytes=0, volume=volume_usage(root))
    entries: list[StorageEntry] = []
    named = {name for name, _, _ in WORKSPACE_CONTENTS}
    for name, label, description in WORKSPACE_CONTENTS:
        size, files = _measure(root / name) if (root / name).exists() else (0, 0)
        entries.append(
            StorageEntry(
                name=label,
                relative_path=name,
                size_bytes=size,
                file_count=files,
                description=description,
            )
        )
    other_size = 0
    other_files = 0
    for child in sorted(root.iterdir()):
        if child.name in named:
            continue
        size, files = _measure(child)
        other_size += size
        other_files += files
    if other_files:
        entries.append(
            StorageEntry(
                name="Other files",
                relative_path=".",
                size_bytes=other_size,
                file_count=other_files,
                description="Logs and anything else in the folder that no catalogue entry "
                "describes. Maintenance can reclaim these.",
            )
        )
    return StorageReport(
        path=str(root),
        exists=True,
        total_bytes=sum(entry.size_bytes for entry in entries),
        entries=entries,
        volume=volume_usage(root),
    )


def _writable(directory: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".smart-home-write-test-"):
            return True
    except OSError:
        return False


def _contains(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


def _same_volume(first: Path, second: Path) -> bool:
    left = _nearest_existing(first)
    right = _nearest_existing(second)
    if left is None or right is None:
        return False
    return Path(left).anchor.lower() == Path(right).anchor.lower()


def holds_workspace(path: Path) -> bool:
    return (path / "workspace.sqlite3").is_file()


def check_destination(
    candidate: str, *, current: Path, required_bytes: int = 0
) -> DestinationCheck:
    """Can the workspace live at ``candidate``, and what would that cost?

    Answers rather than refuses: the page shows this while the researcher is still typing, so an
    unusable path has to explain itself instead of producing an error the field cannot display.
    """
    text = candidate.strip()
    if not text:
        return DestinationCheck(
            path=candidate or ".", usable=False, message="Enter a folder for the workspace."
        )
    path = Path(text).expanduser()
    if not path.is_absolute():
        return DestinationCheck(
            path=text,
            usable=False,
            message="Use a complete path, starting from the drive or the root folder.",
        )
    path = Path(os.path.normpath(path))
    volume = volume_usage(path)
    same_volume = _same_volume(path, current)
    if path.is_file():
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            message="That path is a file, not a folder.",
        )
    if _contains(current, path) and path != current:
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            same_volume=same_volume,
            message="That folder is inside the current workspace, so moving into it would move "
            "the workspace into itself.",
        )
    anchor = _nearest_existing(path)
    if anchor is None:
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            message="That drive is not available on this machine.",
        )
    if not _writable(anchor):
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            same_volume=same_volume,
            message=f"This application cannot write to {anchor}.",
        )
    existing = holds_workspace(path)
    empty = not path.exists() or not any(path.iterdir())
    if path.exists() and not empty and not existing:
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            same_volume=same_volume,
            empty=False,
            message="That folder already holds other files. Choose an empty folder or a folder "
            "that already holds a workspace.",
        )
    # A move within one volume renames the folder, so it needs no free space at all.
    needed = 0 if same_volume else required_bytes
    if volume is not None and needed > volume.free_bytes:
        return DestinationCheck(
            path=str(path),
            usable=False,
            volume=volume,
            same_volume=same_volume,
            empty=empty,
            holds_workspace=existing,
            message=f"{_bytes(needed)} are needed and {_bytes(volume.free_bytes)} are free on "
            f"{volume.root}.",
        )
    if existing:
        message = "A workspace already exists here; the application will open it."
    elif same_volume:
        message = "Ready. This is the same drive, so the move is a rename and finishes instantly."
    else:
        message = f"Ready. {_bytes(needed)} will be copied to {volume.root if volume else path}."
    return DestinationCheck(
        path=str(path),
        usable=True,
        volume=volume,
        same_volume=same_volume,
        empty=empty,
        holds_workspace=existing,
        message=message,
    )


def _bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    size = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}" if size < 10 else f"{size:.0f} {unit}"
    return f"{size:.0f} PB"  # pragma: no cover - no workspace is a petabyte


def request_relocation(source: Path, destination: str) -> StoredConfiguration:
    """Record a move for the next start, instead of moving a workspace that is currently open.

    Moving files out from under an open SQLite database and a running worker is how a workspace
    becomes half a workspace. The next start owns the move: nothing has the files open then, and a
    copy that fails leaves the original exactly where it was.
    """
    report = storage_report(source)
    check = check_destination(destination, current=source, required_bytes=report.total_bytes)
    if not check.usable:
        raise ConfigurationError(check.message)
    if Path(check.path) == source:
        raise ConfigurationError("The workspace is already in that folder.")
    if check.holds_workspace:
        raise ConfigurationError(
            "A workspace already exists there. Switch to it instead of moving this one into it."
        )
    configuration = load()
    configuration.pending_relocation = PendingRelocation(source=str(source), destination=check.path)
    return save(configuration)


def cancel_relocation() -> StoredConfiguration:
    configuration = load()
    configuration.pending_relocation = None
    return save(configuration)


def apply_pending_relocation(report: Callable[[str], None] = lambda _: None) -> str | None:
    """Perform a move recorded earlier, before anything opens the workspace.

    Returns what happened, for the console, or None when there was nothing to do. A failure is
    reported and the pending move cleared rather than raised: the researcher's data is still at the
    source, so the application can start normally and say why the move did not happen.
    """
    configuration = load()
    pending = configuration.pending_relocation
    if pending is None:
        return None
    source = Path(pending.source)
    destination = Path(pending.destination)
    configuration.pending_relocation = None
    if not source.exists():
        save(configuration)
        return f"nothing to move: {source} no longer exists"
    report(f"Moving the workspace from {source} to {destination}. Do not close this window.")
    try:
        if destination.exists() and not any(destination.iterdir()):
            # A rename onto an existing folder would nest the workspace inside it, not become it.
            destination.rmdir()
        destination.parent.mkdir(parents=True, exist_ok=True)
        left_behind = _move_tree(source, destination)
    except (OSError, shutil.Error) as error:
        save(configuration)
        return (
            f"the workspace could not be moved to {destination}: {error}. It is still at {source}"
        )
    configuration.workspace_directory = str(destination)
    save(configuration)
    if left_behind is not None:
        # Every byte arrived, so the workspace really is at the destination and the setting has to
        # say so. Only the tidying up failed, and that is the researcher's to finish.
        return (
            f"the workspace was copied to {destination}, but the old copy at {source} could not be "
            f"removed ({left_behind}). Delete it by hand once nothing is holding those files"
        )
    return f"the workspace was moved to {destination}"


def _move_tree(source: Path, destination: Path) -> str | None:
    """Move a directory, keeping the original readable until the new one is complete.

    Returns None after a clean move, or why the original could not be deleted once the copy had
    succeeded. It never leaves both copies incomplete: within one volume this is a rename, and
    across volumes nothing at the source is touched until every byte has arrived at the destination.
    A partial copy is removed, because a half-written workspace beside an intact one is the state
    most likely to be mistaken for the real thing.
    """
    if _same_volume(source, destination):
        source.rename(destination)
        return None
    try:
        shutil.copytree(source, destination)
    except (OSError, shutil.Error):
        shutil.rmtree(destination, ignore_errors=True)
        raise
    try:
        shutil.rmtree(source)
    except OSError as error:
        return str(error)
    return None


def open_in_file_manager(path: Path) -> None:
    """Show a folder in the desktop's own file manager."""
    if not path.exists():
        raise ConfigurationError(f"'{path}' does not exist")
    if sys.platform == "win32":
        command = ["explorer", str(path)]
    elif sys.platform == "darwin":
        command = ["open", str(path)]
    else:
        command = ["xdg-open", str(path)]
    try:
        # Explorer reports "1" on success, so the return code is deliberately not checked.
        subprocess.Popen(command)  # noqa: S603 - fixed command, path from local configuration
    except OSError as error:
        raise ConfigurationError(f"no file manager could be started: {error}") from error


def view(
    *,
    active_workspace: Path,
    workspace_source: PathSource,
    data_source: PathSource | None = None,
) -> ConfigurationView:
    """Describe the installation as the settings page shows it.

    ``active_workspace`` is the folder the running server actually opened, which is not always the
    configured one: a change made in this session applies at the next start, and the page has to be
    able to say so.
    """
    configuration = load()
    configured_workspace, configured_source = resolve_workspace_directory(
        configuration=configuration
    )
    data_directory, resolved_data_source = resolve_data_directory(configuration=configuration)
    return ConfigurationView(
        configuration_path=str(configuration_path()),
        workspace=DirectoryLocation(
            path=str(active_workspace),
            source=workspace_source,
            exists=active_workspace.is_dir(),
            volume=volume_usage(active_workspace),
        ),
        configured_workspace=DirectoryLocation(
            path=str(configured_workspace),
            source=configured_source,
            exists=configured_workspace.is_dir(),
            volume=volume_usage(configured_workspace),
        ),
        data_directory=DirectoryLocation(
            path=str(data_directory),
            source=data_source or resolved_data_source,
            exists=data_directory.is_dir(),
            volume=volume_usage(data_directory),
        ),
        port=configuration.port,
        open_browser=configuration.open_browser,
        pending_relocation=configuration.pending_relocation,
        # Only when a restart would actually change something. A session launched with an explicit
        # workspace keeps it across a restart, so offering one there would be a promise the
        # application cannot keep; the page says the launch option wins instead.
        restart_required=configuration.pending_relocation is not None
        or (
            workspace_source not in {"command-line", "environment"}
            and configured_workspace != active_workspace
        ),
        supervised=os.environ.get(SUPERVISED_VARIABLE) == "1",
        volumes=available_volumes(),
    )
