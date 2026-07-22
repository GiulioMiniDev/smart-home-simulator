# Procedural environment generation implementation plan

**Date:** 2026-07-22  
**Design:** `docs/plans/2026-07-22-procedural-environment-generation-design.md`  
**Target:** scenario-aware, seeded home and sensor generation with a configurable pre-run draft

## Delivery rules

- Preserve existing user changes and commit only files owned by the active implementation step.
- Keep `HomeModel 1.0.0`, `SensorModel 1.0.0`, simulation, and export semantics compatible.
- Keep manual home and sensor import supported.
- Use deterministic named random streams; never consume one shared mutable generator across stages.
- Never publish partial home/sensor pairs or replace a valid draft after failed generation.
- Do not start implementation until this plan follows the approved design.
- Add failing tests before each behavior change and keep commits phase-scoped.

## 1. Baseline and contract decisions

Files:

- `docs/decisions/ADR-016-procedural-environment-generation.md`
- `src/smart_home_sim/domain/materialization.py`
- `schemas/home-generation-policy-1.1.0.schema.json`
- `schemas/home-generation-report-1.1.0.schema.json`
- matching checksum files
- `tests/test_contract_structure.py`
- `tests/test_json_schema.py`

Tasks:

1. Record the current full Python and frontend test baseline without modifying generated goldens.
2. Add ADR-016 covering named PRNG streams, catalog authority, external-topology projection,
   compatible environment revisions, and run inputs.
3. Add an additive `HomeGenerationPolicy 1.1.0` with `procedural-home` policy ID, archetype,
   size, furnishing density, maximum attempts, seed-stream version, and dimensional limits.
4. Add a richer `HomeGenerationReport 1.1.0` with selected archetype, accepted attempt,
   catalog/version provenance, stream scheme, warning/error counts, and bounded rejected-attempt
   summaries.
5. Preserve parsing of `compact-grid 1.0.0` policies for historical provenance and CLI replay.
6. Generate schemas and checksums through the project schema tooling.

Verification:

- strict positive and negative policy/report parsing;
- old compact-grid examples remain readable;
- schema/model equivalence and checksum tests pass;
- serialization is deterministic.

## 2. Furnishing catalog and symbol registry

Files:

- `src/smart_home_sim/domain/furnishing.py`
- `src/smart_home_sim/catalogs/furnishing-catalog-1.0.0.json`
- `src/smart_home_sim/catalogs/__init__.py`
- `frontend/src/furnishings.ts`
- `frontend/src/components/FurnishingSymbols.tsx`
- `tests/test_furnishing_catalog.py`
- `frontend/src/test/furnishings.test.tsx`

Tasks:

1. Define strict catalog models for room compatibility, size ranges, placement preference,
   footprint, clearance, routing behavior, semantic roles, capabilities, operations, interaction
   rules, sensor affinities, and SVG symbol IDs.
2. Populate the first catalog with complete bedroom, bathroom, kitchen, living, circulation,
   utility, entrance, balcony, and generic storage kits.
3. Include operational objects required by existing authoring examples, including bed, shower,
   toilet, washbasin, refrigerator, sink, stove, table, seating, sofa, television, wardrobe,
   cabinet, washing machine, medication storage, vacuum cleaner, cleaning tools, and entrance.
4. Create one reusable editable SVG symbol registry in React. Port useful M4 symbols without
   porting hardcoded Mario coordinates.
5. Add a catalog coverage gate: every physical catalog type has a symbol and every symbol maps to
   a catalog type.

Verification:

- duplicate type/role/symbol IDs fail;
- invalid dimensions and incompatible placement rules fail;
- every catalog entry round-trips deterministically;
- React renders every symbol and exposes an accessible label.

## 3. Named deterministic streams and requirement analysis

Files:

- `src/smart_home_sim/generation/__init__.py`
- `src/smart_home_sim/generation/randomness.py`
- `src/smart_home_sim/generation/requirements.py`
- `tests/test_generation_randomness.py`
- `tests/test_generation_requirements.py`

Tasks:

