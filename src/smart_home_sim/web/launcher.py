from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

import uvicorn

from smart_home_sim.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the local smart-home research workspace")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd() / "smart-home-workspace",
        help="Persistent workspace directory",
    )
    parser.add_argument("--name", default="Research workspace", help="Name for a new workspace")
    parser.add_argument("--port", type=int, default=8765, help="Loopback TCP port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the local browser")
    arguments = parser.parse_args()
    if not (1 <= arguments.port <= 65535):
        parser.error("port must be between 1 and 65535")
    app = create_app(arguments.workspace, workspace_name=arguments.name)
    if not arguments.no_browser:
        webbrowser.open(f"http://127.0.0.1:{arguments.port}")
    uvicorn.run(app, host="127.0.0.1", port=arguments.port, log_level="info")


if __name__ == "__main__":
    main()
