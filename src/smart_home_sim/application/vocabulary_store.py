"""Where a workspace keeps its edited vocabulary.

One file, one pack, one workspace. It is not content-addressed like a run's artifacts, because
those are immutable evidence and this is a document the researcher is still writing: it wants a
stable path that the editor overwrites and the next run reads, not a new digest per keystroke. The
digest still matters and is still recorded — by the run, in its provenance, so a dataset can say
which vocabulary produced it.

Absent file means "the built-in vocabulary", which is what makes reset a deletion rather than a
copy of the defaults: there is then no stale duplicate to drift from the bundled catalogs when they
are next revised.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smart_home_sim.domain.vocabulary import VocabularyPack
from smart_home_sim.vocabulary.active import load_pack, save_pack, set_active_pack
from smart_home_sim.vocabulary.defaults import builtin_pack

PACK_DIRECTORY = "vocabulary"
PACK_FILENAME = "pack.json"


class VocabularyStoreError(RuntimeError):
    """The stored pack could not be read, and a run must not silently fall back to the default."""


@dataclass(frozen=True, slots=True)
class StoredVocabulary:
    pack: VocabularyPack
    # False means nothing is stored and this is the bundled vocabulary. The editor shows it, and
    # `reset` is disabled, because there is nothing to reset to.
    customised: bool


def pack_path(workspace_root: Path) -> Path:
    return workspace_root / PACK_DIRECTORY / PACK_FILENAME


def load(workspace_root: Path) -> StoredVocabulary:
    """The vocabulary this workspace runs on.

    A stored file that will not parse raises rather than falling back. Quietly running on the
    built-in vocabulary when the researcher believes their edits are in force would produce a
    dataset labelled with one vocabulary and generated with another, which is the worst outcome
    available here.
    """
    path = pack_path(workspace_root)
    if not path.exists():
        return StoredVocabulary(pack=builtin_pack(), customised=False)
    try:
        return StoredVocabulary(pack=load_pack(path), customised=True)
    except (OSError, ValueError) as error:
        raise VocabularyStoreError(
            f"the stored vocabulary at {path} cannot be read: {error}"
        ) from error


def save(workspace_root: Path, pack: VocabularyPack) -> StoredVocabulary:
    save_pack(pack, pack_path(workspace_root))
    return StoredVocabulary(pack=pack, customised=True)


def reset(workspace_root: Path) -> StoredVocabulary:
    """Forget the edits and go back to the vocabulary the simulator ships with."""
    path = pack_path(workspace_root)
    path.unlink(missing_ok=True)
    return StoredVocabulary(pack=builtin_pack(), customised=False)


def adopt(workspace_root: Path) -> VocabularyPack:
    """Make this workspace's vocabulary the one this process runs on.

    Every worker calls this before it does any work. Workers are separate processes — a job manager
    hands a root and a job id to a fresh interpreter — so adopting in the API process would not
    reach them, and a run would be generated on the built-in vocabulary while the editor showed the
    researcher their own.

    Returns the pack so the caller can record its digest alongside the run.
    """
    stored = load(workspace_root)
    set_active_pack(stored.pack if stored.customised else None)
    return stored.pack
