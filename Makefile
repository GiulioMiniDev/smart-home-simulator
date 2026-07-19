.PHONY: sync validate schema test lint check

sync:
	UV_NO_EDITABLE=1 uv sync

validate:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_week.json

schema:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --output schemas/scenario-1.0.0.schema.json
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run smart-home-sim schema --contract validation-report --output schemas/validation-report-1.0.0.schema.json

test:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run pytest

lint:
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff check .
	PYTHONPATH=src UV_NO_EDITABLE=1 uv run ruff format --check .

check: test lint validate schema
