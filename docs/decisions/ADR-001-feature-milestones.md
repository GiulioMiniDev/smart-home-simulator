# ADR-001: Feature milestones instead of an early end-to-end simulator

- **Status:** accepted
- **Date:** 2026-07-19

## Context

The initial spike combined input models, pathfinding, SimPy, activity templates and PIR generation before their contracts and acceptance criteria were defined. This made arbitrary implementation choices appear as architectural decisions.

## Decision

Develop the system through dependent, independently testable milestones. The current production code contains only capabilities belonging to the active milestone. Premature downstream implementations are removed rather than kept as implicit foundations.

## Consequences

- Progress is measured through milestone definitions of done.
- Interfaces are documented before dependent features begin.
- Early demonstrations may be less visually impressive but produce reusable contracts.
- A downstream feature can be replaced without modifying the authority of upstream artifacts.

