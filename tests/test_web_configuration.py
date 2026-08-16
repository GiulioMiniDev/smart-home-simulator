from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smart_home_sim.application import configuration as config
from smart_home_sim.web import create_app


def _client(workspace: Path, **options: object) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(create_app(workspace, workspace_name="Settings acceptance", **options))
    token = client.get("/api/session").json()["token"]
    return client, {"X-Workspace-Token": token}


def test_the_settings_page_is_told_where_everything_is(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace)
    with client:
        assert client.get("/api/configuration").status_code == 401
        payload = client.get("/api/configuration", headers=headers).json()

        assert Path(payload["workspace"]["path"]) == workspace.resolve()
        assert payload["workspace"]["source"] == "command-line"
        assert payload["workspace"]["volume"]["freeBytes"] > 0
        assert payload["port"] == config.DEFAULT_PORT
        assert payload["openBrowser"] is True
        assert payload["pendingRelocation"] is None
        assert payload["volumes"]
        assert Path(payload["configurationPath"]).name == "configuration.json"


def test_the_disk_usage_breakdown_covers_the_whole_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace)
    with client:
        (workspace / "exports" / "dataset").mkdir(parents=True)
        (workspace / "exports" / "dataset" / "log.csv").write_bytes(b"0" * 4096)

        report = client.get("/api/configuration/storage", headers=headers).json()

        assert report["exists"] is True
        entries = {entry["relativePath"]: entry for entry in report["entries"]}
        assert entries["exports"]["sizeBytes"] == 4096
        assert entries["exports"]["fileCount"] == 1
        assert report["totalBytes"] == sum(entry["sizeBytes"] for entry in report["entries"])
        assert report["volume"]["root"]


def test_a_destination_is_checked_while_the_researcher_is_still_typing(tmp_path: Path) -> None:
    client, headers = _client(tmp_path / "workspace")
    with client:
        rejected = client.post(
            "/api/configuration/destination", headers=headers, json={"path": "somewhere/relative"}
        ).json()
        assert rejected["usable"] is False
        assert "complete path" in rejected["message"]

        accepted = client.post(
            "/api/configuration/destination",
            headers=headers,
            json={"path": str(tmp_path / "second-drive")},
        ).json()
        assert accepted["usable"] is True
        assert accepted["empty"] is True
        assert accepted["volume"]["freeBytes"] > 0


def test_saving_a_new_location_changes_nothing_on_disk_until_the_next_start(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace, workspace_source="default")
    with client:
        elsewhere = tmp_path / "elsewhere"
        response = client.put(
            "/api/configuration",
            headers=headers,
            json={"workspace_directory": str(elsewhere), "port": 9300, "open_browser": False},
        )

        assert response.status_code == 200
        payload = response.json()
        assert Path(payload["configuredWorkspace"]["path"]) == elsewhere
        assert Path(payload["workspace"]["path"]) == workspace.resolve()
        assert payload["restartRequired"] is True
        assert payload["port"] == 9300
        assert payload["openBrowser"] is False
        # The workspace in use is untouched, and the next start will read the saved folder.
        assert (workspace / "workspace.sqlite3").is_file()
        assert not elsewhere.exists()
        assert config.load().workspace_directory == str(elsewhere)


def test_a_session_launched_with_an_explicit_folder_is_not_offered_a_pointless_restart(
    tmp_path: Path,
) -> None:
    """A restart re-runs the same launch options, so the explicit folder would simply come back."""
    client, headers = _client(tmp_path / "chosen-on-the-command-line")
    with client:
        payload = client.put(
            "/api/configuration",
            headers=headers,
            json={"workspace_directory": str(tmp_path / "saved")},
        ).json()

        assert payload["workspace"]["source"] == "command-line"
        assert Path(payload["configuredWorkspace"]["path"]) == tmp_path / "saved"
        assert payload["restartRequired"] is False


