import { useCallback, useEffect, useRef, useState } from "react";
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

function options(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

const ZOOM_OPTIONS = [
  [5 * 60 * 1000, "5m"], [15 * 60 * 1000, "15m"], [60 * 60 * 1000, "1h"],
  [6 * 60 * 60 * 1000, "6h"], [24 * 60 * 60 * 1000, "1d"], [7 * 24 * 60 * 60 * 1000, "7d"],
] as const;

export function ReplayTimeline({ controller, sensorModel }: { controller: ReplayController; sensorModel?: SensorModel }) {
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(() => new Set());
  const [laneWidths, setLaneWidths] = useState<Record<string, number>>({});
  const measuredLaneWidths = useRef<Record<string, number>>({});
  const observers = useRef(new Map<string, ResizeObserver>());
  const laneRefs = useRef(new Map<string, (node: HTMLDivElement | null) => void>());
  useEffect(() => () => {
    observers.current.forEach((observer) => observer.disconnect());
    observers.current.clear();
  }, []);
  const observeLane = useCallback((track: string) => {
    const existing = laneRefs.current.get(track);
    if (existing) return existing;
    const callback = (node: HTMLDivElement | null) => {
      observers.current.get(track)?.disconnect();
      observers.current.delete(track);
      if (!node) return;
      const update = () => {
        const measured = node.getBoundingClientRect().width;
        const width = Number.isFinite(measured) && measured > 0
          ? measured
          : Number.isFinite(node.clientWidth) && node.clientWidth > 0 ? node.clientWidth : undefined;
        if (width === undefined) return;
        if (measuredLaneWidths.current[track] === width) return;
        measuredLaneWidths.current = { ...measuredLaneWidths.current, [track]: width };
        setLaneWidths(measuredLaneWidths.current);
      };
      update();
      if (typeof ResizeObserver !== "undefined") {
        const observer = new ResizeObserver(update);
        observer.observe(node);
        observers.current.set(track, observer);
      }
    };
    laneRefs.current.set(track, callback);
    return callback;
  }, []);
  const events = controller.evidenceIncomplete ? [] : controller.events?.items ?? [];
  const windowStart = Date.parse(controller.events?.windowStart ?? "");
  const windowEnd = Date.parse(controller.events?.windowEnd ?? "");
  // An empty persisted filter has one deliberate meaning: every evidence track is visible.
  const selectedKinds = controller.filters.eventKinds.length ? controller.filters.eventKinds : ALL_EVENT_KINDS;
  const visible = events.filter((event) => selectedKinds.includes(event.kind));
  const ready = controller.status === "ready";
  const oracle = controller.filters.visibilityMode === "oracle";
  const sensorOptions = options([...(sensorModel?.sensors.map((sensor) => sensor.sensorId) ?? []), ...controller.filterOptions.sensorIds, ...controller.filters.sensorIds]);
  const residentOptions = options(oracle ? [...controller.filterOptions.actorIds, ...controller.filters.actorIds] : []);
  const statusOptions = options([...controller.filterOptions.statuses, ...controller.filters.statuses]);
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
      <label>Resident<select aria-label="Resident" value={controller.filters.actorIds[0] ?? ""} disabled={!oracle} aria-describedby={!oracle ? "resident-filter-help" : undefined} onChange={(event) => controller.updateFilters(event.target.value ? { actorIds: [event.target.value], selectedResidentId: event.target.value } : { actorIds: [], selectedResidentId: undefined })}><option value="">All residents</option>{residentOptions.map((resident) => <option key={resident} value={resident}>{resident}</option>)}</select></label>
      {!oracle && <span id="resident-filter-help" className="replay-filter-help">Resident filtering is available only in Oracle evidence.</span>}
      <label>Status<select aria-label="Event status" value={controller.filters.statuses[0] ?? ""} onChange={(event) => controller.updateFilters({ statuses: event.target.value ? [event.target.value] : [] })}><option value="">All statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
      <label>Zoom<select aria-label="Temporal zoom" value={controller.windowSpanMs} onChange={(event) => controller.setWindowSpan(Number(event.target.value))}>{ZOOM_OPTIONS.map(([span, label]) => <option key={span} value={span}>{label}</option>)}</select></label>
      <button type="button" onClick={() => controller.updateFilters({ eventKinds: [], sensorIds: [], actorIds: [], selectedResidentId: undefined, statuses: [] })}>Clear filters</button>
    </div>
    <label className="replay-time-range"><span>Replay time <output>{controller.frame ? clock(controller.frame.at) : "Loading"}</output></span>
      <input aria-label="Replay time" type="range" min={controller.traceStartMs ?? 0} max={controller.traceEndMs ?? 1} value={controller.positionMs} disabled={!ready || controller.evidenceIncomplete || controller.evidenceLoading || controller.traceStartMs === undefined || controller.traceEndMs === undefined} onChange={(event) => controller.seek(Number(event.target.value))} />
    </label>
    {controller.error && <p className="replay-request-error" role="alert">Replay window unavailable: {controller.error.message}</p>}
    {controller.windowNotice && <p className={controller.evidenceIncomplete ? "replay-request-error" : "replay-window-notice"} role="status">{controller.windowNotice}</p>}
    <div className="replay-track-list">
      {REPLAY_TRACKS.map((track) => {
        const items = visible.filter((event) => track.kinds.includes(event.kind));
        const laneWidth = laneWidths[track.label] ?? 720;
        const trackClusters = Number.isFinite(windowStart) && Number.isFinite(windowEnd)
          ? clusterEvents(items, windowStart, windowEnd, laneWidth) : [];
        return <div className="replay-track" key={track.label}><h3>{track.label}</h3><div ref={observeLane(track.label)} className="replay-track-events" aria-label={`${track.label} events`}>
          {trackClusters.map((cluster, clusterIndex) => {
            const clustered = cluster.eventIds.map((id) => items.find((event) => event.eventId === id)).filter((event): event is ReplayEvent => Boolean(event));
            if (!clustered.length) return null;
            const clusterId = `${track.label.toLowerCase()}-cluster-${clusterIndex}`;
            const expanded = expandedClusters.has(clusterId);
            return <div className="replay-event-cluster" style={{ left: `${Math.max(0, Math.min(100, cluster.x / laneWidth * 100))}%` }} key={cluster.eventIds.join("-")}>
              {clustered.length === 1
                ? <button type="button" className={`replay-cluster-mark ${controller.selectedEventId === clustered[0]?.eventId ? "is-selected" : ""}`} aria-label={`${clock(clustered[0]!.at)} ${clustered[0]!.label}`} disabled={!ready || controller.evidenceIncomplete || controller.evidenceLoading} onClick={() => controller.selectEvent(clustered[0]?.eventId)}>1</button>
                : <button type="button" className="replay-cluster-mark" aria-label={`${clustered.length} clustered events`} aria-expanded={expanded} aria-controls={clusterId} disabled={!ready || controller.evidenceIncomplete || controller.evidenceLoading} onClick={() => toggleCluster(clusterId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleCluster(clusterId); } }}>{clustered.length}</button>}
              {clustered.length > 1 && <div id={clusterId} className="replay-cluster-items" hidden={!expanded}>{clustered.map((event) => <button type="button" key={event.eventId} className={controller.selectedEventId === event.eventId ? "is-selected" : ""} aria-label={`${clock(event.at)} ${event.label}`} onClick={() => controller.selectEvent(event.eventId)}><time>{clock(event.at)}</time><span>{event.label}</span></button>)}</div>}
            </div>;
          })}
          {!items.length && <p>No {track.label.toLowerCase()} in this window.</p>}
        </div></div>;
      })}
    </div>
  </section>;
}
