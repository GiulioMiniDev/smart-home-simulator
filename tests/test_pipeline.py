from __future__ import annotations

import json
import types
from datetime import date

from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig, LMStudioError
from smart_home_sim.hybrid_planning.pipeline import STAGES, run_generation

runner = CliRunner()

_PERSONA = json.dumps(
    {
        "name": "Elena Bruni",
        "age": 72,
        "sex": "F",
        "occupation": "retired teacher",
        "household": "lives alone",
        "health": ["arthritis"],
        "city": "Bologna",
        "notes": "quiet, routine-driven",
        "routine_anchors": ["morning coffee", "evening pill"],
    }
)

def _h(label: str, kind: str, frequency: str, band: str) -> dict[str, str]:
    return {"label": label, "kind": kind, "frequency": frequency, "time_band": band}


_HABITS = json.dumps(
    {
        "habits": [
            _h("morning coffee", "anchor", "daily", "early_morning"),
            _h("evening pill", "anchor", "daily", "evening"),
            _h("morning walk", "anchor", "daily", "morning"),
            _h("groceries", "contextual", "weekly", "morning"),
            _h("laundry", "contextual", "weekly", "afternoon"),
            _h("call friend", "optional", "few_times_week", "evening"),
            _h("cinema", "optional", "biweekly", "evening"),
            _h("doctor visit", "rare", "monthly", "morning"),
        ]
    }
)

_DAYS = json.dumps(
    {
        "days": [
            {"date": "2026-08-03", "timeline": [{"intent": "eat_breakfast", "around": "07:30"}]},
            {"date": "2026-08-04", "timeline": [{"intent": "eat_lunch", "around": "12:30"}]},
        ]
    }
)


def _pipeline_client() -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        text = " ".join(
            message["content"] for message in json.loads(body)["messages"]
        ).lower()
        if "invent one coherent person" in text:
            reply = _PERSONA
        elif "daily-habit portfolio" in text:
            reply = _HABITS
        elif "plan each of these days" in text:
            reply = _DAYS
        else:
            reply = "{}"
        return json.dumps({"choices": [{"message": {"content": reply}, "finish_reason": "stop"}]})

    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


def _assert_all_artifacts(output_dir) -> None:
    for name in (
        "persona.json",
        "behavioral-profile.json",
        "planning-world.json",
        "personal-process-package.json",
        "cadence-calendar.json",
        "batch-manifest.json",
        "planned-habit-trace.json",
    ):
        assert (output_dir / name).exists(), name


def test_run_generation_deterministic_days(tmp_path) -> None:
    result = run_generation(
        "an elderly woman living alone",
        tmp_path,
        _pipeline_client(),
        start_date=date(2026, 8, 3),
        months=1,
        days=2,
        seed=1,
    )
    assert result.day_count == 2
    _assert_all_artifacts(tmp_path)
    persona = json.loads((tmp_path / "persona.json").read_text(encoding="utf-8"))
    assert persona["personaId"] == "elena_bruni"


def test_run_generation_with_llm_days_and_progress(tmp_path) -> None:
    stages: list[str] = []

    result = run_generation(
        "an elderly woman living alone",
        tmp_path,
        _pipeline_client(),
        start_date=date(2026, 8, 3),
        months=1,
        days=2,
        use_llm_days=True,
        use_llm_package=False,
        seed=1,
        progress=lambda stage, percent, message: stages.append(stage),
    )
    assert result.day_count == 2
    assert stages == list(STAGES)
    _assert_all_artifacts(tmp_path)


def test_cli_generate_dataset(monkeypatch, tmp_path) -> None:
    def fake_run(brief, output_dir, client, *, start_date, months, use_llm_package, use_llm_days,
                 seed, progress):
        progress("persona", 0.0, "inventing")
        return types.SimpleNamespace(manifest_path=tmp_path / "batch-manifest.json", day_count=3)

    monkeypatch.setattr(cli, "run_generation", fake_run)
    result = runner.invoke(
        cli.app,
        [
            "generate-dataset",
            "an elderly woman",
            "-o",
            str(tmp_path / "out"),
            "--start",
            "2026-08-03",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "3 days bundled" in result.output
    assert "simulate-batch" in result.output


def test_cli_generate_dataset_rejects_bad_start(tmp_path) -> None:
    result = runner.invoke(
        cli.app,
        ["generate-dataset", "brief", "-o", str(tmp_path / "out"), "--start", "not-a-date"],
    )
    assert result.exit_code != 0


def test_cli_generate_dataset_reports_failure(monkeypatch, tmp_path) -> None:
    def fake_run(*args, **kwargs):
        raise LMStudioError("endpoint down")

    monkeypatch.setattr(cli, "run_generation", fake_run)
    result = runner.invoke(
        cli.app,
        ["generate-dataset", "brief", "-o", str(tmp_path / "out"), "--start", "2026-08-03"],
    )
    assert result.exit_code == 1
    assert "Generation failed" in result.output