1. Derive named stream seeds from SHA-256 of root seed, stream-scheme version, and stream name.
2. Ensure stream construction is platform-independent and independent of Python hash ordering.
3. Extract domestic and external location roles from the scenario without using input order as
   topology.
4. Extract required capability/role/operation tuples from process models and the action catalog.
5. Map explicit scenario resources to required physical types and identify generated providers.
6. Produce normalized sensor requirements from stateful entities and used actions.
7. Return structured missing-role diagnostics before geometry generation when no catalog mapping
   exists.

Verification:

- same seed/name gives identical sequences across processes;
- adding a sensor stream does not alter layout or furnishing streams;
- permuting JSON location/resource order does not change normalized requirements;
- Tommaso requirements include bathroom fixtures, food preparation, dining, cleaning, sleeping,
  entrance, and scenario resources.

## 4. Domestic program and orthogonal layout

Files:

- `src/smart_home_sim/generation/program.py`
- `src/smart_home_sim/generation/layout.py`
- `src/smart_home_sim/generation/geometry.py`
- `tests/test_generation_program.py`
- `tests/test_generation_layout.py`
- `tests/test_generation_properties.py`

Tasks:

1. Define apartment and house archetype rules and deterministic `auto` selection.
2. Build semantic adjacency graphs for entrance, circulation, day, night, service, and outdoor
   zones.
3. Generate rectangular and bounded L-shaped room candidates inside an orthogonal footprint.
4. Place doors/passages on legal shared boundaries with configured clear widths.
5. Reserve circulation corridors and entrance access before furnishing.
6. Represent external locations and transit connections authoritatively without allowing their
   display geometry to influence the domestic fit or scale.
7. Reject overlaps, disconnected rooms, illegal portals, undersized rooms, and footprints that
   cannot fit required furnishing kits.
8. Run bounded candidate attempts using attempt-specific named streams.

Verification:

- property-based tests over many seeds assert no overlaps and complete entrance reachability;
- input order has no effect;
- different seeds yield more than one topology or dimensional arrangement;
- no accepted multi-room plan is a single equal-sized row;
- apartment and house fixed-seed goldens are deterministic.

## 5. Furnishing placement, footprints, and interaction points

Files:

- `src/smart_home_sim/generation/furnishing.py`
- `src/smart_home_sim/generation/clearance.py`
- `tests/test_generation_furnishing.py`
- `tests/test_generation_clearance.py`

Tasks:

1. Select required room kits, then add optional elements according to density.
2. Place wall, corner, and free-standing items using catalog constraints and room-local streams.
3. Materialize specific `HomeEntity` types and deterministic obstacle footprints.
4. Use stable footprint/entity ID relationships so the renderer can derive symbol position and
   orientation from authoritative geometry.
5. Place interaction points outside footprints and within catalog approach distance.
6. Reserve door swing/approach and required circulation clearances.
7. Reject optional furniture before rejecting a required item or the room candidate.
8. Validate paths from entrance to every required interaction point with resident body clearance.

Verification:

- complete-density rooms contain the expected furnishing classes;
- all blocking items have footprints and all required entities have reachable interaction points;
- furniture never blocks the only room route;
- changing one room kit leaves other room placements unchanged;
- catalog symbols cover every generated physical type.

## 6. Specific capability and resource binding

Files:

- `src/smart_home_sim/generation/binding.py`
- `src/smart_home_sim/materialization/service.py`
- `src/smart_home_sim/environment/service.py`
- `tests/test_generation_binding.py`
- `tests/test_materialization.py`
- `tests/test_environment.py`

Tasks:

1. Bind required roles to specific generated or scenario-backed entities.
2. Preserve normal `ResourceBinding` entries for scenario resources.
3. Allow generated physical providers to satisfy action bindings without inventing scenario
   resources.
4. Remove domestic `generated_environment_service` creation from the procedural policy.
5. Keep explicit external service providers only where the external action semantics require
   them, and project them outside the domestic plan.
6. Return actionable missing-role issues naming process model, node, action, capability, and role.
7. Keep `compact-grid` generation isolated as a legacy policy implementation.

