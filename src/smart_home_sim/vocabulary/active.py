"""Which vocabulary pack this process is running on.

The engine reads its vocabulary from module-level constants in a dozen places, and threading a pack
argument through every one of them would touch far more code than the change is worth — and would
still leave the question of who supplies it at the bottom of a call stack that starts in a CLI
command. So the pack is resolved here, once, and the call sites ask for it.

That makes it process state, which is worth being honest about. Three things keep it safe:

- **The default is the built-in pack**, so a process that never sets one behaves exactly as before.
- **It is set once, early** — by the CLI before a command runs, by the job worker before a run
  starts — and `use_pack` exists for tests and for the API, which needs to validate a candidate
  pack without adopting it.
- **A run records the digest of whatever was active**, so a dataset can always say what vocabulary
  produced it. Determinism is a property of a run, not of the module; the same pack and the same
  seed give the same output whichever process they meet in.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from smart_home_sim.domain.vocabulary import VocabularyPack

_active: VocabularyPack | None = None


def active_pack() -> VocabularyPack:
    """The pack this process runs on — the built-in one until something says otherwise."""
    if _active is not None:
        return _active
    # Imported here rather than at module scope: `defaults` reads the very tables that the modules
    # importing *this* one own, so a top-level import would close a cycle.
    from smart_home_sim.vocabulary.defaults import builtin_pack

    return builtin_pack()


def set_active_pack(pack: VocabularyPack | None) -> None:
    """Adopt a pack for the rest of this process, or `None` to fall back to the built-in one."""
    global _active
    _active = pack


def load_pack(path: Path) -> VocabularyPack:
    """Read a pack from disk, strictly.

    `ContractModel` is strict, so the document is parsed from JSON text rather than from a dict:
    a bare `"string"` only becomes a `ValueType` on the way through the JSON parser.
    """
    return VocabularyPack.model_validate_json(path.read_text(encoding="utf-8"))


def save_pack(pack: VocabularyPack, path: Path) -> None:
    """Write a pack where a reader will either see the old one or the new one, never half of each.

    An editor that autosaves writes far more often than anything reads, and a crash mid-write on
    the file the next run depends on would be the worst possible failure: not a lost edit but an
    unparseable vocabulary. The rename is atomic on both platforms this runs on.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.loads(pack.model_dump_json(by_alias=True))
    temporary = path.with_name(f"{path.name}.writing")
    temporary.write_text(
        json.dumps(encoded, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


@contextmanager
def use_pack(pack: VocabularyPack | None) -> Iterator[VocabularyPack]:
    """Run a block on a given pack and put back whatever was active before.

    The API uses this to validate and to report on a candidate pack the researcher has not saved
    yet; tests use it to prove that a changed vocabulary actually reaches the engine.
    """
    global _active
    previous = _active
    _active = pack
    try:
        yield active_pack()
    finally:
        _active = previous
