# Milestone 7 closure audit

## Scope and architecture

M7 delivers the local research application over the frozen M1-M6.1 services. ADR-016
records the loopback FastAPI and React architecture, the SQLite/file persistence split and
the rule that the UI cannot create alternative domain semantics. Public application
contracts `1.0.0` cover workspace manifests, jobs, export manifests and replay verification;
their Draft 2020-12 schemas and SHA-256 checksum files are committed under `schemas/`.

## End-to-end evidence

The application supports the ordinary flow without CLI use or hand-editing JSON:

1. create and search a home workspace;
2. select scenario and personal-process-package files and run the authoritative M3 gate;
3. use scenario-first materialization or import a home/sensor model as an explicit draft;
4. edit plan geometry and every M6 sensor type, including timing, error model and failure
   windows, with selection, keyboard controls, undo/redo, zoom, pan and fit;
5. publish immutable home and sensor revisions only after authoritative validation;
6. queue, monitor, reconnect to and cancel an isolated worker from durable SQLite events;
7. inspect run artifacts, the source-linked ground-truth diary and observable sensor data;
8. opt into the separate oracle mapping and navigate each available simulated cause;
9. replay the persisted trace and verify its M5 semantic digest;
10. stream separate JSONL, CSV and XES role projections and verify/download their manifest;
11. create a portable workspace archive from a consistent SQLite snapshot.

The diary is a projection of the execution trace. It stores no invented behavioral truth.
Observable responses never include identity, activity, action, movement or transition fields;
oracle traversal is a separate query and export role.

## SQLite and recovery evidence

The workspace database contains homes, residents, revisions, jobs, ordered job events,
artifact catalogue entries, exports, replay sessions, normalized validation issues, settings
and forward migration records. WAL, foreign keys, `synchronous=FULL`, a five-second busy
timeout and explicit transactions are enabled per connection, and all read handles close
deterministically.

Artifacts are immutable files addressed and checked by SHA-256. Startup reconciliation detects
missing, changed, unsafe and orphan files. Diagnostic mode blocks publication. Active jobs are
recovered as `interrupted`. Archive export is refused while work is active; archive import
checks encryption, links, duplicate/traversal paths, file count, expanded size, database
presence and every catalogue digest before atomic promotion. Tests cover rollback-relevant
failure paths, corruption, recovery, archive round trip and malicious traversal.

## Export and replay evidence

JSONL and CSV writers emit records incrementally; XES uses a streaming XML generator. All
formats write to staging, fsync, compute count/size/digest and publish one directory atomically.
The manifest binds files to the exact bundle digest, trace semantic digest and seed. Tests cover
CSV quoting, all declared role/format pairs, manifest verification, corrupt files, time filters,
observable/oracle separation and replay digest equality. Replay sessions persist the verified
digest, position and filters without changing the trace.

## Quality gates

The terminal acceptance commands are:

```text
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run lint
cd frontend && npm run build
cd frontend && npm test
cd frontend && npm run e2e
uv run python tools/benchmark_application_workspace.py
uv build
```

Python retains the repository-wide 95% coverage gate. Frontend tests enforce 95% statements
and lines and 90% branches. Playwright runs Chromium against the real packaged backend on
desktop and mobile, checks the durable home journey, evaluates axe without disabling the WCAG
contrast rule and asserts no page-level mobile overflow. CI repeats Python on Windows, macOS
and Linux and runs the Node 20 application job on Linux.

The application benchmark constructs 10,000 catalogued artifacts and 1,000 completed runs,
then measures reopen, search, manifest construction and peak traced memory against explicit
budgets. The production build is force-included in the wheel and the installed
`smart-home-sim-app` entry point serves it from loopback.

The final Windows acceptance run recorded 441 passing Python tests with 95.04% repository-wide
coverage. It recorded 41 passing frontend tests with 100% statements/lines and 90.71% branches.
Playwright recorded three applicable passes and one intentional desktop skip for the mobile-only
overflow assertion; Axe reported no violations. The 10,000/1,000 benchmark measured 0.0148 s
reopen, 0.0198 s search, 0.8214 s manifest construction and 18.17 MiB peak traced memory.
`npm audit` reported zero vulnerabilities after upgrading Vite within major 6 to 6.4.3. Both the
wheel and source distribution built successfully. The wheel contains 11 production frontend
files; a clean-venv installation served a valid session token and the packaged SPA over loopback.

## Frozen result and later work

M7 format and application contracts are frozen at `1.0.0`. M8 owns longitudinal horizons and
Monte Carlo execution. M9 owns empirical calibration and dataset-quality claims. Neither is
required for the complete local M7 authoring, execution, inspection, replay and export flow.