Verification:

- every required action binding resolves to a specific provider;
- no procedural domestic entity has type `generated_environment_service`;
- Tommaso binds shower, toilet, food preparation, dining, cleaning, medication, sleep, and exit
  semantics to physical providers;
- existing manual golden bundles still validate.

## 7. Sensor placement on the stable furnished home

Files:

- `src/smart_home_sim/generation/sensors.py`
- `src/smart_home_sim/materialization/service.py`
- `tests/test_generation_sensors.py`
- `tests/test_sensors.py`

Tasks:

1. Refactor sensor deployment to accept the furnished home and catalog sensor affinities.
2. Place PIR sensors at obstacle-free positions and construct useful contained coverage polygons.
3. Attach contact sensors only to compatible stateful entities used by the scenario where
   possible.
4. Place temperature sensors in valid regions with explicit heat-source entities.
5. Keep sensor streams independent by type and sensor ID.
6. Preserve the existing minimal, room-coverage, and dense semantics while improving placement.

Verification:

- every generated sensor passes the frozen sensor/home validation gates;
- coverage stays inside assigned regions and avoids impossible device positions;
- contact and temperature sources exist and are semantically appropriate;
- changing sensor preset leaves home bytes and digest unchanged;
- removing one sensor does not change other sensor random streams.

## 8. Procedural generation facade, reports, and CLI

Files:

- `src/smart_home_sim/generation/service.py`
- `src/smart_home_sim/materialization/service.py`
- `src/smart_home_sim/materialization/__init__.py`
- `src/smart_home_sim/cli.py`
- `tools/build_materialization_artifacts.py`
- `tests/test_procedural_generation.py`
- `tests/test_cli.py`

Tasks:

1. Compose the pipeline behind a pure service returning home, sensor model, and reports without
   publishing files.
2. Add bounded deterministic retry orchestration and structured rejection diagnostics.
3. Make `procedural-home` the application and CLI default while keeping an explicit legacy policy.
4. Expose separate CLI commands for environment generation and simulation from supplied
   home/sensor models.
5. Regenerate only new procedural goldens; do not rewrite frozen historical examples.

Verification:

- direct service and CLI outputs match byte-for-byte;
- failed candidates publish nothing;
- cancellation interrupts between stages and attempts;
- generation stays within the documented attempt/time budget.

## 9. Compatible environment revision persistence

Files:

- `src/smart_home_sim/domain/application.py`
- `src/smart_home_sim/application/workspace.py`
- `src/smart_home_sim/application/service.py`
- `tests/test_application_workspace.py`
- `tests/test_application_service.py`

Tasks:

1. Add a forward-only SQLite migration for environment revisions that reference one home artifact,
   one sensor artifact, source artifacts, policy/report artifacts, seed, status, and provenance.
2. Keep current home/sensor pointers readable but derive the active compatible pair from the
   environment revision.
3. Persist generated drafts without moving the active published revision.
4. Publish home and sensor artifacts plus the environment revision in one transaction.
5. Preserve imported/manual model publication by creating compatible environment revisions once
   both sides validate.
6. Reject stale sensor models after home edits and surface the compatibility issue.

Verification:

- transaction rollback leaves no partial pair;
- failed generation leaves the current draft and published pair untouched;
- restart/reconciliation preserves drafts and current revisions;
- old workspaces migrate forward and completed runs remain readable.

## 10. Split generation jobs from simulation jobs

Files:

- `src/smart_home_sim/application/jobs.py`
- `src/smart_home_sim/web/app.py`
- `tests/test_application_jobs.py`
- `tests/test_web_application.py`

Tasks:

1. Add a `generation` worker/job using the pure procedural service and stage progress events.
2. Add generate, draft-read, draft-discard, and atomic publish endpoints.
3. Change simulation requests to require a published environment revision or exact home/sensor
   artifact IDs.
4. Refactor the simulation worker to compile, bind, simulate, and project against supplied models
   without calling home or sensor generation.
