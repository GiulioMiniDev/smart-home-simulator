# Task 8 report — real replay journey

## Outcome

DONE. Task 8 adds a disposable, real-artifact replay workspace, browser acceptance
coverage, replay performance evidence, and operator documentation. It does not change the protected
night, drives, or expander implementation/tests.

## Follow-up UI fixes

- The scrollable replay inspector is now reachable with Tab and retains its visible `Inspector`
  heading as its accessible name, without adding another landmark. Component coverage asserts the
  focus target, heading association, and single complementary landmark; the real axe scan remains
  clean on desktop and mobile Chromium.
- Transport stepping now moves to the first source-order event at the next or previous *distinct*
  timestamp. Simultaneous evidence remains individually reachable through timeline clusters rather
  than trapping Previous/Next at one instant. Controller coverage exercises dense same-timestamp
  events in both directions. The reload E2E begins at a known dense fixture instant and requires one
  keyboard step to change both the slider time and selected semantic event before proving exact
  session restoration.

## Acceptance evidence

- `frontend/e2e/replay.spec.ts` was written first and failed as intended because
  `reports/e2e-replay-run.json` did not exist. The builder now recreates only the explicit resolved
  `reports/e2e-workspace` target after proving that it is a descendant of repository `reports/`.
- `tools/build_replay_e2e_workspace.py` mirrors `_completed_workspace` from
  `tests/test_application_replay_export.py`: creates a workspace/home/job, imports
  `examples/materialization/mario_rossi_2026_10_30`, and publishes a completed run metadata file.
- Playwright `globalSetup` always builds the disposable workspace before it checks or starts the
  backend. An occupied loopback port is a hard failure rather than permission to reuse a stale server;
  readiness also proves that the freshly generated run ID is served by that backend.
- The real E2E covers digest verification, timestamp-changing playback, Presentation → Analysis,
  evidence, Oracle cause, typed axe scan, keyboard stepping, reload/session restoration, and both
  Chromium projects.
- A real-browser race was found by the new test and corrected: verification/session and event-window
  requests no longer share an abort controller. Plan SVG groups now expose valid ARIA group roles, so
  the full axe scan is clean without hiding the canvas's keyboard controls.

## Design checkpoint evidence

- The exact timestamp and semantic selection survive mode and visibility-projection changes:
  `ReplayWorkbench.test.tsx`, `useReplayController.test.tsx`, and both replay E2E projects.
  Reload restores the exact timestamp, mode, and filters after debouncing; it does not claim to
  restore event selection.
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

| Fixture | Span | Events | Observations | Runtime sentinels | Daily summaries | Bounded daily window | Index ms | Median frame ms | Median window ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Weekly | 7 d | 31,458 | 28,612 | 2 | 6 | 6 / 6 | 2,388.310 | 1.293 | 6.616 |
| Four-week month-scale | 28 d | 125,832 | 114,448 | 8 | 24 | 24 / 24 | 10,885.630 | 1.664 | 7.138 |
| Yearly | 364 d | 1,635,816 | 1,487,824 | 104 | 312 | 37 / 312 | 54,578.166 | 1.392 | 4.945 |

The 7-day canonical week is two contiguous complete source periods with an affine monotonic
timestamp normalization; four-week and yearly fixtures are respectively 8 and 104 source periods.
No records are sampled, cropped, or separated by multi-day gaps. All trace families, observations,
IDs, cross-references, semantic digests, and Observable-log metadata are regenerated. Because the
source has no runtime events, each source period gains a valid, fixture-only
`benchmark_runtime_coverage_sentinel`; it is coverage data, not simulated output. The builder
validates the Oracle mapping before deliberately omitting it from the annual timing workspace: this
benchmark measures Observable replay performance, not optional Oracle disclosure. Daily summaries
are counted as a trace family and queried through a separately bounded `daily_summary` window; the
annual window returns 37 of 312 summaries. The annual construction peaked at about 2.53 GiB and its
1.392 ms median meets the 100 ms CI target; it is
synthetic replay-load evidence, not a production year-long simulation claim.

## Verification

- `uv run ruff check src tests tools` — passed.
- `npm test` — passed: 8 files, 220 tests; jsdom emits its pre-existing non-fatal navigation notice.
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
