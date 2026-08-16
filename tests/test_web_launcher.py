from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.application import configuration as config
from smart_home_sim.web import launcher


class _Server:
    """Stands in for uvicorn's server: records that it ran, and honours a shutdown request."""

    instances: list[_Server] = []

    def __init__(self, configuration: Any) -> None:
        self.configuration = configuration
        self.should_exit = False
        self.ran = False
        _Server.instances.append(self)

    def run(self) -> None:
        self.ran = True


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[_Server]:
    _Server.instances = []
    monkeypatch.setattr(launcher.uvicorn, "Server", _Server)
    monkeypatch.setattr(launcher.uvicorn, "Config", lambda app, **options: {"app": app, **options})
    return _Server.instances


def test_launcher_builds_loopback_app_and_opens_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[_Server]
) -> None:
    workspace = tmp_path / "workspace"
    opened: list[str] = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smart-home-sim-app",
            "--workspace",
            str(workspace),
            "--name",
            "Launcher test",
            "--port",
            "9123",
        ],
    )
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)

    assert launcher.main() == 0

    assert opened == ["http://127.0.0.1:9123"]
    assert served[0].configuration["host"] == "127.0.0.1"
    assert served[0].configuration["port"] == 9123
    assert served[0].ran is True
    assert workspace.joinpath("workspace.sqlite3").is_file()


def test_launcher_no_browser_and_invalid_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[_Server]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smart-home-sim-app", "--workspace", str(tmp_path / "workspace"), "--no-browser"],
    )
    assert launcher.main() == 0
    assert opened == []

    monkeypatch.setattr(sys, "argv", ["smart-home-sim-app", "--port", "0"])
    with pytest.raises(SystemExit, match="2"):
        launcher.main()


def test_the_launcher_opens_the_folder_and_port_the_settings_page_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[_Server]
) -> None:
    saved = tmp_path / "second-drive" / "workspace"
    config.save(
        config.StoredConfiguration(workspace_directory=str(saved), port=9200, open_browser=False)
    )
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", ["smart-home-sim-app"])

    assert launcher.main() == 0

    assert saved.joinpath("workspace.sqlite3").is_file()
    assert served[0].configuration["port"] == 9200
    # The saved preference is honoured without anyone having to pass --no-browser.
    assert opened == []


def test_a_move_agreed_earlier_happens_before_the_workspace_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[_Server], capsys: Any
) -> None:
    source = tmp_path / "old-drive" / "workspace"
    source.mkdir(parents=True)
    (source / "workspace.sqlite3").write_bytes(b"")
    (source / "runs").mkdir()
    (source / "runs" / "trace.jsonl").write_text("{}", encoding="utf-8")
    destination = tmp_path / "new-drive" / "workspace"
    config.save(config.StoredConfiguration(workspace_directory=str(source)))
    config.request_relocation(source, str(destination))

    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(sys, "argv", ["smart-home-sim-app", "--no-browser"])

    assert launcher.main() == 0

    assert (destination / "runs" / "trace.jsonl").is_file()
    assert not source.exists()
    assert config.load().workspace_directory == str(destination)
    assert str(destination) in capsys.readouterr().out


def test_the_settings_page_can_stop_the_server_so_its_supervisor_starts_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[_Server]
) -> None:
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smart-home-sim-app", "--workspace", str(tmp_path / "workspace"), "--no-browser"],
    )

    def restart_while_running(self: _Server) -> None:
        self.ran = True
        self.configuration["app"].state.request_restart()

    monkeypatch.setattr(_Server, "run", restart_while_running)

    assert launcher.main() == config.RESTART_EXIT_CODE
    assert served[0].should_exit is True
