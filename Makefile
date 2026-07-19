.PHONY: sync validate compile schema test lint check

sync:
	UV_NO_EDITABLE=1 uv sync

validate:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_week.json

compile:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim compile examples/valid/mario_week.json --output examples/compiled/mario_week.plan.json --report-output examples/compiled/mario_week.compilation-report.json

schema:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --output schemas/scenario-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract validation-report --output schemas/validation-report-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract canonical-plan --output schemas/canonical-plan-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract compilation-report --output schemas/compilation-report-1.0.0.schema.json

test:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run pytest

lint:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff check .
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff format --check .

check: test lint validate compile schema
