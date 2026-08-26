import type { Point, ReplayEvent, ReplayFrame } from "../types";
import { currentRoute, interiorRoute, movementAt, movementPositionAt, replayTimestamp, waypointAtOrBefore } from "./replay-positioning";
import type { ScenePlace, SceneThing } from "./replay-place";
import { residentName, type SceneScript } from "./replay-script";

/**
 * The state of the flat at an instant, folded from one authoritative frame plus the day's own
 * state transitions.
 *
 * Reading it this way costs a single frame request per day: everything after that is arithmetic
 * over evidence already in the browser, which is what lets the scene run at the screen's rate
 * instead of the network's.
 */

export interface WorldEntity {
  open: boolean;
  active: boolean;
}

export interface WorldResident {
  residentId: string;
  name: string;
  posture: string;
  carrying: string[];
  regionId?: string;
  position?: Point;
  heading?: number;
  moving: boolean;
  /** Out of the flat: nothing the scene draws can show where, so it does not pretend to. */
  away: boolean;
  /** The thing they are standing at, when the position names exactly one. */
  using?: SceneThing;
  route?: ReplayEvent;
  routes: ReplayEvent[];
  anchorPosition?: Point;
}

export interface SceneWorld {
  atMs: number;
  entities: Record<string, WorldEntity>;
  residents: WorldResident[];
}

const CARRYING = "resident.carrying.";

function baseEntities(frame: ReplayFrame | undefined): Record<string, WorldEntity> {
  const entities: Record<string, WorldEntity> = {};
  for (const [entityId, state] of Object.entries(frame?.entityStates ?? {})) {
    entities[entityId] = { open: state.open === true, active: state.active === true };
  }
  return entities;
}

function baseCarrying(facts: Record<string, unknown>): Set<string> {
  const carried = new Set<string>();
  for (const [fact, value] of Object.entries(facts)) {
    if (fact.startsWith("carrying.") && value === true) carried.add(fact.slice("carrying.".length));
  }
  return carried;
}

/** Which way a walker is facing, from the step of route they are on. */
function heading(route: ReplayEvent, atMs: number): number | undefined {
  const here = movementPositionAt(route, atMs);
  const next = route.waypoints.find((waypoint) => (replayTimestamp(waypoint.at) ?? -Infinity) > atMs);
  if (!here || !next) return undefined;
  const dx = next.position.x - here.x;
  const dy = next.position.y - here.y;
  return dx === 0 && dy === 0 ? undefined : Math.atan2(dy, dx);
}

export function foldWorld(
  script: SceneScript,
  frame: ReplayFrame | undefined,
  atMs: number,
  place: ScenePlace,
): SceneWorld {
  const anchorMs = replayTimestamp(frame?.at);
  const entities = baseEntities(frame);
  const postures = new Map<string, string>();
  const carrying = new Map<string, Set<string>>();
  for (const resident of frame?.residents ?? []) {
    const residentId = resident.residentId ?? "resident";
    postures.set(residentId, resident.posture ?? "standing");
    carrying.set(residentId, baseCarrying(resident.facts));
  }

  for (const transition of script.transitions) {
    const transitionMs = replayTimestamp(transition.at);
    // A transition the clock has not reached yet is not part of the world it is drawing.
    if (transitionMs === undefined || transitionMs > atMs) continue;
    if (anchorMs !== undefined && transitionMs < anchorMs) continue;
    const value = transition.details.value;
    if (transition.label === "resident.posture" && typeof value === "string" && transition.actorId) {
      postures.set(transition.actorId, value);
      continue;
    }
    if (transition.label.startsWith(CARRYING) && transition.actorId) {
      const held = carrying.get(transition.actorId) ?? new Set<string>();
      const item = transition.label.slice(CARRYING.length);
      if (value === true) held.add(item); else held.delete(item);
      carrying.set(transition.actorId, held);
      continue;
    }
    const subjectId = transition.details.subjectId;
    if (typeof subjectId !== "string") continue;
    const state = entities[subjectId] ?? { open: false, active: false };
    if (transition.label === "entity.open") entities[subjectId] = { ...state, open: value === true };
    else if (transition.label === "entity.active") entities[subjectId] = { ...state, active: value === true };
  }

  const residents = (frame?.residents ?? []).map((resident): WorldResident => {
    const residentId = resident.residentId ?? "resident";
    const routes = script.movements.filter((movement) => movement.actorId === residentId);
    const walked = currentRoute(routes, atMs, anchorMs);
    // Where they are now is the last step of the route they are on. The day's anchor frame is a
    // single instant -- midnight -- and a resident who was out for the evening is still out in
    // it twenty hours later, so it can only answer this before the day's first route.
    const stepped = walked ? waypointAtOrBefore(walked, atMs) : undefined;
    const regionId = stepped?.regionId ?? resident.regionId ?? undefined;
    const away = !place.inside(regionId);
    // Only the part of a route that stays in the flat can put anybody anywhere on this plan.
    const route = walked ? interiorRoute(walked, place.inside) : undefined;
    const anchorPosition = resident.position ?? undefined;
    const routed = route !== undefined && anchorPosition !== undefined;
    const moving = !away && routed && movementAt(route, atMs) !== undefined;
    const position = (routed ? movementPositionAt(route, atMs) : undefined) ?? anchorPosition;
    return {
      residentId,
      name: residentName(residentId),
      posture: postures.get(residentId) ?? resident.posture ?? "standing",
      carrying: [...(carrying.get(residentId) ?? new Set<string>())],
      regionId,
      position: away ? undefined : position,
      heading: moving ? heading(route, atMs) : undefined,
      moving,
      away,
      using: away || moving ? undefined : place.thingAt(position),
      route: moving ? route : undefined,
      routes,
      anchorPosition,
    };
  });

  return { atMs, entities, residents };
}
