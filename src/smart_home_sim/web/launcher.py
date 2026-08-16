from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from smart_home_sim.application import configuration as configuration_store
from smart_home_sim.web.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the local smart-home research workspace")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Persistent workspace directory (default: the one saved in the settings page)",
    )
    parser.add_argument("--name", default="Research workspace", help="Name for a new workspace")
    parser.add_argument("--port", type=int, default=None, help="Loopback TCP port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the local browser")
    arguments = parser.parse_args()
    if arguments.port is not None and not (1 <= arguments.port <= 65535):
        parser.error("port must be between 1 and 65535")

    # Before anything opens the workspace: a move agreed in the settings page during the previous
    # session happens here, while no database handle and no worker is holding those files.
    moved = configuration_store.apply_pending_relocation(
        lambda message: print(f"[smart-home-simulator] {message}", flush=True)
    )
    if moved is not None:
        print(f"[smart-home-simulator] {moved}", flush=True)

    settings = configuration_store.load()
    workspace, source = configuration_store.resolve_workspace_directory(
        arguments.workspace, configuration=settings
    )
    port = arguments.port if arguments.port is not None else settings.port

    # The restart endpoint needs the server, and the server needs the app: the app is handed a
    # callback that finds the server later, once there is one.
    state: dict[str, Any] = {}

    def request_restart() -> None:
        state["restart"] = True
        server = state.get("server")
        if server is not None:
            server.should_exit = True

    app = create_app(
        workspace,
        workspace_name=arguments.name,
        workspace_source=source,
        on_restart=request_restart,
    )
    print(f"[smart-home-simulator] Workspace: {workspace}", flush=True)
    if settings.open_browser and not arguments.no_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
    state["server"] = server
    server.run()
    return configuration_store.RESTART_EXIT_CODE if state.get("restart") else 0


if __name__ == "__main__":
    raise SystemExit(main())
