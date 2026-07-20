# ADR-004: Freeze behavioral authoring contracts 1.0.0

- **Status:** accepted
- **Date:** 2026-07-20

## Context

The complete simulator needs resident-specific descriptions of how scheduled activities
decompose into typed actions. Building a simulation engine before defining these inputs
would make its interface provisional and force later milestones to replace rather than
consume it. Dataset activity labels are too coarse to own runtime semantics, and an LLM
output cannot be allowed to control the world without deterministic validation.

## Decision

Freeze together under behavioral authoring version `1.0.0`:

- the project-specific activity catalog;
- the typed personal, state, day and calendar variable catalog;
- the closed atomic-action vocabulary and parameter contracts;
- the personal process-package graph and binding semantics;
- the behavior validation report and stable issue-code vocabulary;
- the official external-authoring prompt templates;
- the five distributed Draft 2020-12 schemas and checksums;
- the rule-generated minimal and Mario acceptance packages and golden report;
- the `validate-behavior` CLI behavior.

JSON is the authoritative process representation. Mermaid is not an input contract or a
runtime dependency. External dataset labels may appear only as interoperability metadata.
An LLM may author scenario and process files before validation; validation, compilation
and simulation never invoke an LLM provider.

A process package is accepted only when every source-scenario activity resolves to exactly
one applicable resident-specific binding, every graph is structurally sound and bounded,
every model implements the intent's complete ordered component decomposition, and every
action and variable belongs to its loaded catalog. The Mario acceptance package contains
91 intent-specific models and 91 bindings for all 173 scheduled activities; its graphs
exercise conditional choice, parallel split/join and a bounded loop.

## Consequences

- Milestone 4 can bind typed actions to a concrete home without redefining behavior.
- Milestone 5 can execute complete process models rather than inventing microactions.
- The scenario and canonical-plan `1.0.0` contracts remain unchanged.
- New activities, variables, actions or graph semantics require a new catalog or contract
  version and explicit compatibility handling.
- Provider integration remains unnecessary; persisted accepted artifacts, versions and
  digests determine reproducibility.
