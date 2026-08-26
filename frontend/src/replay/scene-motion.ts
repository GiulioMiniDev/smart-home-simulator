import type { Point, ReplayEvent } from "../types";
import { currentRoute, interiorRoute, movementAt, movementPath, movementPositionAt, replayTimestamp } from "./replay-positioning";
import type { SceneWorld } from "./replay-world";

/** Where each person stands at an instant, and the path they are drawing while they walk. */
export interface ScenePose {
  position?: Point;
  heading?: number;
  travelled: Point[];
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
  inside: (regionId: string) => boolean = () => true,
): SceneMotion {
  const residents = world.residents;
  return {
    subscribe,
    sample: (atMs: number) => Object.fromEntries(residents.map((resident) => {
      // Somebody out of the flat has no place on this plan, and the leg that took them there
      // is a departure rather than a walk across the kitchen.
      if (resident.away) return [resident.residentId, { position: undefined, travelled: [] }];
      const walked = resident.anchorPosition ? currentRoute(resident.routes, atMs, anchorMs) : undefined;
      const route = walked ? interiorRoute(walked, inside) : undefined;
      if (!route) return [resident.residentId, { position: resident.anchorPosition, travelled: [] }];
      const moving = movementAt(route, atMs) !== undefined;
      return [resident.residentId, {
        position: movementPositionAt(route, atMs) ?? resident.anchorPosition,
        heading: moving ? routeHeading(route, atMs) : undefined,
        travelled: moving ? movementPath(route, atMs).travelled : [],
      }];
    })),
  };
}

function routeHeading(route: ReplayEvent, atMs: number): number | undefined {
  const here = movementPositionAt(route, atMs);
  const next = route.waypoints.find((waypoint) => (replayTimestamp(waypoint.at) ?? Number.NEGATIVE_INFINITY) > atMs);
  if (!here || !next) return undefined;
  const dx = next.position.x - here.x;
  const dy = next.position.y - here.y;
  return dx === 0 && dy === 0 ? undefined : Math.atan2(dy, dx);
}
