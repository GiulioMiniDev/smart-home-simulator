from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from smart_home_sim.application import configuration as config


def _workspace(root: Path, *, megabytes: int = 1) -> Path:
    """A folder shaped like a workspace, with something in every part the settings page lists."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace.sqlite3").write_bytes(b"\0" * 1024)
    for name in ("objects", "runs", "exports", "staging"):
        (root / name).mkdir()
    (root / "runs" / "trace.jsonl").write_bytes(b"\0" * (megabytes * 1024 * 1024))
    (root / "exports" / "dataset.csv").write_bytes(b"\0" * 2048)
    (root / "server-errors.log").write_text("noise", encoding="utf-8")
    return root


def test_the_configuration_file_survives_a_round_trip_and_tolerates_damage(
    isolated_application_home: Path,
) -> None:
    assert config.configuration_path() == isolated_application_home / "configuration.json"
    assert config.load().workspace_directory is None

    config.save(
        config.StoredConfiguration(workspace_directory="D:/research", port=9100, open_browser=False)
    )
    reloaded = config.load()
    assert reloaded.workspace_directory == "D:/research"
    assert reloaded.port == 9100
    assert reloaded.open_browser is False
    # Written under the names the browser and the bootstrap script both read.
    assert '"workspaceDirectory"' in config.configuration_path().read_text(encoding="utf-8")

    for damage in ("{not json", '"a string"', '{"port": 999999}'):
        config.configuration_path().write_text(damage, encoding="utf-8")
        assert config.load().port == config.DEFAULT_PORT, damage


def test_an_unreadable_configuration_never_stops_the_application(
    isolated_application_home: Path,
) -> None:
    shutil.rmtree(isolated_application_home)
    assert config.load().workspace_directory is None


def test_each_location_names_what_decided_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_application_home: Path
) -> None:
    assert config.resolve_workspace_directory() == (
        (isolated_application_home / "workspace").resolve(),
        "default",
    )

    config.save(config.StoredConfiguration(workspace_directory=str(tmp_path / "saved")))
    assert config.resolve_workspace_directory() == ((tmp_path / "saved").resolve(), "configuration")

    monkeypatch.setenv("SMART_HOME_SIM_WORKSPACE", str(tmp_path / "environment"))
    assert config.resolve_workspace_directory() == (
        (tmp_path / "environment").resolve(),
        "environment",
    )

    assert config.resolve_workspace_directory(tmp_path / "explicit") == (
        (tmp_path / "explicit").resolve(),
        "command-line",
    )

    monkeypatch.delenv("SMART_HOME_SIM_WORKSPACE")
    monkeypatch.setenv("SMART_HOME_SIM_DATA_DIR", str(tmp_path / "data"))
    assert config.resolve_data_directory() == ((tmp_path / "data").resolve(), "environment")
    assert config.resolve_data_directory(tmp_path / "elsewhere") == (
        (tmp_path / "elsewhere").resolve(),
        "command-line",
    )
    monkeypatch.delenv("SMART_HOME_SIM_DATA_DIR")
    config.save(config.StoredConfiguration(data_directory=str(tmp_path / "saved-data")))
    assert config.resolve_data_directory() == ((tmp_path / "saved-data").resolve(), "configuration")
    # With the data folder moved, the default workspace follows it rather than staying behind.
    assert config.resolve_workspace_directory()[0] == (tmp_path / "saved-data" / "workspace")


def test_the_storage_report_accounts_for_every_file_in_the_folder(tmp_path: Path) -> None:
    missing = config.storage_report(tmp_path / "absent")
    assert missing.exists is False
    assert missing.total_bytes == 0

    root = _workspace(tmp_path / "workspace")
    report = config.storage_report(root)
    assert report.exists is True
    by_path = {entry.relative_path: entry for entry in report.entries}
    assert by_path["runs"].size_bytes == 1024 * 1024
    assert by_path["runs"].file_count == 1
    assert by_path["exports"].size_bytes == 2048
    assert by_path["workspace.sqlite3"].size_bytes == 1024
    assert by_path["generations"].size_bytes == 0
    # The stray log is neither hidden nor mixed into a named part.
    assert by_path["."].name == "Other files"
    assert by_path["."].file_count == 1
    assert report.total_bytes == sum(entry.size_bytes for entry in report.entries)
    assert report.total_bytes == 1024 * 1024 + 2048 + 1024 + len("noise")


def test_a_workspace_with_nothing_beside_it_reports_no_other_files(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    report = config.storage_report(root)
    assert [entry.relative_path for entry in report.entries] == [
        name for name, _, _ in config.WORKSPACE_CONTENTS
    ]
    assert report.total_bytes == 0


def test_volumes_are_reported_with_the_space_left_on_them(tmp_path: Path) -> None:
    usage = config.volume_usage(tmp_path)
    assert usage is not None
    assert usage.total_bytes >= usage.free_bytes > 0
    # A path that does not exist yet still answers, from the nearest folder that does.
    assert config.volume_usage(tmp_path / "not" / "created" / "yet") == usage

    volumes = config.available_volumes()
    assert volumes
    assert len({volume.root for volume in volumes}) == len(volumes)


def test_an_unreadable_volume_is_simply_not_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_: Path) -> None:
        raise OSError("the device is not ready")

    monkeypatch.setattr(config.shutil, "disk_usage", refuse)
    assert config.volume_usage(tmp_path) is None
    assert config.available_volumes() == []


def test_a_candidate_folder_explains_itself_rather_than_failing(tmp_path: Path) -> None:
    current = _workspace(tmp_path / "current")

    assert config.check_destination("  ", current=current).usable is False
    assert "Enter a folder" in config.check_destination("", current=current).message
    assert "complete path" in config.check_destination("relative/folder", current=current).message

    file_path = tmp_path / "a-file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert "is a file" in config.check_destination(str(file_path), current=current).message

    inside = config.check_destination(str(current / "runs"), current=current)
    assert inside.usable is False
    assert "inside the current workspace" in inside.message

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "someone-elses.txt").write_text("x", encoding="utf-8")
    assert (
        "already holds other files"
        in config.check_destination(str(occupied), current=current).message
    )

    fresh = config.check_destination(str(tmp_path / "fresh"), current=current)
    assert fresh.usable is True
    assert fresh.empty is True
    assert fresh.same_volume is True
    # A rename inside one volume needs no free space, whatever the workspace weighs.
    assert (
        config.check_destination(
            str(tmp_path / "fresh"), current=current, required_bytes=2**60
        ).usable
        is True
    )

    existing = _workspace(tmp_path / "already-a-workspace")
    check = config.check_destination(str(existing), current=current)
    assert check.usable is True
    assert check.holds_workspace is True
    assert "will open it" in check.message


def test_a_destination_on_a_full_or_absent_drive_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    monkeypatch.setattr(config, "_nearest_existing", lambda path: None)
    assert (
        "drive is not available"
        in config.check_destination(str(tmp_path / "elsewhere"), current=current).message
    )

    monkeypatch.undo()
    monkeypatch.setattr(config, "_same_volume", lambda first, second: False)
    monkeypatch.setattr(
        config,
        "volume_usage",
        lambda path: config.VolumeUsage(root="Z:\\", total_bytes=100, free_bytes=10),
    )
    tight = config.check_destination(str(tmp_path / "small"), current=current, required_bytes=5_000)
    assert tight.usable is False
    assert "are needed and" in tight.message

    roomy = config.check_destination(str(tmp_path / "small"), current=current, required_bytes=5)
    assert roomy.usable is True
    assert "will be copied" in roomy.message


def test_a_destination_that_cannot_be_written_to_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    monkeypatch.setattr(config, "_writable", lambda directory: False)
    check = config.check_destination(str(tmp_path / "read-only"), current=current)
    assert check.usable is False
    assert "cannot write to" in check.message


def test_a_move_is_recorded_for_the_next_start_rather_than_performed(tmp_path: Path) -> None:
    current = _workspace(tmp_path / "current")
    destination = tmp_path / "moved"

    stored = config.request_relocation(current, str(destination))
    assert stored.pending_relocation is not None
    assert stored.pending_relocation.destination == str(destination)
    # Nothing has been touched: this is a note for the next start, not the move itself.
    assert (current / "workspace.sqlite3").is_file()
    assert not destination.exists()
    assert config.load().pending_relocation == stored.pending_relocation

    assert config.cancel_relocation().pending_relocation is None
    assert config.load().pending_relocation is None


def test_a_move_that_makes_no_sense_is_refused_with_a_reason(tmp_path: Path) -> None:
    current = _workspace(tmp_path / "current")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "other.txt").write_text("x", encoding="utf-8")

    with pytest.raises(config.ConfigurationError, match="already holds other files"):
        config.request_relocation(current, str(occupied))
    with pytest.raises(config.ConfigurationError, match="A workspace already exists"):
        config.request_relocation(current, str(_workspace(tmp_path / "other-workspace")))
    with pytest.raises(config.ConfigurationError, match="already in that folder"):
        config.request_relocation(current, str(current))
    assert config.load().pending_relocation is None


def test_the_pending_move_happens_at_the_next_start_and_updates_the_setting(
    tmp_path: Path,
) -> None:
    assert config.apply_pending_relocation() is None

    current = _workspace(tmp_path / "current")
    destination = tmp_path / "second-drive" / "workspace"
    config.request_relocation(current, str(destination))

    announced: list[str] = []
    outcome = config.apply_pending_relocation(announced.append)

    assert outcome is not None and str(destination) in outcome
    assert announced and "Moving the workspace" in announced[0]
    assert (destination / "workspace.sqlite3").is_file()
    assert (destination / "runs" / "trace.jsonl").is_file()
    assert not current.exists()
    saved = config.load()
    assert saved.workspace_directory == str(destination)
    assert saved.pending_relocation is None
    assert config.resolve_workspace_directory() == (destination.resolve(), "configuration")


def test_a_move_into_an_empty_folder_replaces_it_instead_of_nesting(tmp_path: Path) -> None:
    current = _workspace(tmp_path / "current")
    destination = tmp_path / "prepared"
    destination.mkdir()
    config.request_relocation(current, str(destination))

    config.apply_pending_relocation()

    assert (destination / "workspace.sqlite3").is_file()
    assert not (destination / "prepared").exists()


def test_a_move_whose_source_vanished_is_reported_and_forgotten(tmp_path: Path) -> None:
    current = _workspace(tmp_path / "current")
    config.request_relocation(current, str(tmp_path / "moved"))
    shutil.rmtree(current)

    outcome = config.apply_pending_relocation()

    assert outcome is not None and "no longer exists" in outcome
    assert config.load().pending_relocation is None


def test_a_failed_move_leaves_the_workspace_where_it_was_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    config.request_relocation(current, str(tmp_path / "moved"))

    def refuse(self: Path, destination: Path) -> None:
        raise OSError("the folder is open in another program")

    monkeypatch.setattr(Path, "rename", refuse)
    outcome = config.apply_pending_relocation()

    assert outcome is not None
    assert "could not be moved" in outcome
    assert str(current) in outcome
    assert (current / "workspace.sqlite3").is_file()
    saved = config.load()
    # The move is forgotten rather than retried forever, and the setting still points at the files.
    assert saved.pending_relocation is None
    assert saved.workspace_directory is None


def test_a_move_across_drives_copies_before_it_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    destination = tmp_path / "other-drive" / "workspace"
    config.request_relocation(current, str(destination))
    # Two folders on one test drive still have to exercise the copy-then-delete path.
    monkeypatch.setattr(config, "_same_volume", lambda first, second: False)

    assert config.apply_pending_relocation() == f"the workspace was moved to {destination}"

    assert (destination / "runs" / "trace.jsonl").is_file()
    assert not current.exists()


def test_a_copy_that_fails_halfway_leaves_only_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    destination = tmp_path / "other-drive" / "workspace"
    config.request_relocation(current, str(destination))
    monkeypatch.setattr(config, "_same_volume", lambda first, second: False)

    def fail_after_writing_something(source: str, target: str) -> None:
        Path(target).mkdir(parents=True)
        (Path(target) / "half-a-run.jsonl").write_text("{", encoding="utf-8")
        raise OSError("the drive was disconnected")

    monkeypatch.setattr(config.shutil, "copytree", fail_after_writing_something)
    outcome = config.apply_pending_relocation()

    assert outcome is not None and "could not be moved" in outcome
    assert (current / "runs" / "trace.jsonl").is_file()
    # No half-written workspace is left beside the real one to be mistaken for it.
    assert not destination.exists()
    assert config.load().workspace_directory is None


def test_a_copy_that_arrived_is_kept_even_when_the_old_folder_cannot_be_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _workspace(tmp_path / "current")
    destination = tmp_path / "other-drive" / "workspace"
    config.request_relocation(current, str(destination))
    monkeypatch.setattr(config, "_same_volume", lambda first, second: False)

    def refuse(path: str) -> None:
        raise OSError("the log file is open in another program")

    monkeypatch.setattr(config.shutil, "rmtree", refuse)
    outcome = config.apply_pending_relocation()

    assert outcome is not None
    assert "could not be removed" in outcome
    assert "Delete it by hand" in outcome
    assert (destination / "runs" / "trace.jsonl").is_file()
    # The data is at the destination, so that is where the application must now look.
    assert config.load().workspace_directory == str(destination)


def test_the_file_manager_is_asked_to_show_a_folder_that_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(config.subprocess, "Popen", lambda command: started.append(command))

    config.open_in_file_manager(tmp_path)

    assert started and str(tmp_path) in started[0]
    with pytest.raises(config.ConfigurationError, match="does not exist"):
        config.open_in_file_manager(tmp_path / "absent")

    def refuse(command: list[str]) -> None:
        raise OSError("no desktop session")

    monkeypatch.setattr(config.subprocess, "Popen", refuse)
    with pytest.raises(config.ConfigurationError, match="no file manager"):
        config.open_in_file_manager(tmp_path)


def test_the_view_separates_the_open_workspace_from_the_configured_one(tmp_path: Path) -> None:
    active = _workspace(tmp_path / "active")

    view = config.view(active_workspace=active, workspace_source="command-line")
    assert view.workspace.path == str(active)
    assert view.workspace.source == "command-line"
    assert view.workspace.exists is True
    assert view.supervised is False
    assert view.volumes
    # A launch option survives a restart, so restarting would change nothing and is not offered
    # even though the configured folder is a different one.
    assert view.configured_workspace.path != str(active)
    assert view.restart_required is False

    config.save(config.StoredConfiguration(workspace_directory=str(tmp_path / "next")))
    assert config.view(active_workspace=active, workspace_source="default").restart_required is True

    config.save(config.StoredConfiguration(workspace_directory=str(active)))
    settled = config.view(active_workspace=active, workspace_source="configuration")
    assert settled.configured_workspace.path == str(active)
    assert settled.restart_required is False

    config.request_relocation(active, str(tmp_path / "next"))
    pending = config.view(active_workspace=active, workspace_source="configuration")
    assert pending.restart_required is True
    assert pending.pending_relocation is not None


def test_a_supervised_process_is_told_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.SUPERVISED_VARIABLE, "1")
    assert config.view(active_workspace=tmp_path, workspace_source="default").supervised is True
