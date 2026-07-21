# ADR-012: Parallel batch orchestration 1.0.0

- **Status:** accepted; portability amended by ADR-013
- **Date:** 2026-07-21

## Context

Sensor generation, Monte Carlo replication and experimental calibration require many
independent simulations. Parallelizing one SimPy world would weaken deterministic event
ordering, while external shell jobs do not provide a versioned manifest, failure
isolation, resume validation or reproducible seed provenance.

## Decision

Freeze an orchestration layer around the unchanged M5 engine:

- one simulation remains synchronous and owns one complete `SimulationEngine`;
- independent runs execute in a `spawn`-based process pool;
- a run references a bundle and may override its seed;
- the effective bundle is materialized beside the trace before execution;
- output paths derive only from a validated run ID;
- each run writes atomically and failures do not cancel siblings;
- aggregate order follows the manifest rather than future completion order;
- resume reuses only a complete bundle/trace/report set whose hashes and digest match the
  current input and effective seed;
- a non-blocking directory lock prevents two batches from publishing into the same root;
- sequential and parallel executions must produce identical per-run semantic digests.

The public contracts are `simulation-batch-manifest-1.0.0` and
`simulation-batch-report-1.0.0`.

## Consequences

- Experiment throughput can scale across CPU cores without shared runtime state.
- Every completed run remains replayable without the batch runner.
- Operational fields such as PID and elapsed time are not semantic reproducibility data.
- Storage grows by one effective bundle, trace and report per run.
- The output lock is implemented by the platform abstraction established in ADR-013.
- Streaming, distributed queues and cross-host scheduling remain deferred until M8
  benchmarks demonstrate that a local process pool is insufficient.
