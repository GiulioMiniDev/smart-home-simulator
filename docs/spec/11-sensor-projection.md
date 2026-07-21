# Sensor projection and oracle separation

## Boundary

Milestone 6 consumes one completed M5 `execution_trace`, its exact M4
`simulation_bundle` and one independently versioned `sensor_model`. The bundle embeds the
researcher-provided authoritative home model. Projection either publishes all three
successful artifacts—observable log, oracle mapping and projection report—or publishes
only a failed report. It is read-only: it cannot advance the simulation clock, mutate
world state or alter the M5 semantic digest.

## Public and oracle data

An `observable_sensor_log` contains exactly what a device can expose: observation ID,
sensor ID and type, device timestamp, measurement, value, unit and quality. It contains no
trace, resident, activity, action, movement, transition or causal identifier.

The separate `oracle_mapping` joins each observation ID to its simulated cause and, where
available, to resident, action and activity executions. A false positive is explicitly
mapped to `noise` and has no fabricated simulated cause. The initial temperature reading
maps to the source trace as initial state.

## Implemented sensor semantics

- A PIR requires a valid coverage polygon containing the declared sensor position. It
  analytically intersects every movement segment with that polygon, including crossings
  whose waypoints both lie outside it, and emits a paired `motion=ON`/`motion=OFF` pulse
  with the configured hold duration. Projection is event-driven and does not poll the home.
- A contact sensor either observes matching transitions of one entity fact or converts
  configured action executions into an `OPEN`/`CLOSED` pulse. The latter models doors even
  when the authoritative trace represents passage as `enter_home`/`leave_home` actions.
- A temperature sensor starts from its configured baseline. Matching entity transitions
  drive an additive response curve with explicit delay, rise, decay and sampling interval.
  Optional Gaussian measurement noise affects only the public value, never the oracle cause.

Generated sensor models `1.1.0` select projection policy `event-driven-sensors-1.1.0`.
In addition to crossings, a PIR receives causally linked, irregularly retriggered pulses
while motor actions execute at a covered entity interaction point. Temperature sensors
emit periodic 15-minute samples with a deterministic daily component, 0.5 °C quantization
and source deltas. Samples caused only by this exogenous component use the explicit
`environment_model` oracle origin. Sensor models `1.0.0` retain the frozen original
projection behavior for reproducible historical artifacts.

Every type supports its declared position, latency, clock jitter, cooldown, dropout,
false negatives, daily false positives and non-overlapping failure windows. Temperature
also supports measurement noise; PIR and contact reject non-zero measurement noise rather
than silently ignoring an unsupported setting. A paired PIR pulse is suppressed as one
candidate when its activation is lost. Latency plus negative jitter is clamped to zero so
a device timestamp never precedes its triggering event.

Before projection, sensor placement is checked against the exact home embedded in the
source bundle. Sensor and home region/entity catalogs must be identical. A PIR position
and its entire coverage polygon must be contained in the union of its declared home
regions, so coverage cannot silently cross an undeclared wall. Contact positions must lie
inside the region of their referenced entity; temperature positions must lie inside their
declared region. Boundary points are accepted for wall- or door-mounted devices.

## Reproducibility

The execution trace is the authoritative source of randomness. The sensor model repeats
its seed as an explicit compatibility assertion and projection refuses a mismatch. Each
sensor and concern derives an independent PRNG stream from SHA-256 of:

```text
execution trace seed : sha256-named-streams-1.0.0 : sensor:<id>:<concern>
```

The concerns include dropout, false negatives, false-positive selection, value and timing,
clock jitter and measurement noise. Removing or adding a sensor therefore does not change
another sensor's records. M5 randomness is never consumed.

## Compatibility and publication

The supplied bundle ID, canonical digest and seed must equal the corresponding trace
fields. The model `sourceBundleId`, `sourceBundleSha256` and seed must also match, and the
trace semantic digest is independently recomputed before projection. The successful
report records the source home ID, version and canonical digest. The CLI stages the observable log, oracle
mapping and successful report together, then uses atomic replacement for each artifact and
publishes the report last as the commit marker. A write error produces a failed report;
without a successful report whose hashes match both data artifacts, no partial replacement
is a valid projection. Invalid input, a mismatched model or a tampered trace cannot be
presented as a valid observable dataset.

The observable log and oracle mapping validate their own canonical identifiers, ordering,
uniqueness and semantic digests. The report accounts every nominal candidate exactly once
as observed, dropped, missed, cooldown-suppressed or failure-suppressed; false positives
and noisy observations are explicit subsets. It also records projector, policy, PRNG,
model, trace and source-bundle provenance plus hashes of both successful output artifacts.

All four contracts are Draft 2020-12 schemas with checksum sidecars:

- `sensor-model-1.0.0`;
- `observable-sensor-log-1.0.0`;
- `oracle-mapping-1.0.0`;
- `sensor-projection-report-1.0.0`.
