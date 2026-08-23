import { useMemo, useState } from "react";
import type { ReplayEvent, ReplayEventKind } from "../types";
import { clusterEvents } from "./replay-clock";
import type { ReplayController } from "./useReplayController";

// eslint-disable-next-line react-refresh/only-export-components -- fixed public replay-track contract
export const REPLAY_TRACKS: Array<{ label: string; kinds: ReplayEventKind[] }> = [
  { label: "Activities", kinds: ["activity"] }, { label: "Actions", kinds: ["action"] },
  { label: "Movements", kinds: ["movement"] }, { label: "Sensors", kinds: ["observation"] },
  { label: "State", kinds: ["state_transition"] }, { label: "Resources", kinds: ["resource"] },
  { label: "Runtime", kinds: ["runtime_event"] }, { label: "Deviations", kinds: ["plan_deviation"] },
];

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

export function ReplayTimeline({ controller }: { controller: ReplayController }) {
  const [selectedTracks, setSelectedTracks] = useState<ReplayEventKind[]>([]);
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(() => new Set());
  const events = controller.events?.items ?? [];
  const windowStart = Date.parse(controller.events?.windowStart ?? "");
  const windowEnd = Date.parse(controller.events?.windowEnd ?? "");
  const visible = selectedTracks.length ? events.filter((event) => selectedTracks.includes(event.kind)) : events;
  const clusters = useMemo(() => Number.isFinite(windowStart) && Number.isFinite(windowEnd)
    ? clusterEvents(visible, windowStart, windowEnd, 1000) : [], [visible, windowEnd, windowStart]);
  const byTime = useMemo(() => grouped(visible), [visible]);
  const ready = controller.status === "ready";
  const updateTrack = (track: typeof REPLAY_TRACKS[number], checked: boolean) => {
    const trackKinds = track.kinds;
    const next = checked
      ? [...new Set([...selectedTracks, ...trackKinds])]
      : selectedTracks.filter((kind) => !trackKinds.includes(kind));
    setSelectedTracks(next);
    controller.updateFilters({ eventKinds: next });
  };
  const toggleCluster = (clusterId: string) => setExpandedClusters((current) => {
    const next = new Set(current);
    if (next.has(clusterId)) next.delete(clusterId); else next.add(clusterId);
    return next;
  });
  return <section className="replay-timeline" aria-labelledby="replay-timeline-heading">
    <div className="replay-timeline-heading"><div><p className="eyebrow">Synchronized trace</p><h2 id="replay-timeline-heading">Event timeline</h2></div><span>{controller.events?.total ?? 0} events in window</span></div>
    <div className="replay-track-filters" role="group" aria-label="Timeline tracks">
      {REPLAY_TRACKS.map((track) => <label key={track.label}><input type="checkbox" checked={track.kinds.every((kind) => selectedTracks.includes(kind))} onChange={(event) => updateTrack(track, event.target.checked)} /> {track.label}</label>)}
    </div>
    <label className="replay-time-range"><span>Replay time <output>{controller.frame ? clock(controller.frame.at) : "Loading"}</output></span>
      <input aria-label="Replay time" type="range" min={Number.isFinite(windowStart) ? windowStart : 0} max={Number.isFinite(windowEnd) ? windowEnd : 1} value={controller.positionMs} disabled={!ready || !Number.isFinite(windowStart) || !Number.isFinite(windowEnd)} onChange={(event) => controller.seek(Number(event.target.value))} />
    </label>
    {controller.error && <p className="replay-request-error" role="alert">Replay window unavailable: {controller.error.message}</p>}
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
                ? <button type="button" className={`replay-cluster-mark ${controller.selectedEventId === clustered[0]?.eventId ? "is-selected" : ""}`} aria-label={`${clock(clustered[0]!.at)} ${clustered[0]!.label}`} disabled={!ready} onClick={() => controller.selectEvent(clustered[0]?.eventId)}>1</button>
                : <button type="button" className="replay-cluster-mark" aria-label={`${clustered.length} simultaneous events`} aria-expanded={expanded} aria-controls={clusterId} disabled={!ready} onClick={() => toggleCluster(clusterId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleCluster(clusterId); } }}>{clustered.length}</button>}
              {clustered.length > 1 && <div id={clusterId} className="replay-cluster-items" hidden={!expanded}>{clustered.map((event) => <button type="button" key={event.eventId} className={controller.selectedEventId === event.eventId ? "is-selected" : ""} aria-label={`${clock(event.at)} ${event.label}`} onClick={() => controller.selectEvent(event.eventId)}><time>{clock(event.at)}</time><span>{event.label}</span></button>)}</div>}
            </div>;
          })}
          {!items.length && <p>No {track.label.toLowerCase()} in this window.</p>}
        </div></div>;
      })}
    </div>
  </section>;
}
