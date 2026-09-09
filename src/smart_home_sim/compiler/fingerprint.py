"""What actually determines a canonical plan, reduced to one comparable string.

A plan is a function of two things: the scenario document it was compiled from, and the code that
compiled it. The first is already identified — `sourceScenarioSha256` is recorded inside every
plan. The second is not, and cannot be read off the plan either: `CompilerMetadata` declares
`compiler_version: Literal["1.0.0"]` and `solver_version: Literal["9.15.6755"]`, which are
statements about the *contract* the document satisfies, frozen in the schema. `__version__` has
said "1.0.0" since the first commit. So a plan compiled before the time-axis rescale and one
compiled after it carry byte-identical metadata while disagreeing about when the resident wakes up.

That is tolerable as long as nothing reuses a plan. The moment a run may execute a plan some
earlier job compiled, the missing fact becomes load-bearing: a stale plan and a current engine
produce a dataset that is internally consistent, passes every gate, and answers a question nobody
asked. So this derives the fact instead of asking for it — the bytes of the modules that decide
what a plan says, plus the solver they call.

Deliberately coarse. Editing a comment in `solver.py` invalidates the reuse and costs one
recompilation; failing to notice a changed search strategy costs a dataset, and possibly the
measurement built on it before anyone looks twice. The two errors are not the same size, so the
cheap one is the one to make.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Everything that can change `canonical-plan.json` or `compilation-report.json` for a scenario
# whose own bytes have not moved: the solver and its driver, the issue codes their reports carry,
# and the models that decide how the scenario is read and how the two outputs are written.
_DECIDING_MODULES = (
    "compiler/service.py",
    "compiler/solver.py",
    "compiler/issues.py",
    "domain/plan.py",
    "domain/compilation.py",
    "domain/models.py",
)

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def compiler_fingerprint() -> str:
    """A digest of the compiler as it exists in this process, for deciding plan reuse.

    Cached: the source cannot change under a running interpreter in any way that would also be
    picked up by the already-imported modules, so re-reading it would only be able to disagree
    with what is actually executing.
    """
    digest = hashlib.sha256()
    for relative in _DECIDING_MODULES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        # Read as bytes and hash unnormalised: a checkout with different line endings is a
        # different set of bytes but the same program, and treating it as a different compiler
        # only ever causes an extra solve.
        digest.update((_PACKAGE_ROOT / relative).read_bytes())
        digest.update(b"\0")
    try:
        solver = version("ortools")
    except PackageNotFoundError:  # pragma: no cover - ortools is a hard dependency
        solver = "unknown"
    digest.update(f"ortools=={solver}".encode())
    return digest.hexdigest()
