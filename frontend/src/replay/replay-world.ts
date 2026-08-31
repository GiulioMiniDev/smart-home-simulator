import type { Point, ReplayEvent, ReplayFrame } from "../types";
import { currentRoute, interiorRoute, movementAt, replayTimestamp, routePoseAt } from "./replay-positioning";
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
  /** The free floor she walked to: what routes are planned from, and what names the thing in use. */
  position?: Point;
  /**
   * Where the body has come to rest, when the trace says it has.
   *
   * An interaction point is where you *stand* to use a thing, so on its own it draws a resident
   * asleep on the carpet beside her bed. The engine records the berth she is actually on as a
   * fact about her, and this is that fact. Absent on traces written before it existed, and on a
   * body that is on its feet.
   */
  restingAt?: Point;
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
const RESTING = "resident.resting_at";

/** A berth only speaks for the room it is in, and only for a body that is still in that room. */
function restingHere(
  place: { at: Point; regionId: string } | undefined,
  regionId: string | undefined,
): Point | undefined {
  if (!place || regionId === undefined) return undefined;
  return place.regionId === "" || place.regionId === regionId ? place.at : undefined;
}

/**
 * The `{x, y}` a resting fact carries, with the room it belongs to, or nothing when it says she is
 * back on her feet.
 *
 * The room comes along because a berth means nothing outside it. The engine releases one as soon
 * as the posture holding it ends, so a fresh trace never carries a stale berth — but a trace
 * written before that did, and a body drawn on a sofa two rooms away is worse than no answer.
 */
function restingPoint(value: unknown): { at: Point; regionId: string } | undefined {
  if (value === null || typeof value !== "object") return undefined;
  const { x, y, regionId } = value as { x?: unknown; y?: unknown; regionId?: unknown };
  return typeof x === "number" && typeof y === "number"
    ? { at: { x, y }, regionId: typeof regionId === "string" ? regionId : "" }
    : undefined;
}

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
function heading(route: ReplayEvent, atMs: number, levelOf: (regionId: string) => number): number | undefined {
  const pose = routePoseAt(route, atMs, levelOf);
  const next = route.waypoints.find((waypoint) => (replayTimestamp(waypoint.at) ?? -Infinity) > atMs);
  // A body on the stairs is not crossing a floor, so it has no bearing on this one.
  if (!pose || !next || pose.climbing > 0) return undefined;
  const dx = next.position.x - pose.position.x;
  const dy = next.position.y - pose.position.y;
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
  const resting = new Map<string, { at: Point; regionId: string } | undefined>();
  for (const resident of frame?.residents ?? []) {
    const residentId = resident.residentId ?? "resident";
    postures.set(residentId, resident.posture ?? "standing");
    carrying.set(residentId, baseCarrying(resident.facts));
    // Seeded from the frame like the other two, and for a reason the other two never show: a day
    // opens at midnight with the resident asleep, so the very first thing the scene draws is a
    // body on a berth no transition in this day has got round to announcing yet.
    resting.set(residentId, restingPoint(resident.facts.resting_at));
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
    if (transition.label === RESTING && transition.actorId) {
      resting.set(transition.actorId, restingPoint(value));
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
    // Where they are now is the pose the route puts them in. On a flight of stairs that is the
    // storey they left until halfway and the one they reach after, because the scene has to change
    // floors at some instant and the middle of the climb is the only one that is not a lurch.
    const pose = walked ? routePoseAt(walked, atMs, place.levelOf) : undefined;
    const regionId = pose?.regionId ?? resident.regionId ?? undefined;
    const away = !place.inside(regionId);
    // Only the part of a route that stays in the flat can put anybody anywhere on this plan.
    const route = walked ? interiorRoute(walked, place.inside) : undefined;
    const anchorPosition = resident.position ?? undefined;
    const routed = route !== undefined && anchorPosition !== undefined;
    const moving = !away && routed && movementAt(route, atMs) !== undefined;
    const position = (routed ? routePoseAt(route, atMs, place.levelOf)?.position : undefined) ?? anchorPosition;
    return {
      residentId,
      name: residentName(residentId),
      posture: postures.get(residentId) ?? resident.posture ?? "standing",
      restingAt: restingHere(resting.get(residentId), away ? undefined : regionId),
      carrying: [...(carrying.get(residentId) ?? new Set<string>())],
      regionId,
      position: away ? undefined : position,
      heading: moving ? heading(route, atMs, place.levelOf) : undefined,
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
