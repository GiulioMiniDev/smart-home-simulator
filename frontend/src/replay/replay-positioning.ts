import type { Point, ReplayEvent } from "../types";

/** Sub-millisecond digits, which `Date.parse` is free to discard, split off from the rest. */
const SUB_MILLISECOND = /^(.*\.\d{3})(\d+)(.*)$/;

/**
 * A trace instant in milliseconds, keeping the microseconds the trace actually recorded.
 *
 * `Date.parse` resolves to whole milliseconds, and a waypoint a fraction of a millisecond off
 * shifts the position interpolated between waypoints by millimetres. The digits are separated
 * before parsing rather than after, because whether an engine truncates or rounds the ones it
 * cannot represent is not something to depend on.
 */
export function replayTimestamp(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const precise = SUB_MILLISECOND.exec(value);
  const parsed = Date.parse(precise ? `${precise[1]}${precise[3]}` : value);
  if (!Number.isFinite(parsed)) return undefined;
  return precise ? parsed + Number(`0.${precise[2]}`) : parsed;
}

/** The instants a movement covers, or nothing when its waypoints cannot carry a position. */
function movementSpan(movement: ReplayEvent): { start: number; end: number } | undefined {
  if (movement.waypoints.length < 2) return undefined;
  const startsAt = replayTimestamp(movement.at);
  const endsAt = movement.end === null || movement.end === undefined
    ? replayTimestamp(movement.waypoints.at(-1)?.at)
    : replayTimestamp(movement.end);
  const usableWaypoints = movement.waypoints.every((waypoint) =>
    replayTimestamp(waypoint.at) !== undefined
    && Number.isFinite(waypoint.position.x)
    && Number.isFinite(waypoint.position.y),
  );
  if (!usableWaypoints || startsAt === undefined || endsAt === undefined || endsAt < startsAt) return undefined;
  return { start: startsAt, end: endsAt };
}

/** The movement the trace says is under way at this instant, or nothing. */
export function movementAt(movement: ReplayEvent | undefined, atMs: number | undefined): ReplayEvent | undefined {
  if (!movement || atMs === undefined) return undefined;
  const span = movementSpan(movement);
  return span && span.start <= atMs && atMs < span.end ? movement : undefined;
}

/** When a route set someone down, by its own evidence. */
export function movementEnd(movement: ReplayEvent | undefined): number | undefined {
  return movement ? movementSpan(movement)?.end : undefined;
}

/** Whether a movement carries enough waypoint evidence to place anyone anywhere. */
export function isUsableRoute(movement: ReplayEvent | undefined): boolean {
  return Boolean(movement && movementSpan(movement) !== undefined);
}

/** How far along its route a movement has come, as a fraction of its own duration. */
export function movementProgress(movement: ReplayEvent, atMs: number): number {
  const span = movementSpan(movement);
  if (!span || span.end === span.start) return 1;
  return Math.min(1, Math.max(0, (atMs - span.start) / (span.end - span.start)));
}

/** The last route started at or before an instant, under way or already finished. */
export function routeAt(movements: ReplayEvent[], atMs: number | undefined): ReplayEvent | undefined {
  if (atMs === undefined) return undefined;
  return movements
    .filter(isUsableRoute)
    .map((movement) => ({ movement, at: replayTimestamp(movement.at)! }))
    .filter((item) => item.at <= atMs)
    .sort((left, right) => left.at - right.at)
    .at(-1)?.movement;
}

/**
 * The route that may speak for someone at this instant.
 *
 * A route under way always may: at the anchor's own instant it reproduces exactly what the
 * frame reports, and past it, it is the only evidence there is. A route that has already
 * finished may only speak for instants the anchor cannot know about yet -- otherwise the
 * authoritative frame, which has seen everything up to its own instant, stays in charge.
 */
export function currentRoute(
  routes: ReplayEvent[],
  atMs: number | undefined,
  anchorMs: number | undefined,
): ReplayEvent | undefined {
  const route = routeAt(routes, atMs);
  if (!route) return undefined;
  if (movementAt(route, atMs) !== undefined) return route;
  return anchorMs === undefined || (movementEnd(route) ?? Number.NEGATIVE_INFINITY) > anchorMs
    ? route
    : undefined;
}

/**
 * The stretch of a route that stays inside the flat.
 *
 * A trip out of the home is one waypoint in the living room and the next one twenty metres
 * south, because that is how far away the trace puts the office. Interpolating between them
 * draws a line straight through the kitchen and out through a wall, which is not a walk anyone
 * took; the honest reading is that the route ends at the door and the resident is then away.
 */
export function interiorRun(
  movement: ReplayEvent,
  inside: (regionId: string) => boolean,
): { from: number; to: number } | undefined {
  const flags = movement.waypoints.map((waypoint) => inside(waypoint.regionId));
  const from = flags.indexOf(true);
  if (from < 0) return undefined;
  let to = from;
  while (to + 1 < flags.length && flags[to + 1]) to += 1;
  return { from, to };
}

/** The same route with everything outside the flat trimmed off both ends. */
export function interiorRoute(
  movement: ReplayEvent,
  inside: (regionId: string) => boolean,
): ReplayEvent | undefined {
  const run = interiorRun(movement, inside);
  if (!run) return undefined;
  return { ...movement, waypoints: movement.waypoints.slice(run.from, run.to + 1) };
}

