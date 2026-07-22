from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
PACKAGE_NAME = "smart-home-simulator"
MINIMUM_NODE_MAJOR = 20


class BootstrapError(RuntimeError):
    pass


def _status(message: str) -> None:
    print(f"[smart-home-simulator] {message}", flush=True)


def _run(
    command: list[str],
    *,
    cwd: Path = PROJECT_ROOT,
    environment: dict[str, str] | None = None,
) -> None:
    _status("Eseguo: " + " ".join(command))
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def _executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise BootstrapError(f"comando richiesto non trovato: {name}")
    return resolved


def _node_tools() -> tuple[str, str]:
    node = _executable("node")
    npm = _executable("npm")
    result = subprocess.run(
        [node, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = result.stdout.strip().lstrip("v")
    try:
        major = int(rendered.split(".", maxsplit=1)[0])
    except ValueError as error:
        raise BootstrapError(f"versione Node.js non riconosciuta: {rendered}") from error
    if major < MINIMUM_NODE_MAJOR:
        raise BootstrapError(
            f"serve Node.js >= {MINIMUM_NODE_MAJOR}; versione rilevata: {rendered}"
        )
    return node, npm


def _data_root(override: Path | None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    configured = os.environ.get("SMART_HOME_SIM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".smart-home-simulator"


def _files(roots: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for root in roots:
        if root.is_file():
            result.append(root)
        elif root.is_dir():
            result.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.name != ".DS_Store"
                and path.suffix not in {".pyc", ".pyo"}
            )
    return sorted(result)


def _fingerprint(roots: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in _files(roots):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _application_executable(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "smart-home-sim-app.exe"
    return venv / "bin" / "smart-home-sim-app"


def _frontend_fingerprint() -> str:
    inputs = [
        FRONTEND_ROOT / "index.html",
        FRONTEND_ROOT / "package.json",
        FRONTEND_ROOT / "package-lock.json",
        FRONTEND_ROOT / "src",
        FRONTEND_ROOT / "tsconfig.app.json",
        FRONTEND_ROOT / "tsconfig.json",
        FRONTEND_ROOT / "tsconfig.test.json",
        FRONTEND_ROOT / "vite.config.ts",
    ]
    return _fingerprint(inputs)


def _python_fingerprint() -> str:
    return _fingerprint(
        [
            PROJECT_ROOT / "pyproject.toml",
            PROJECT_ROOT / "uv.lock",
            PROJECT_ROOT / "src",
            FRONTEND_ROOT / "dist",
        ]
    )


def _configure_frontend(
    state: dict[str, Any], *, npm: str, force: bool
) -> None:
    lock_digest = _fingerprint([FRONTEND_ROOT / "package-lock.json"])
    dependencies_missing = not (FRONTEND_ROOT / "node_modules").is_dir()
    if force or dependencies_missing or state.get("frontendLock") != lock_digest:
        _status("Configuro le dipendenze frontend.")
        _run([npm, "ci"], cwd=FRONTEND_ROOT)

    source_digest = _frontend_fingerprint()
    build_missing = not (FRONTEND_ROOT / "dist" / "index.html").is_file()
    if force or build_missing or state.get("frontendSource") != source_digest:
        _status("Costruisco il frontend.")
        _run([npm, "run", "build"], cwd=FRONTEND_ROOT)

    state["frontendLock"] = lock_digest
    state["frontendSource"] = source_digest


def _configure_python(
    state: dict[str, Any], *, uv: str, venv: Path, force: bool
) -> None:
    source_digest = _python_fingerprint()
    application = _application_executable(venv)
    if force or not application.is_file() or state.get("pythonSource") != source_digest:
        _status(f"Configuro l'ambiente Python in {venv}.")
        environment = os.environ.copy()
        environment["UV_PROJECT_ENVIRONMENT"] = str(venv)
        environment["UV_NO_EDITABLE"] = "1"
        _run(
            [
                uv,
                "sync",
                "--locked",
                "--reinstall-package",
                PACKAGE_NAME,
            ],
            environment=environment,
        )
    state["pythonSource"] = source_digest


def _tcp_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _simulator_responds(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/session", timeout=1
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and isinstance(payload.get("token"), str)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _launch(
    application: Path,
    *,
    workspace: Path,
    name: str,
    port: int,
    no_browser: bool,
) -> int:
    url = f"http://127.0.0.1:{port}/"
    if _tcp_port_open(port):
        if not _simulator_responds(port):
            raise BootstrapError(f"la porta {port} è già usata da un'altra applicazione")
        _status(f"Il simulatore è già attivo: {url}")
        if not no_browser:
            webbrowser.open(url)
        return 0

    workspace.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(application),
        "--workspace",
        str(workspace),
        "--name",
        name,
        "--port",
        str(port),
    ]
    if no_browser:
        command.append("--no-browser")
    _status(f"Avvio su {url}. Premi Ctrl+C per arrestare.")
    try:
        return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode
    except KeyboardInterrupt:
        _status("Arresto richiesto.")
        return 130


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configura e avvia Smart Home Simulator con un solo comando."
    )
    parser.add_argument("--name", default="Smart Home Simulator")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="reinstalla dipendenze e ricostruisce gli artefatti locali",
    )
    parser.add_argument(
        "--configure-only",
        action="store_true",
        help="configura senza avviare il server",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    if not 1 <= arguments.port <= 65535:
        raise BootstrapError("la porta deve essere compresa tra 1 e 65535")

    system = platform.system() or "Unknown"
    _status(f"Piattaforma rilevata: {system} ({platform.machine()}).")
    data_root = _data_root(arguments.data_dir)
    venv = data_root / "venv"
    workspace = (
        arguments.workspace.expanduser().resolve()
        if arguments.workspace is not None
        else data_root / "workspace"
    )
    state_path = data_root / "bootstrap-state.json"
    state = _load_state(state_path)

    try:
        uv = _executable("uv")
    except BootstrapError as error:
        raise BootstrapError(
            f"{error}. Installa uv da https://docs.astral.sh/uv/getting-started/installation/"
        ) from error
    try:
        _, npm = _node_tools()
    except BootstrapError as error:
        raise BootstrapError(
            f"{error}. Installa Node.js LTS da https://nodejs.org/"
        ) from error

    _configure_frontend(state, npm=npm, force=arguments.reconfigure)
    _configure_python(state, uv=uv, venv=venv, force=arguments.reconfigure)
    state.update({"platform": system, "projectRoot": str(PROJECT_ROOT)})
    _save_state(state_path, state)
    _status("Configurazione pronta.")

    if arguments.configure_only:
        return 0
    return _launch(
        _application_executable(venv),
        workspace=workspace,
        name=arguments.name,
        port=arguments.port,
        no_browser=arguments.no_browser,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BootstrapError, subprocess.CalledProcessError) as error:
        print(f"[smart-home-simulator] ERRORE: {error}", file=sys.stderr)
        raise SystemExit(1) from error
