import { useMemo, useState } from "react";
import type { ReplayEvent, ReplayEventKind, SensorModel } from "../types";
import { clusterEvents } from "./replay-clock";
import type { ReplayController } from "./useReplayController";

// eslint-disable-next-line react-refresh/only-export-components -- fixed public replay-track contract
export const REPLAY_TRACKS: Array<{ label: string; kinds: ReplayEventKind[] }> = [
  { label: "Activities", kinds: ["activity"] }, { label: "Actions", kinds: ["action"] },
  { label: "Movements", kinds: ["movement"] }, { label: "Sensors", kinds: ["observation"] },
  { label: "State", kinds: ["state_transition"] }, { label: "Resources", kinds: ["resource"] },
  { label: "Runtime", kinds: ["runtime_event"] }, { label: "Deviations", kinds: ["plan_deviation"] },
];
const ALL_EVENT_KINDS = REPLAY_TRACKS.flatMap((track) => track.kinds);

function clock(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Unknown time" : `${String(parsed.getUTCHours()).padStart(2, "0")}:${String(parsed.getUTCMinutes()).padStart(2, "0")}`;
}

function grouped(events: ReplayEvent[]): Map<string, ReplayEvent[]> {
  return events.reduce((result, event) => {
    const key = event.at;
    result.set(key, [...(result.get(key) ?? []), event]);
    return result;
  }, new Map<string, ReplayEvent[]>());
}