/** Where a route puts someone at an instant, clamped to its own ends. */
export function movementPositionAt(movement: ReplayEvent, at: number): Point | undefined {
  const points = movement.waypoints
    .map((waypoint) => ({ waypoint, at: replayTimestamp(waypoint.at) }))
    .filter((item): item is { waypoint: ReplayEvent["waypoints"][number]; at: number } => item.at !== undefined);
  const before = points.filter((item) => item.at <= at).at(-1);
  const after = points.find((item) => item.at > at);
  if (!before) return after?.waypoint.position;
  if (!after || after.at === before.at) return before.waypoint.position;
  const ratio = (at - before.at) / (after.at - before.at);
  return {
    x: before.waypoint.position.x + (after.waypoint.position.x - before.waypoint.position.x) * ratio,
    y: before.waypoint.position.y + (after.waypoint.position.y - before.waypoint.position.y) * ratio,
  };
}

/** Duplicate waypoint timestamps are right-continuous: the last supplied point is the trace state. */
export function waypointAtOrBefore(movement: ReplayEvent, at: number): ReplayEvent["waypoints"][number] | undefined {
  return movement.waypoints.filter((waypoint) => (replayTimestamp(waypoint.at) ?? Number.POSITIVE_INFINITY) <= at).at(-1);
}

/**
 * Where a route puts someone, on which storey, and how far up the stairs they are.
 *
 * Every leg of a route is a walk across a floor except one: the step between two storeys. Those
 * two waypoints are metres apart on the page and one flight apart in the house, so interpolating
 * between them slides the body across rooms it is not in and through the walls between — the same
 * lie `interiorRun` refuses for the leg that leaves the flat, told inside it.
 *
 * So a climb is not walked. The body waits at the foot of the flight, the stairs take it, and it
 * arrives at the head: `climbing` rises to 1 as it goes and falls back to 0 as it lands, and the
 * storey changes at the halfway point, which is the moment the scene has to change floors too.
 * That is also the honest reading of the evidence, which says only that she left the bottom at one
 * instant and reached the top at another.
 */
export interface RoutePose {
  position: Point;
  /** The region the body counts as being in: the one it left until halfway, then the one it reaches. */
  regionId: string;
  level: number;
  /** 0 on a floor; 1 at the instant the flight hands the body to the other storey. */
  climbing: number;
}

export function routePoseAt(
  movement: ReplayEvent,
  atMs: number,
  levelOf: (regionId: string) => number,
): RoutePose | undefined {
  const points = movement.waypoints
    .map((waypoint) => ({ waypoint, at: replayTimestamp(waypoint.at) }))
    .filter((item): item is { waypoint: ReplayEvent["waypoints"][number]; at: number } => item.at !== undefined);
  const before = points.filter((item) => item.at <= atMs).at(-1);
  const after = points.find((item) => item.at > atMs);
  const settled = (item: typeof before) => item && {
    position: item.waypoint.position,
    regionId: item.waypoint.regionId,
    level: levelOf(item.waypoint.regionId),
    climbing: 0,
  };
  if (!before) return settled(after) ?? undefined;
  if (!after || after.at === before.at) return settled(before) ?? undefined;

  const ratio = (atMs - before.at) / (after.at - before.at);
  const from = levelOf(before.waypoint.regionId);
  const to = levelOf(after.waypoint.regionId);
  if (from !== to) {
    const landed = ratio >= .5;
    const end = landed ? after : before;
    return {
      position: end.waypoint.position,
      regionId: end.waypoint.regionId,
      level: landed ? to : from,
      climbing: landed ? (1 - ratio) * 2 : ratio * 2,
    };
  }
  return {
    position: {
      x: before.waypoint.position.x + (after.waypoint.position.x - before.waypoint.position.x) * ratio,
      y: before.waypoint.position.y + (after.waypoint.position.y - before.waypoint.position.y) * ratio,
    },
    regionId: before.waypoint.regionId,
    level: from,
    climbing: 0,
  };
}

/**
 * The route split at an instant: where the resident has walked, and where it is still going.
 *
 * Given a storey, only the part of the route on it — a trail drawn straight through the flight
 * would cross the whole plan, which is the picture the climb exists to avoid.
 */
export function movementPath(
  movement: ReplayEvent,
  atMs: number,
  on?: { level: number; levelOf: (regionId: string) => number },
): { travelled: Point[]; remaining: Point[] } {
  const here = on
    ? (() => {
        const pose = routePoseAt(movement, atMs, on.levelOf);
        return pose && pose.level === on.level ? pose.position : undefined;
      })()
    : movementPositionAt(movement, atMs);
  const drawn = (waypoint: ReplayEvent["waypoints"][number]) =>
    !on || on.levelOf(waypoint.regionId) === on.level;
  const behind = movement.waypoints.filter((waypoint) =>
    (replayTimestamp(waypoint.at) ?? Number.POSITIVE_INFINITY) <= atMs && drawn(waypoint));
  const ahead = movement.waypoints.filter((waypoint) =>
    (replayTimestamp(waypoint.at) ?? Number.NEGATIVE_INFINITY) > atMs && drawn(waypoint));
  return {
    travelled: [...behind.map((waypoint) => waypoint.position), ...(here ? [here] : [])],
    remaining: [...(here ? [here] : []), ...ahead.map((waypoint) => waypoint.position)],
  };
}
