# Dual-mode replay design

**Status:** approved  
**Date:** 2026-08-23  
**Scope:** deterministic execution replay in the local application

## Goal

Turn the current movement slideshow into a truthful temporal replay that serves two connected
uses. Presentation mode explains a simulation clearly in a thesis demonstration. Analysis mode
lets a researcher inspect the same instant as scientific evidence. Switching modes preserves the
clock, selection, resident, speed, and filters.

The replay remains a projection of immutable run artifacts. It never becomes a second simulation
engine or source of truth.

## Current gap

The current frontend advances one completed movement every 650 milliseconds, regardless of its
timestamps, and draws the complete selected trajectory at once. Activity and action selections do
not alter the plan. The client requests up to 5,000 events, renders at most the first 800, and does
not provide seek, temporal zoom, speed control, filters, an inspector, or saved-session recovery.

The application replay endpoint exposes activities, actions, and movements only. The authoritative
execution trace now also contains state transitions, resource events, runtime events, plan
deviations, daily summaries, and the final world state. Observable sensor records and their
separate oracle links are available through another service but are not synchronized with replay.
The existing `replay_sessions` persistence stores position and filters, but the replay UI does not
restore or update them.

## Chosen approach

Use one replay engine and one workbench with two levels of detail:

- **Presentation** makes the home and resident motion primary and keeps technical evidence one
  interaction away.
- **Analysis** exposes a synchronized multitrack timeline, plan, state inspector, filters, and
  explicit Observable/Oracle modes.

This was selected over separate presentation and debugger pages, which would duplicate temporal
state and make the same event feel discontinuous, and over one permanently dense progressive UI,
which would weaken both the projected demonstration and expert analysis.

## Shared temporal model

A replay controller owns:

- verified run identity and semantic digest;
- current simulation instant and visible time window;
- playing, paused, step, and seek state;
- playback speed from `0.25x` through `32x`;
- selected event and resident;
- enabled event and spatial layers;
- Observable or Oracle visibility mode;
- presentation or analysis detail mode.

Playback advances by simulation time, not by event count. Movement positions are interpolated
between authoritative waypoints using their timestamps. Seeking reconstructs the same frame
whether approached from the past or the future. Switching detail mode does not reset controller
state.

The server indexes immutable artifacts and provides bounded event windows and frames at requested
instants. A frame is a derived projection containing resident position and execution state,
current activity and action, sensor readings, relevant entity and environment facts, held
resources, deviations, and provenance links. Frame construction must not mutate or reinterpret the
trace.

## Presentation mode

The plan fills the available workbench and remains the authoritative visual object. A compact top
bar shows simulated date and time, resident, and current activity. A bottom transport contains
previous event, play or pause, next event, speed, and a simple scrubber.

Each resident has a stable labelled marker that follows timestamped waypoints. The current room
receives a restrained tint and sensors give short state-change pulses. A compact caption explains
the current evidence in plain language, for example resident, activity, region, and time. An
**Open evidence** action switches to Analysis mode at the identical instant and selection.

Presentation motion communicates state only. It respects reduced-motion preferences by stepping
between authoritative waypoint positions rather than continuously interpolating them.

## Analysis mode

The desktop layout uses three coordinated regions:

1. the shared plan on the left;
2. a persistent event and world-state inspector on the right;
3. a multitrack timeline across the bottom.

Timeline tracks cover activities, actions, movements, sensor observations, state transitions,
resource events, runtime events, and plan deviations. Users can click or drag to seek, step between
events, zoom from minutes to days, and filter by resident, sensor, event kind, and status. Dense
windows aggregate visually but keep every underlying event inspectable.

The inspector explains the selected event, current state, causal links, and source identifiers.
Observable mode never receives resident or activity identity through sensor records. Oracle mode
is a deliberate structural switch that adds the separately stored mapping and labels its simulated
cause.

## Visual integration

The workbench extends the existing simulator design rather than introducing a separate replay
theme. It reuses the current typography, spacing, borders, radii, buttons, badges, inspectors,
loading states, and `PlanCanvas` SVG system. The warm light workspace, restrained dark theme, and
existing semantic palette remain authoritative:

- indigo for computed routes and temporal selection;
- teal for physical resources;
- amber for routing obstacles and warnings;
- existing success and error roles for verification state.

Only the tokens required to distinguish event tracks and resident identities are added. Identity
uses a symbol and label as well as color. The design excludes gradients, glass effects, neon
control-room styling, decorative smart-home imagery, and gratuitous animation.

## Component boundaries

- `ReplayWorkbench` composes the selected mode and shared controller.
- `useReplayController` owns temporal, playback, selection, filter, and persistence state.
- `ReplayToolbar` provides verification, mode, filter, speed, and transport controls.
- `ReplayStage` adapts `PlanCanvas` with resident and live-state overlays.
- `ReplayTimeline` renders and navigates bounded multitrack event windows.
- `ReplayInspector` presents selected evidence and reconstructed world state.

Existing run summary, diary, observations, profile, and artifacts remain separate tabs. The replay
may deep-link to their source rows, but it does not duplicate their complete interfaces.

## Verification and persistence

Opening replay performs semantic verification before enabling transport controls. A successful
verification saves the verified digest. Position, speed, detail mode, visibility mode, selected
resident, and filters are persisted with the replay session and restored only when its digest still
matches the run.

A digest mismatch blocks playback and displays expected and actual values. Missing artifacts name
the exact unavailable role. A missing position is displayed as unknown and never interpolated.
Simultaneous events are grouped visually and remain individually selectable. Oracle controls are
disabled with an explanation when the mapping is absent.

## Accessibility

All transport, mode, filter, timeline, and event controls support keyboard operation and visible
focus. The plan has a synchronized structured alternative describing residents, regions, active
sensors, and the selected event. Status and resident identity never rely on color alone. Live
announcements describe intentional navigation and state changes without announcing every playback
frame. Both themes target WCAG 2.2 AA.

## Test strategy

- Backend unit tests prove deterministic frames, random forward and backward seeks, simultaneous
  events, all trace event families, Observable/Oracle separation, bounded windows, and session
  invalidation after a digest change.
- Frontend unit tests use a fake clock to prove timestamp-based playback, interpolation, stepping,
  speed changes, mode continuity, filtering, persistence, reduced motion, and blocked states.
- Component and visual tests cover both modes, light and dark themes, desktop and narrow layouts,
  multiresident identity, dense timelines, and empty or incomplete evidence.
- End-to-end tests use a real backend and run artifacts to verify playback, evidence drilldown,
  keyboard navigation, accessibility, and reload recovery.
- Performance checks cover weekly, monthly, and yearly traces without loading the complete event
  history into the browser.

## Delivery sequence

1. Make verification, indexed frame reconstruction, windowed events, seek, and timestamp-correct
   movement playback trustworthy.
2. Add the analysis timeline, inspector, trace families, filtering, Observable/Oracle separation,
   and saved sessions.
3. Add presentation mode, resident animation and captions, responsive and reduced-motion behavior,
   then complete visual and end-to-end verification.
