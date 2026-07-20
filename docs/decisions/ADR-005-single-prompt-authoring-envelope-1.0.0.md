# ADR-005: Single-prompt authoring envelope 1.0.0

- Status: accepted and frozen
- Date: 2026-07-20

## Context

The scenario and personal ADL contracts were independently complete, but asking a
researcher to attach their schemas, three catalogs and multiple prompt files to a chatbot
created unnecessary manual work. The intended research workflow is instead one generic
prompt enriched with a free-form person description, followed by external-LLM generation
before simulation.

Two unrelated JSON code blocks are not a portable machine-readable response: chatbot file
creation differs by provider, surrounding prose is common and cross-document identity can
be lost during manual copying.

## Decision

Distribute one generated, self-contained prompt containing the complete output schema and
all authoritative catalogs. Require one pure-JSON `simulation_authoring_bundle` response
that embeds exactly one frozen scenario and one frozen personal process package.

Provide deterministic ingestion that applies the existing validators and atomically
publishes the two canonical standalone artifacts only when the whole response is valid.
The new envelope is a transport layer and does not change either nested contract.

## Consequences

- The researcher supplies only the generic prompt plus natural-language person
  description; no intermediate person-profile JSON is required.
- The LLM may generate the scenario and its personal ADL models in one initial authoring
  interaction.
- Schema and catalog duplication exists only inside a generated distribution artifact and
  is checked for deterministic parity.
- Provider-specific downloadable-file features are unnecessary.
- Invalid, inconsistent or truncated LLM responses cannot produce partial simulator
  inputs.
- The simulator remains provider-independent and never invokes an LLM at runtime.
- Empirical realism is not implied by structural acceptance.

The public envelope and ingestion-report contracts are frozen at `1.0.0`. Future changes
require new parallel versions and cannot mutate the frozen scenario or process-package
contracts.
