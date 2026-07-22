# Behavioral profile and habit ground truth implementation plan

## Goal

Add an LLM-generated, validated, frozen behavioral profile to the isolated hybrid-planning
subsystem, then use it to enforce mineable habits in Tommaso's weekly plan without running
the simulation or exposing the comparison baseline to the model.

## Phase 1: Contracts and fixtures

1. Extend `hybrid_planning.models` with behavioral-profile, cadence, chain, ledger, budget,
   violation, gate-report, and planned-trace contracts.
2. Add strict cross-field validation for identifiers, cadence bounds, cooldowns, and profile
   versioning.
3. Add a behavioral-profile structured-output schema constrained to the planning case's
   known activity and location identifiers.
4. Add deterministic test fixtures for a valid Tommaso profile and invalid variants.

## Phase 2: Profile generation and freezing

1. Add a dedicated prompt that separates supplied immutable facts from synthetic traits
   and requests a detailed, mineable habit portfolio.
2. Implement `generate_behavioral_profile` with at most two explicit repair attempts.
3. Validate catalog references, resident identity, anchor coverage, causal-chain references,
   cadence feasibility, and a minimum mix of anchor, contextual, optional, and rare habits.
4. Persist request, response, parsed proposal, validation report, manifest, frozen profile,
   intended ground truth, and SHA-256 digest.
5. Add `generate-behavioral-profile` to the CLI.

## Phase 3: Ledger, budget, and plan gates

1. Derive an initial ledger from the frozen profile and verify its digest when reused.
2. Compute a seven-day habit budget with required, due, optional, and forbidden habits.
3. Include the frozen profile and budget in weekly and daily prompts.
4. Implement plan gates for cadence maximums, cooldowns, required habits, daily completeness,
   causal adjacency/order, and weekly-goal traceability.
5. Produce stable violation codes with dates, habit IDs, and evidence.
6. Add targeted full-week repair with at most two attempts and explicit failure.
7. Persist gate reports, planned habit trace, and updated ledger.

## Phase 4: CLI integration and compatibility

1. Add `--behavioral-profile` and optional ledger input to `generate-hybrid-plan`.
2. Preserve the existing legacy path temporarily for focused tests, but mark the CLI path
   as requiring a profile once the live vertical slice is stable.
3. Keep comparison post-acceptance only and preserve `executionPerformed: false`.
4. Document both commands and the LM Studio prerequisite.

## Phase 5: Verification and live acceptance

1. Unit-test contracts, invalid profiles, digest mismatch, budgets, gates, repair exhaustion,
   and ground-truth artifacts.
2. Verify no baseline identifier or payload appears in persisted LLM prompts.
3. Run lint and targeted tests with at least 95 percent package coverage.
4. Generate Tommaso's behavioral profile with `qwen2.5-coder-7b-instruct`.
5. Generate a new seven-day plan using the frozen profile.
6. Compare habit fidelity, causal completeness, diversity, runtime, and repair count with the
   previous hybrid plan and hidden baseline.
