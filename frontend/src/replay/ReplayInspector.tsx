import type { ReplayEvent } from "../types";
import type { ReplayController } from "./useReplayController";

function value(value: unknown): string {
  if (value === null || value === undefined) return "Not available";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value); } catch { return String(value); }
}

function EvidenceRows({ title, entries }: { title: string; entries: Record<string, unknown> }) {
  const values = Object.entries(entries);
  if (!values.length) return null;
  return <section className="replay-inspector-section"><h3>{title}</h3><dl>{values.map(([key, item]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><code>{value(item)}</code></dd></div>)}</dl></section>;
}

function selected(controller: ReplayController): ReplayEvent | undefined {
  return controller.events?.items.find((event) => event.eventId === controller.selectedEventId);
}

export function ReplayInspector({ controller }: { controller: ReplayController }) {
  const event = selected(controller);
  const oracle = controller.filters.visibilityMode === "oracle";
  const frame = controller.frame;
  return <aside className="replay-inspector" aria-labelledby="replay-inspector-heading">
    <div className="replay-inspector-heading"><p className="eyebrow">Evidence and provenance</p><h2 id="replay-inspector-heading">Inspector</h2></div>
    {event ? <section className="replay-inspector-section"><h3>{event.label}</h3><dl>
      <div><dt>Kind</dt><dd>{event.kind}</dd></div><div><dt>Status</dt><dd>{event.status ?? "Not available"}</dd></div>
      <div><dt>Interval</dt><dd>{event.at}{event.end ? ` → ${event.end}` : ""}</dd></div>
      {event.sensorId && <div><dt>Sensor</dt><dd><code>{event.sensorId}</code></dd></div>}
      {oracle && event.actorId && <div><dt>Actor</dt><dd><code>{event.actorId}</code></dd></div>}
      <div><dt>Source ID</dt><dd><code>{event.eventId}</code></dd></div>
    </dl></section> : <p className="replay-empty-inspector">Select an event to inspect its source evidence.</p>}
    {event && <EvidenceRows title="Details" entries={event.details} />}
    {oracle && <section className="replay-inspector-section" aria-labelledby="oracle-cause-heading"><h3 id="oracle-cause-heading">Simulated cause</h3>
      {frame?.sensorStates.some((sensor) => sensor.oracleCause) ? <dl>{frame.sensorStates.filter((sensor) => sensor.oracleCause).map((sensor) => <div key={sensor.observationId}><dt>{sensor.sensorId}</dt><dd>{value(sensor.oracleCause)}</dd></div>)}</dl> : <p>No oracle mapping for this instant.</p>}
    </section>}
    <section className="replay-inspector-section"><h3>Current state</h3>
      <dl><div><dt>Instant</dt><dd>{frame?.at ?? "Loading"}</dd></div><div><dt>Resources</dt><dd>{value(frame?.resourceAvailableUnits ?? {})}</dd></div></dl>
      <EvidenceRows title="Environment facts" entries={frame?.environmentFacts ?? {}} />
      {frame?.residents.length ? <ul className="replay-resident-states">{frame.residents.map((resident, index) => <li key={resident.residentId ?? index}><strong>{oracle ? resident.residentId ?? `Resident ${index + 1}` : `Resident ${index + 1}`}</strong><span>{resident.executionState}{resident.regionId ? ` · ${resident.regionId}` : ""}</span><code>{value(resident.facts)}</code></li>)}</ul> : <p>No resident state at this instant.</p>}
    </section>
  </aside>;
}