def test_the_application_folder_can_be_moved_off_the_system_drive_too(tmp_path: Path) -> None:
    client, headers = _client(tmp_path / "workspace")
    with client:
        elsewhere = tmp_path / "second-drive" / "smart-home-simulator"
        payload = client.put(
            "/api/configuration", headers=headers, json={"data_directory": str(elsewhere)}
        ).json()

        assert Path(payload["dataDirectory"]["path"]) == elsewhere
        assert payload["dataDirectory"]["source"] == "configuration"
        assert payload["dataDirectory"]["exists"] is False
        assert config.load().data_directory == str(elsewhere)

        refused = client.put(
            "/api/configuration", headers=headers, json={"data_directory": "still/relative"}
        )
        assert refused.status_code == 409


def test_an_impossible_location_is_refused_with_the_reason_the_page_shows(tmp_path: Path) -> None:
    client, headers = _client(tmp_path / "workspace")
    with client:
        response = client.put(
            "/api/configuration", headers=headers, json={"workspace_directory": "not/absolute"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFIGURATION_REJECTED"
        assert "complete path" in response.json()["error"]["message"]
        assert config.load().workspace_directory is None


def test_a_move_is_agreed_and_can_be_taken_back(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace)
    with client:
        destination = tmp_path / "second-drive" / "workspace"
        agreed = client.post(
            "/api/configuration/relocation", headers=headers, json={"destination": str(destination)}
        )

        assert agreed.status_code == 200
        assert agreed.json()["pendingRelocation"]["destination"] == str(destination)
        assert agreed.json()["restartRequired"] is True
        assert (workspace / "workspace.sqlite3").is_file()
        assert not destination.exists()

        cancelled = client.delete("/api/configuration/relocation", headers=headers)
        assert cancelled.json()["pendingRelocation"] is None

        refused = client.post(
            "/api/configuration/relocation",
            headers=headers,
            json={"destination": str(workspace / "runs")},
        )
        assert refused.status_code == 409
        assert "inside the current workspace" in refused.json()["error"]["message"]


def test_the_workspace_is_not_moved_out_from_under_a_running_job(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace)
    with client:
        home_id = client.post(
            "/api/homes", headers=headers, json={"name": "Busy", "description": ""}
        ).json()["homeId"]
        service = client.app.state.workspace
        service.create_job("materialization", home_id=home_id)

        response = client.post(
            "/api/configuration/relocation",
            headers=headers,
            json={"destination": str(tmp_path / "elsewhere")},
        )

        assert response.status_code == 409
        assert "active jobs" in response.json()["error"]["message"]


def test_a_folder_can_be_opened_in_the_desktop_file_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[Path] = []
    monkeypatch.setattr(config, "open_in_file_manager", shown.append)
    workspace = tmp_path / "workspace"
    client, headers = _client(workspace)
    with client:
        for kind, expected in (
            ("workspace", workspace),
            ("exports", workspace / "exports"),
            ("runs", workspace / "runs"),
            ("configuration", config.configuration_path().parent),
        ):
            response = client.post(
                "/api/configuration/reveal", headers=headers, json={"kind": kind}
            )
            assert response.status_code == 200, kind
            assert Path(response.json()["revealed"]) == expected.resolve(), kind

        escape = client.post(
            "/api/configuration/reveal",
            headers=headers,
            json={"kind": "run", "identifier": "../../.."},
        )
        assert escape.status_code == 404


def test_a_restart_is_offered_only_when_something_can_perform_it(tmp_path: Path) -> None:
    unsupervised, headers = _client(tmp_path / "alone")
    with unsupervised:
        response = unsupervised.post("/api/configuration/restart", headers=headers)
        assert response.status_code == 409
        assert "close its window" in response.json()["error"]["message"]

    asked: list[bool] = []
    supervised, headers = _client(tmp_path / "supervised", on_restart=lambda: asked.append(True))
    with supervised:
        response = supervised.post("/api/configuration/restart", headers=headers)
        assert response.status_code == 202
        assert asked == [True]
