from __future__ import annotations

import sys
from pathlib import Path

import pytest

from smart_home_sim.web import launcher


def test_launcher_builds_loopback_app_and_opens_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    opened: list[str] = []
    served: list[tuple[object, str, int, str]] = []
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
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda app, *, host, port, log_level: served.append((app, host, port, log_level)),
    )

    launcher.main()

    assert opened == ["http://127.0.0.1:9123"]
    assert served[0][1:] == ("127.0.0.1", 9123, "info")
    assert workspace.joinpath("workspace.sqlite3").is_file()


def test_launcher_no_browser_and_invalid_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smart-home-sim-app",
            "--workspace",
            str(tmp_path / "workspace"),
            "--no-browser",
        ],
    )
    launcher.main()
    assert opened == []

    monkeypatch.setattr(sys, "argv", ["smart-home-sim-app", "--port", "0"])
    with pytest.raises(SystemExit, match="2"):
        launcher.main()
