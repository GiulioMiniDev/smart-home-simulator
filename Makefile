.PHONY: sync validate validate-behavior compile schema behavior-artifacts test lint check

sync:
	UV_NO_EDITABLE=1 uv sync

validate:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_week.json

compile:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim compile examples/valid/mario_week.json --output examples/compiled/mario_week.plan.json --report-output examples/compiled/mario_week.compilation-report.json

validate-behavior:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate-behavior examples/behavior/mario_rossi_week_2026_10_12.behavior.json examples/valid/mario_week.json

behavior-artifacts:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_behavior_artifacts.py
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/build_invalid_behavior_examples.py

schema:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --output schemas/scenario-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract validation-report --output schemas/validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract canonical-plan --output schemas/canonical-plan-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract compilation-report --output schemas/compilation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract activity-catalog --output schemas/activity-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract variable-catalog --output schemas/variable-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract action-catalog --output schemas/action-catalog-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract personal-process-package --output schemas/personal-process-package-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract behavior-validation-report --output schemas/behavior-validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run python tools/write_schema_checksums.py

test:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run pytest

lint:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff check .
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff format --check .

check: behavior-artifacts schema test lint validate compile validate-behavior
