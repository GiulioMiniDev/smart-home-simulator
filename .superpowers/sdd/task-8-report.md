# Task 8 report — real replay journey

## Outcome

DONE_WITH_CONCERNS. Task 8 adds a disposable, real-artifact replay workspace, browser acceptance
coverage, replay performance evidence, and operator documentation. It does not change the protected
night, drives, or expander implementation/tests.

## Acceptance evidence

- `frontend/e2e/replay.spec.ts` was written first and failed as intended because
  `reports/e2e-replay-run.json` did not exist. The builder now recreates only the explicit resolved
  `reports/e2e-workspace` target after proving that it is a descendant of repository `reports/`.
- `tools/build_replay_e2e_workspace.py` mirrors `_completed_workspace` from
  `tests/test_application_replay_export.py`: creates a workspace/home/job, imports
  `examples/materialization/mario_rossi_2026_10_30`, and publishes a completed run metadata file.
- Playwright starts that builder in the `webServer` command immediately before the launcher. This is
  deliberately not `globalSetup`: Playwright starts `webServer` before `globalSetup`, so a destructive
  fixture rebuild there races the open SQLite/log files. The configured command guarantees the required
  ordering while retaining the loopback port, real launcher, desktop, and mobile projects.
- The real E2E covers digest verification, timestamp-changing playback, Presentation → Analysis,
  evidence, Oracle cause, typed axe scan, keyboard stepping, reload/session restoration, and both
  Chromium projects.
- A real-browser race was found by the new test and corrected: verification/session and event-window
  requests no longer share an abort controller. Plan SVG groups now expose valid ARIA group roles, so
  the full axe scan is clean without hiding the canvas's keyboard controls.

## Design checkpoint evidence

- Same timestamp/selection across modes and reload: `ReplayWorkbench.test.tsx`,
  `useReplayController.test.tsx`, and both replay E2E projects.
- Trace/waypoint-derived playback and no invented positions: replay backend and controller tests;
  the real E2E advances the slider from a verified trace rather than a fixed event interval.
- Bounded all-family evidence and deterministic frames: `tests/test_application_replay_export.py`
  plus the new benchmark's 100 repeated frame and window assertions.
- Observable/Oracle separation, mismatch blocking, and digest-invalidated sessions:
  existing replay backend/controller suites, exercised again by `npm test`.
- Keyboard/reduced-motion/dark/narrow behavior: ReplayWorkbench/controller/component suites and the
  mobile Playwright project. Monthly/yearly coverage comes from `benchmark-replay`.

## Benchmark

`make benchmark-replay` completed. It constructs a fresh index then performs 100 deterministic
random frame seeks and 100 30-minute bounded event windows per fixture. Repeated frames/windows are
equal and every visible window is at most 37 events. The stated acceptance is median frame latency
under 100 ms after index construction; timing failure is enabled only under CI.

| Fixture | Events | Index ms | Median frame ms | Median window ms |
| --- | ---: | ---: | ---: | ---: |
| Weekly | 15,725 | 858.322 | 46.231 | 39.870 |
| Monthly | 4,476 | 113.404 | 20.887 | 18.103 |
| Yearly | 8,320 | 195.549 | 24.594 | 17.788 |

The monthly fixture is a deterministic bounded sample of the checked-in monthly run. The yearly
fixture is a deterministic timestamp-shifted sample of the weekly run, with valid regenerated
observable-log identifiers; neither fixture is a production artifact or a claim about runtime output.

## Verification

- `uv run ruff check src tests tools` — passed.
- `npm test` — passed: 8 files, 217 tests; jsdom emits its pre-existing non-fatal navigation notice.
- `npm run lint`, `npm run typecheck`, `npm run build` — passed (Vite reports the existing >500 kB
  chunk advisory only).
- `npx playwright test e2e/replay.spec.ts` — passed: 4 tests across desktop and mobile Chromium.
- `make benchmark-replay` — passed with the results above.
- `git diff --check` — passed.
- `uv run pytest -q` — completed at 95.41% coverage with exactly two accepted baseline failures:
  - `tests/test_drives.py::test_a_late_night_is_flagged_for_the_following_day`
  - `tests/test_expander.py::test_the_waking_day_never_asks_to_be_in_two_places_at_once`

## Concerns

The two Python failures are the accepted pre-replay baseline failures and were deliberately not
changed. The benchmark's annual data is synthetic, bounded, and clearly documented as such; it is
for replay-index/query behavior, not a published year-long simulation benchmark.
