import type { Point, ReplayEvent, ReplayWaypoint } from "../types";

export interface ReplayEventCluster {
  eventIds: string[];
  x: number;
}

/** Advance the one shared simulation clock without allowing it outside the known trace. */
export function advanceTime(
  positionMs: number,
  elapsedWallMs: number,
  speed: number,
  traceEndMs: number,
  traceStartMs = Number.NEGATIVE_INFINITY,
): number {
  const next = positionMs + elapsedWallMs * speed;
  return Math.min(traceEndMs, Math.max(traceStartMs, next));
}

/** Return the authoritative position at an instant, interpolated only between adjacent waypoints. */
export function interpolateWaypoints(waypoints: ReplayWaypoint[], atMs: number): Point | undefined {
  if (waypoints.length === 0) return undefined;
  const timed = waypoints
    .map((waypoint) => ({ waypoint, time: Date.parse(waypoint.at) }))
    .filter((item) => Number.isFinite(item.time))
    .sort((left, right) => left.time - right.time);
  if (timed.length === 0) return undefined;
  const first = timed[0]!;
  const last = timed.at(-1)!;
  if (atMs <= first.time) return first.waypoint.position;
  if (atMs >= last.time) return last.waypoint.position;
  const rightIndex = timed.findIndex((item) => item.time >= atMs);
  const right = timed[rightIndex]!;
  const left = timed[rightIndex - 1]!;
  const ratio = (atMs - left.time) / (right.time - left.time);
  return {
    x: left.waypoint.position.x + (right.waypoint.position.x - left.waypoint.position.x) * ratio,
    y: left.waypoint.position.y + (right.waypoint.position.y - left.waypoint.position.y) * ratio,
  };
}

/** Group adjacent visual marks while keeping every event selectable through its ID. */
export function clusterEvents(
  events: ReplayEvent[],
  windowStartMs: number,
  windowEndMs: number,
  widthPx: number,
): ReplayEventCluster[] {
  const span = windowEndMs - windowStartMs;
  const scale = span > 0 ? widthPx / span : 0;
  const positioned = events
    .map((event) => ({ event, time: Date.parse(event.at) }))
    .filter((item) => Number.isFinite(item.time))
    .sort((left, right) => left.time - right.time)
    .map(({ event, time }) => ({ eventId: event.eventId, x: (time - windowStartMs) * scale }));
  return positioned.reduce<ReplayEventCluster[]>((clusters, item) => {
    const previous = clusters.at(-1);
    if (previous && item.x - previous.x < 6) {
      previous.eventIds.push(item.eventId);
    } else {
      clusters.push({ eventIds: [item.eventId], x: item.x });
    }
    return clusters;
  }, []);
}
