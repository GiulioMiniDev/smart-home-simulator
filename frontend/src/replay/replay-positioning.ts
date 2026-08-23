import type { Point, ReplayEvent, ReplayEventWindow, ReplayFrame, ReplayResidentFrame, ReplayVisibilityMode } from "../types";

export function replayTimestamp(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function visibleMovement(frame: ReplayFrame | undefined, movement: ReplayEvent | undefined): ReplayEvent | undefined {
  if (!frame || !movement || movement.waypoints.length < 2) return undefined;
  const at = replayTimestamp(frame.at);
  const startsAt = replayTimestamp(movement.at);
  const endsAt = movement.end === null || movement.end === undefined
    ? replayTimestamp(movement.waypoints.at(-1)?.at)
    : replayTimestamp(movement.end);
  const usableWaypoints = movement.waypoints.every((waypoint) =>
    replayTimestamp(waypoint.at) !== undefined
    && Number.isFinite(waypoint.position.x)
    && Number.isFinite(waypoint.position.y),
  );
  if (!usableWaypoints || at === undefined || startsAt === undefined || endsAt === undefined || endsAt < startsAt) return undefined;
  return startsAt <= at && at <= endsAt ? movement : undefined;
}

function samePosition(left: Point | null | undefined, right: Point | undefined): boolean {
  return Boolean(left && right && Math.abs(left.x - right.x) <= .0001 && Math.abs(left.y - right.y) <= .0001);
}

/** The exact trace interpolation used only to associate Observable positions with a movement. */
export function movementPositionAt(movement: ReplayEvent, at: number): Point | undefined {
  const points = movement.waypoints.map((waypoint) => ({ waypoint, at: replayTimestamp(waypoint.at) })).filter((item): item is { waypoint: ReplayEvent["waypoints"][number]; at: number } => item.at !== undefined);
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

export function activeMovements(frame: ReplayFrame | undefined, events: ReplayEventWindow | undefined): ReplayEvent[] {
  return (events?.items ?? []).flatMap((event) => {
    const movement = event.kind === "movement" ? visibleMovement(frame, event) : undefined;
    return movement ? [movement] : [];
  });
}

export function residentMovementAssociations(
  residents: ReplayResidentFrame[],
  movements: ReplayEvent[],
  at: number | undefined,
  visibilityMode: ReplayVisibilityMode | undefined,
): Array<ReplayEvent | undefined> {
  if (at === undefined) return residents.map(() => undefined);
  const candidates = residents.map((resident) => movements.filter((movement) => visibilityMode === "oracle"
    ? Boolean(resident.residentId && movement.actorId === resident.residentId)
    : samePosition(resident.position, movementPositionAt(movement, at))));
  // Observable matching is valid only for a unique resident/movement pair. A tie means there is
  // no evidence to associate either marker with a route, so both retain their frame positions.
  return candidates.map((matches, residentIndex) => {
    if (matches.length !== 1) return undefined;
    const movement = matches[0]!;
    const claimedBy = candidates.filter((otherMatches) => otherMatches.includes(movement));
    return claimedBy.length === 1 && candidates[residentIndex]!.length === 1 ? movement : undefined;
  });
}