function options(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

const ZOOM_OPTIONS = [
  [5 * 60 * 1000, "5m"], [15 * 60 * 1000, "15m"], [60 * 60 * 1000, "1h"],
  [6 * 60 * 60 * 1000, "6h"], [24 * 60 * 60 * 1000, "1d"], [7 * 24 * 60 * 60 * 1000, "7d"],
] as const;

export function ReplayTimeline({ controller, sensorModel }: { controller: ReplayController; sensorModel?: SensorModel }) {
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(() => new Set());
  const events = controller.evidenceIncomplete ? [] : controller.events?.items ?? [];
  const windowStart = Date.parse(controller.events?.windowStart ?? "");
  const windowEnd = Date.parse(controller.events?.windowEnd ?? "");
  // An empty persisted filter has one deliberate meaning: every evidence track is visible.
  const selectedKinds = controller.filters.eventKinds.length ? controller.filters.eventKinds : ALL_EVENT_KINDS;
  const visible = events.filter((event) => selectedKinds.includes(event.kind));
  const clusters = useMemo(() => Number.isFinite(windowStart) && Number.isFinite(windowEnd)
    ? clusterEvents(visible, windowStart, windowEnd, 1000) : [], [visible, windowEnd, windowStart]);
  const byTime = useMemo(() => grouped(visible), [visible]);
  const ready = controller.status === "ready";
  const oracle = controller.filters.visibilityMode === "oracle";
  const sensorOptions = options([...sensorModel?.sensors.map((sensor) => sensor.sensorId) ?? [], ...events.map((event) => event.sensorId), ...controller.filters.sensorIds]);
  const residentOptions = options(oracle ? [...events.map((event) => event.actorId), ...controller.frame?.residents.map((resident) => resident.residentId) ?? [], ...controller.filters.actorIds] : []);
  const statusOptions = options([...events.map((event) => event.status), ...controller.filters.statuses]);
  const updateTrack = (track: typeof REPLAY_TRACKS[number], checked: boolean) => {
    const nextKinds = checked
      ? ALL_EVENT_KINDS.filter((kind) => selectedKinds.includes(kind) || track.kinds.includes(kind))
      : selectedKinds.filter((kind) => !track.kinds.includes(kind));
    // Never let a final unchecked box accidentally serialize as [] (which means all tracks).
    if (!nextKinds.length) return;
    controller.updateFilters({ eventKinds: nextKinds.length === ALL_EVENT_KINDS.length ? [] : nextKinds });
  };
  const toggleCluster = (clusterId: string) => setExpandedClusters((current) => {
    const next = new Set(current);
    if (next.has(clusterId)) next.delete(clusterId); else next.add(clusterId);
    return next;
  });
  return <section className="replay-timeline" aria-labelledby="replay-timeline-heading">
    <div className="replay-timeline-heading"><div><p className="eyebrow">Synchronized trace</p><h2 id="replay-timeline-heading">Event timeline</h2></div><span>{controller.events?.total ?? 0} events in window</span></div>
    <div className="replay-track-filters" role="group" aria-label="Timeline tracks">
      {REPLAY_TRACKS.map((track) => <label key={track.label}><input type="checkbox" checked={track.kinds.every((kind) => selectedKinds.includes(kind))} onChange={(event) => updateTrack(track, event.target.checked)} /> {track.label}</label>)}
    </div>
    <div className="replay-analysis-filters" role="group" aria-label="Evidence filters">
      <label>Sensor<select aria-label="Sensor" value={controller.filters.sensorIds[0] ?? ""} onChange={(event) => controller.updateFilters({ sensorIds: event.target.value ? [event.target.value] : [] })}><option value="">All sensors</option>{sensorOptions.map((sensor) => <option key={sensor} value={sensor}>{sensor}</option>)}</select></label>
      <label>Resident<select aria-label="Resident" value={controller.filters.actorIds[0] ?? ""} disabled={!oracle} aria-describedby={!oracle ? "resident-filter-help" : undefined} onChange={(event) => controller.updateFilters({ actorIds: event.target.value ? [event.target.value] : [] })}><option value="">All residents</option>{residentOptions.map((resident) => <option key={resident} value={resident}>{resident}</option>)}</select></label>
      {!oracle && <span id="resident-filter-help" className="replay-filter-help">Resident filtering is available only in Oracle evidence.</span>}
      <label>Status<select aria-label="Event status" value={controller.filters.statuses[0] ?? ""} onChange={(event) => controller.updateFilters({ statuses: event.target.value ? [event.target.value] : [] })}><option value="">All statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
      <label>Zoom<select aria-label="Temporal zoom" value={controller.windowSpanMs} onChange={(event) => controller.setWindowSpan(Number(event.target.value))}>{ZOOM_OPTIONS.map(([span, label]) => <option key={span} value={span}>{label}</option>)}</select></label>
      <button type="button" onClick={() => controller.updateFilters({ eventKinds: [], sensorIds: [], actorIds: [], statuses: [] })}>Clear filters</button>
    </div>
    <label className="replay-time-range"><span>Replay time <output>{controller.frame ? clock(controller.frame.at) : "Loading"}</output></span>
      <input aria-label="Replay time" type="range" min={Number.isFinite(windowStart) ? windowStart : 0} max={Number.isFinite(windowEnd) ? windowEnd : 1} value={controller.positionMs} disabled={!ready || controller.evidenceIncomplete || !Number.isFinite(windowStart) || !Number.isFinite(windowEnd)} onChange={(event) => controller.seek(Number(event.target.value))} />
    </label>
    {controller.error && <p className="replay-request-error" role="alert">Replay window unavailable: {controller.error.message}</p>}
    {controller.windowNotice && <p className={controller.evidenceIncomplete ? "replay-request-error" : "replay-window-notice"} role="status">{controller.windowNotice}</p>}
    <div className="replay-track-list">
      {REPLAY_TRACKS.map((track) => {
        const items = visible.filter((event) => track.kinds.includes(event.kind));
        return <div className="replay-track" key={track.label}><h3>{track.label}</h3><div className="replay-track-events" aria-label={`${track.label} events`}>
          {clusters.filter((cluster) => byTime.has(events.find((event) => event.eventId === cluster.eventIds[0])?.at ?? "")).map((cluster, clusterIndex) => {
            const clustered = cluster.eventIds.map((id) => items.find((event) => event.eventId === id)).filter((event): event is ReplayEvent => Boolean(event));
            if (!clustered.length) return null;
            const clusterId = `${track.label.toLowerCase()}-cluster-${clusterIndex}`;
            const expanded = expandedClusters.has(clusterId);
            return <div className="replay-event-cluster" style={{ left: `${Math.max(0, Math.min(100, cluster.x / 10))}%` }} key={cluster.eventIds.join("-")}>
              {clustered.length === 1
                ? <button type="button" className={`replay-cluster-mark ${controller.selectedEventId === clustered[0]?.eventId ? "is-selected" : ""}`} aria-label={`${clock(clustered[0]!.at)} ${clustered[0]!.label}`} disabled={!ready || controller.evidenceIncomplete} onClick={() => controller.selectEvent(clustered[0]?.eventId)}>1</button>
                : <button type="button" className="replay-cluster-mark" aria-label={`${clustered.length} simultaneous events`} aria-expanded={expanded} aria-controls={clusterId} disabled={!ready || controller.evidenceIncomplete} onClick={() => toggleCluster(clusterId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleCluster(clusterId); } }}>{clustered.length}</button>}
              {clustered.length > 1 && <div id={clusterId} className="replay-cluster-items" hidden={!expanded}>{clustered.map((event) => <button type="button" key={event.eventId} className={controller.selectedEventId === event.eventId ? "is-selected" : ""} aria-label={`${clock(event.at)} ${event.label}`} onClick={() => controller.selectEvent(event.eventId)}><time>{clock(event.at)}</time><span>{event.label}</span></button>)}</div>}
            </div>;
          })}
          {!items.length && <p>No {track.label.toLowerCase()} in this window.</p>}
        </div></div>;
      })}
    </div>
  </section>;
}
