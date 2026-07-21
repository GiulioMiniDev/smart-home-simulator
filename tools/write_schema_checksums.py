from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).parents[1]


def main() -> None:
    for schema_path in sorted((ROOT / "schemas").glob("*.schema.json")):
        checksum = sha256(schema_path.read_bytes()).hexdigest()
        checksum_path = schema_path.with_suffix(".sha256")
        label = schema_path.name
        if checksum_path.exists():
            existing = checksum_path.read_text(encoding="utf-8").strip().split(maxsplit=1)
            if len(existing) == 2:
                label = existing[1]
        checksum_path.write_text(f"{checksum}  {label}\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