5. Validate source and artifact digests before queueing and again in the worker.
6. Remove automatic home/sensor revision publication from simulation completion.

Verification:

- API rejects runs without a valid compatible pair;
- run artifacts contain the exact requested home and sensor digests;
- generation completion does not start a run;
- cancellation and failure do not replace drafts or revisions;
- SSE exposes real generation phases and diagnostics.

## 11. Generation and pre-run configuration UI

Files:

- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/hooks.ts`
- `frontend/src/types.ts`
- `frontend/src/styles.css`
- `frontend/src/test/App.test.tsx`
- `frontend/e2e/environment-generation.spec.ts`

Tasks:

1. Replace `Generate home, sensors and first run` with `Generate environment`.
2. Add collapsed optional controls for archetype, size, furnishing density, sensor preset, and
   seed, with recommended defaults.
3. Show generation stage progress and rejected-attempt diagnostics through the existing job event
   channel.
4. Load successful output as the current compatible draft and open the plan editor.
5. Implement `New variant` replacement with inline dirty-draft confirmation.
6. Treat home and sensors as one undoable draft and one atomic publish action.
7. Disable `Run simulation` until a compatible environment revision is published and the draft is
   clean.
8. Send the published environment revision to the run endpoint.

Verification:

- keyboard-only generation, option editing, confirmation, publication, and run flow;
- loading, failure, retry, dirty, stale, and success states;
- no generation action can implicitly start a run;
- accessible status announcements and focus movement to blocking issues.

## 12. Floor-plan renderer and editor completion

Files:

- `frontend/src/components.tsx`
- `frontend/src/editor.ts`
- `frontend/src/styles.css`
- new focused components under `frontend/src/components/`
- `frontend/src/test/components.test.tsx`
- `frontend/src/test/editor.test.ts`
- visual snapshots

Tasks:

1. Split domestic metric regions from external topology in the renderer.
2. Add independently toggleable rooms, doors, obstacles, physical resources, logical providers,
   interaction points, sensors, coverage, routes, and validation layers.
3. Render physical entities using catalog SVG symbols positioned from authoritative footprints
   and interaction points.
4. Hide dense labels by default and reveal concise labels on selection/focus.
5. Add furniture/resource/door tools and structured inspector fields for type, region, footprint,
   position, dimensions, and sensor configuration.
6. Synchronize canvas, structured alternative, inspector, and validation issue selection.
7. Preserve complete keyboard access, visible focus, reduced motion, and narrow-screen layout.

Verification:

- every generated physical object is visible and selectable;
- no resource is silently omitted for lack of a symbol;
- external sites never affect domestic fit-to-view;
- desktop and narrow visual regressions cover all layers;
- renderer remains usable with Tommaso-scale entity and sensor counts.

## 13. Terminal regression suite and documentation

Files:

- `tests/test_procedural_generation_tommaso.py`
- `frontend/e2e/tommaso-environment-run.spec.ts`
- `README.md`
- `ROADMAP.md`
- `docs/spec/08-executable-home-and-binding.md`
- `docs/decisions/ADR-015-scenario-first-environment-materialization.md`
- closure audit under `docs/audits/`

Tasks:

1. Add the accepted Tommaso authoring bundle as the main procedural regression input without
   duplicating large derived artifacts.
2. Test import, generation, complete furnishing, sensor validity, manual edit, atomic publish,
   simulation, digest linkage, and replay.
3. Add multi-seed diversity metrics and the explicit anti-compact-grid assertion.
4. Run Python formatting, linting, typing, full tests, schema checks, and 95% coverage.
5. Run frontend linting, typing, unit/component tests, 95% coverage, production build, and
   Playwright.
6. Run keyboard, accessibility, console-error, desktop, and narrow visual checks.
7. Update documentation and roadmap only after all gates pass.

Required final evidence:

- fixed-seed home and sensor digests;
- multi-seed topology/furnishing diversity results;
- routing, interaction-point, and sensor validity counts;
- screenshot evidence for domestic plan and external topology;
- job provenance proving that the simulation used the published environment revision;
- exact quality-gate commands and results.

