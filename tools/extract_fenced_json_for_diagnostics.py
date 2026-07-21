"""Extract an exact fenced JSON payload for diagnostics, never as an accepted response."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    raw = args.source.read_text(encoding="utf-8")
    prefix = "```json"
    if not raw.startswith(prefix) or not raw.rstrip().endswith("```"):
        raise ValueError("response is not wrapped in one exact ```json fence")
    payload = raw[len(prefix) :].lstrip("\r\n")
    payload = payload.rstrip()
    payload = payload[: -len("```")].rstrip()
    parsed = json.loads(payload)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
