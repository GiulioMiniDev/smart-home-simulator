# ADR-016: Local web application and SQLite workspace

- **Status:** accepted and implemented in M7
- **Date:** 2026-07-22

## Context

M1-M6.1 expose deterministic headless services and immutable scientific artifacts. M7
needs a complete graphical workflow without introducing a cloud authority, duplicating
domain semantics or storing large traces as database blobs.

## Decision

Ship a loopback-only FastAPI service and a React/TypeScript client in the Python wheel.
The browser receives an ephemeral session token and uses REST for commands and queries and
SSE for durable job events. Long simulation work runs in isolated local processes.

SQLite is the transactional application index. It stores workspace identity and settings,
homes, residents, immutable revision relationships, jobs and ordered events, artifact
metadata, export requests, replay sessions and normalized validation issues. WAL, foreign
keys, full synchronous commits, a busy timeout, forward-only migrations and explicit
transactions are mandatory. Every read connection is explicitly closed.

Large scientific data stays under workspace-relative paths in `objects/`, `runs/` and
`exports/`. Catalogue rows contain size and SHA-256. Writes use staging and atomic rename;
startup reconciliation places a corrupt workspace in diagnostic mode and blocks new
publication. A portable `.shw` archive is a verified SQLite snapshot plus the immutable
files. It is refused while jobs are active and import rejects traversal, links, encryption,
duplicates and configured size/count limits.

The application layer remains independent of FastAPI and React. Observable and oracle
queries and export writers use separate entry points. The ground-truth diary is a
projection of the persisted execution trace and every row retains its source identifiers.

## Consequences

- Closing or refreshing the UI cannot lose accepted inputs, progress or completed work.
- SQLite remains small and queryable while scientific artifacts remain streamable.
- The same frozen validators and engines serve CLI and UI, preserving deterministic digests.
- Recovery is explicit: corrupt data is never silently accepted or overwritten.
- Collaboration, remote accounts and cloud synchronization remain outside M7.
