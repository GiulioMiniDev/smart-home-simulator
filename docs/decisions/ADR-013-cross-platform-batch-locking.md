# ADR-013: Cross-platform batch locking

- **Status:** accepted
- **Date:** 2026-07-21
- **Milestone:** M5.1.1

## Context

ADR-012 required one non-blocking owner for each batch output directory, but its first
implementation imported POSIX `fcntl.flock` directly. That import does not exist on
Windows, which made the orchestrator fail before a batch could start. Windows support is
a product requirement, so it cannot remain deferred to a later milestone.

## Decision

Keep the M5.1 public contracts unchanged and isolate locking behind one project-owned
interface with standard-library operating-system backends:

- macOS and Linux use `fcntl.flock(LOCK_EX | LOCK_NB)`;
- Windows uses `msvcrt.locking(LK_NBLCK)` over one reserved byte;
- both backends translate only lock-contention errors into the same domain exception;
- unexpected I/O errors remain visible rather than being misreported as contention;
- the lock file keeps byte zero reserved and writes diagnostic metadata after it;
- acquisition is non-blocking and release is guaranteed by a context manager;
- CI executes lint, formatting, the full test suite and the parallel benchmark on Python
  3.12 for Windows, macOS and Linux.
- Repository text and generated textual artifacts use canonical UTF-8 with LF newlines;
  Git attributes and explicit writer configuration prevent Windows CRLF translation from
  changing byte-level checksums.

The change is operational: manifest, report, trace, replay and semantic-digest contracts
remain byte-for-byte compatible with M5.1 `1.0.0`.

## Consequences

- Independent batches can execute on all three supported desktop/server platforms.
- Two writers targeting the same experiment root are rejected consistently.
- The platform modules are imported lazily, so importing the package never references an
  unavailable operating-system module.
- Network filesystems may implement byte-range or advisory locks differently; a shared
  multi-host experiment root therefore remains outside M5.1 and belongs to a future
  distributed scheduler decision.
