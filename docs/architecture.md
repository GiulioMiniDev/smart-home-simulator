# Architecture

## Design principles

1. The structured scenario, simulator version and seed define reproducibility.
2. The simulation engine never asks an LLM how to activate a sensor.
3. Domain models do not depend on SimPy.
4. Microexecution templates translate semantic activities into reusable primitives.
5. Raw observations and oracle ground truth are separate artifacts.

## Modules

```text
domain/          Pydantic input and output contracts
validation/      referential and temporal checks
world/           rooms, connections and path finding
microexecution/  reusable primitives and activity templates
compiler/        daily activity -> executable primitive sequence
sensors/         observation and error models
engine/          SimPy orchestration and authoritative trace
exporters/       serialization of generated artifacts
```

## Current execution contract

An activity specifies a semantic intent, destination, planned start and expected duration. The compiler resolves the route from the resident's current room and selects a template profile. A template does not generate sensor data directly; it produces primitives with a duration and a movement cadence.

The engine executes each primitive. Motion detections are passed to every PIR covering the current room. Each PIR independently applies false-negative probability, reset delay and cooldown before emitting an observable record.

## Planned extensions

1. Versioned activity catalog loaded from data files.
2. Interaction points and 2D geometry inside rooms.
3. Contact, power and environmental sensor models.
4. Interruptions, alternatives and local replanning.
5. Persistent state and multi-day execution.
6. Multiple residents and shared resources.
7. Calibration and validation reports against real datasets.

