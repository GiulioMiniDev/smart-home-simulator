.PHONY: sync validate schema test lint check

sync:
	UV_NO_EDITABLE=1 uv sync

validate:
	UV_NO_EDITABLE=1 uv run smart-home-sim validate examples/valid/mario_two_days.json

schema:
	UV_NO_EDITABLE=1 uv run smart-home-sim schema --output schemas/scenario-0.1.0.schema.json

test:
	UV_NO_EDITABLE=1 uv run pytest

lint:
	UV_NO_EDITABLE=1 uv run ruff check .
	UV_NO_EDITABLE=1 uv run ruff format --check .

check: test lint validate schema

