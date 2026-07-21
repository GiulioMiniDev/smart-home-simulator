# Milestone 6.1 closure audit

## Scope

M6.1 closes the first-run gap between accepted M3 authoring and the frozen M4–M6 runtime.
It does not infer a real dwelling or add UI behavior. Policy `1.1.0` also closes the
initial sensor-plausibility defects without claiming the formal calibration assigned to M9.

## Acceptance evidence

The authoritative acceptance input is
`generated/mario_rossi_2026_10_30_ingested`. Its behavior package is reproducibly migrated
to the already published activity/action catalogs `1.1.0`; the migration removes the
invalid duplicate egress from `travel_home` and materializes `prepare_food` outputs.

Starting from the resulting scenario and personal process package, the default policies
produce:

- 9 regions and 8 connections;
- 27 entities, including an explicit entrance door, and all 17 resource bindings;
- 312 resolved action bindings and 100 route checks;
- a successful M5 trace with 293 actions and 49 movements;
- 15 sensors under `room_coverage` (6 PIR, 3 contact, 6 temperature);
- a successful observable log with 6,764 records (4,826 PIR, 1,896 temperature and 42
  contact) and a separate oracle mapping;
- 17 hashed artifacts plus the self-describing workspace manifest.

The same inputs and policies are run twice in the acceptance suite and every artifact is
byte-identical. A pre-existing output directory is refused. Injected failure removes the
staging directory and publishes no workspace.

## Contract and gate evidence

New public contracts are versioned `1.0.0`: home generation policy/report, sensor
deployment policy/report and synthetic workspace manifest. Generated home and sensor
artifacts deliberately use the frozen M4/M6 contracts. All existing validators remain
authoritative; no generator result is published merely because generation completed.

The `1.1.0` policy version is explicit inside those contracts. Physical resource aliases
make `open`/`close` resolve to the refrigerator and medication/cleaning cabinet, while
`enter_home`/`leave_home` resolve to the entrance door. Distinct interaction points make
those bindings spatial. Projection policy `event-driven-sensors-1.1.0` adds irregular
within-room PIR retriggers, periodic quantized temperature and an explicit
`environment_model` oracle origin. Historical sensor models `1.0.0` keep policy `1.0.0`.

## Dataset-scale sanity check

The check is reproducible with `make compare-sensor-density` when the locally archived
dataset is available.

The local CASAS Aruba source (`03_datasets/raw/casas-11-aruba/data`, SHA-256 recorded in
its `SOURCE.md`) contains 1,719,558 records over 219.996 days. Normalized per sensor/day,
it contains 234.04 motion records across 31 motion sensors and 105.98 temperature records
across 5 temperature sensors. The corrected Mario run spans 3.286 days and produces
244.77 PIR records per PIR/day and 96.16 temperature records per temperature sensor/day.
Thus the two high-volume channels are on the same per-device order of magnitude. Mario's
4.26 contact records per contact sensor/day are lower than Aruba's 10.36 because they are
causally limited to the 17 open/close pairs and four entrance actions actually present in
this scenario; synthetic filler events are deliberately not invented.

This is a reproducible scale and semantic sanity check, not a distributional validation:
M9 must still compare inter-event distributions, burst structure, cross-sensor sequences,
daily variability and train/validation/test-separated calibration.

`make check` regenerates the migrated acceptance package, complete golden workspace, JSON
Schemas and checksums before running the full test, lint, CLI and benchmark matrix. The
M6.1 benchmark enforces a 10-second end-to-end ceiling on the development machine.

## Residual limits

The generated geometry is a controlled synthetic nuisance variable, not a recovered or
realistic floorplan. The default sensor policy is empirically informed but not a completed
dataset-specific calibration. Reusable physical shells, scenario-specific binding
layers, multi-resident merging, visual editing and empirical calibration remain assigned
to M7–M9 and are not needed for the complete single-scenario M6.1 claim.
