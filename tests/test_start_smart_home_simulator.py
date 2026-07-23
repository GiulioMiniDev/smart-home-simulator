from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "start_smart_home_simulator.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("start_smart_home_simulator", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configure_python_uses_uv_when_available(tmp_path, monkeypatch) -> None:
    module = _load_module()
    state: dict[str, str] = {}
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    monkeypatch.setattr(module, "_python_fingerprint", lambda: "digest-1")
    monkeypatch.setattr(
        module,
        "_application_executable",
        lambda venv: venv / "Scripts" / "smart-home-sim-app.exe",
    )
    monkeypatch.setattr(module, "_status", lambda message: None)
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, cwd=module.PROJECT_ROOT, environment=None: calls.append(
            (command, cwd, environment)
        ),
    )

    module._configure_python(state, uv="uv.exe", venv=tmp_path / "venv", force=False)

    assert calls == [
        (
            ["uv.exe", "sync", "--locked", "--reinstall-package", "smart-home-simulator"],
            module.PROJECT_ROOT,
            {
                "UV_NO_EDITABLE": "1",
                "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv"),
            },
        )
    ]
    assert state == {"pythonInstaller": "uv", "pythonSource": "digest-1"}


def test_configure_python_uses_pip_fallback_when_uv_is_missing(tmp_path, monkeypatch) -> None:
    module = _load_module()
    state: dict[str, str] = {}
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    monkeypatch.setattr(module, "_python_fingerprint", lambda: "digest-2")
    monkeypatch.setattr(
        module,
        "_application_executable",
        lambda venv: venv / "Scripts" / "smart-home-sim-app.exe",
    )
    monkeypatch.setattr(
        module,
        "_venv_python",
        lambda venv: venv / "Scripts" / "python.exe",
    )
    monkeypatch.setattr(module, "_status", lambda message: None)
    monkeypatch.setattr(module.sys, "executable", "C:\\Python312\\python.exe")
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, cwd=module.PROJECT_ROOT, environment=None: calls.append(
            (command, cwd, environment)
        ),
    )

    module._configure_python(state, uv=None, venv=tmp_path / "venv", force=False)

    assert calls == [
        (["C:\\Python312\\python.exe", "-m", "venv", str(tmp_path / "venv")], module.PROJECT_ROOT, None),
        (
            [
                str(tmp_path / "venv" / "Scripts" / "python.exe"),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                ".",
            ],
            module.PROJECT_ROOT,
            None,
        ),
    ]
    assert state == {"pythonInstaller": "pip", "pythonSource": "digest-2"}