import type { Point, ReplayEvent } from "../types";
import { currentRoute, interiorRoute, movementAt, movementPath, replayTimestamp, routePoseAt } from "./replay-positioning";
import type { ScenePlace } from "./replay-place";
import type { SceneWorld } from "./replay-world";

/** Where each person stands at an instant, and the path they are drawing while they walk. */
export interface ScenePose {
  position?: Point;
  heading?: number;
  travelled: Point[];
  /** 0 on a floor, 1 at the top of a flight: what the scene fades the body out and in by. */
  climbing: number;
  /** The storey the body is on, which is the storey the scene should be drawing. */
  level: number;
}

export interface SceneMotion {
  subscribe(listener: (atMs: number) => void): () => void;
  sample(atMs: number): Record<string, ScenePose>;
}

/** Pose sampling that walks one route's waypoints, not the whole day, on every frame. */
export function sceneMotion(
  world: SceneWorld,
  anchorMs: number | undefined,
  subscribe: (listener: (atMs: number) => void) => () => void,
  place: Pick<ScenePlace, "inside" | "levelOf"> = { inside: () => true, levelOf: () => 0 },
): SceneMotion {
  const residents = world.residents;
  const levelOf = (regionId: string) => place.levelOf(regionId);
  const still = (position: Point | undefined, level: number): ScenePose =>
    ({ position, travelled: [], climbing: 0, level });
  return {
    subscribe,
    sample: (atMs: number) => Object.fromEntries(residents.map((resident) => {
      // Somebody out of the flat has no place on this plan, and the leg that took them there
      // is a departure rather than a walk across the kitchen.
      if (resident.away) return [resident.residentId, still(undefined, levelOf(resident.regionId ?? ""))];
      const walked = resident.anchorPosition ? currentRoute(resident.routes, atMs, anchorMs) : undefined;
      const route = walked ? interiorRoute(walked, place.inside) : undefined;
      if (!route) return [resident.residentId, still(resident.anchorPosition, levelOf(resident.regionId ?? ""))];
      const moving = movementAt(route, atMs) !== undefined;
      const pose = routePoseAt(route, atMs, levelOf);
      const level = pose?.level ?? levelOf(resident.regionId ?? "");
      return [resident.residentId, {
        position: pose?.position ?? resident.anchorPosition,
        // On the stairs there is no direction to face: the body is not crossing the floor.
        heading: moving && !pose?.climbing ? routeHeading(route, atMs, levelOf) : undefined,
        travelled: moving ? movementPath(route, atMs, { level, levelOf }).travelled : [],
        climbing: pose?.climbing ?? 0,
        level,
      }];
    })),
  };
}

function routeHeading(route: ReplayEvent, atMs: number, levelOf: (regionId: string) => number): number | undefined {
  const pose = routePoseAt(route, atMs, levelOf);
  const next = route.waypoints.find((waypoint) => (replayTimestamp(waypoint.at) ?? Number.NEGATIVE_INFINITY) > atMs);
  if (!pose || !next) return undefined;
  const dx = next.position.x - pose.position.x;
  const dy = next.position.y - pose.position.y;
  return dx === 0 && dy === 0 ? undefined : Math.atan2(dy, dx);
}
