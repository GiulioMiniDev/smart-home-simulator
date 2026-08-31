import { dwellingRegionIds } from "../editor";
import type { HomeModel, Point } from "../types";

/**
 * What the flat is, and what standing somewhere in it means.
 *
 * Two questions the scene keeps asking: is this region part of the home it draws, and is this
 * position a particular thing a resident is using. Both are answered from the home model alone,
 * so the answers are the same ones the plan editor would give.
 */

export interface SceneThing {
  entityId: string;
  /** The kind of thing it is, which is what a caption wants: "chair", "washing machine". */
  label: string;
}

export interface ScenePlace {
  inside(regionId: string | null | undefined): boolean;
  thingAt(position: Point | undefined): SceneThing | undefined;
  /**
   * Which storey a region is on.
   *
   * The scene draws one storey at a time, and the step between two of them is the one move in a
   * route that is not a walk across the floor. Both facts start here.
   */
  levelOf(regionId: string | null | undefined): number;
}

/** Positions are compared at millimetre resolution, which is finer than the trace records. */
function key(position: Point): string {
  return `${position.x.toFixed(3)},${position.y.toFixed(3)}`;
}

function words(value: string): string {
  return value.replaceAll("_", " ");
}

export function scenePlace(home: HomeModel | undefined): ScenePlace {
  const dwelling = home ? dwellingRegionIds(home) : new Set<string>();
  const points = new Map<string, string[]>();
  for (const point of home?.interactionPoints ?? []) {
    const at = key(point.position);
    points.set(at, [...points.get(at) ?? [], point.interactionPointId]);
  }
  const owners = new Map<string, { entityId: string; entityType: string }>();
  for (const entity of home?.entities ?? []) {
    const pointId = typeof entity.interactionPointId === "string" ? entity.interactionPointId : undefined;
    if (pointId) owners.set(pointId, { entityId: entity.entityId, entityType: entity.entityType });
  }

  const things = new Map<string, SceneThing>();
  for (const [at, pointIds] of points) {
    const claimed = pointIds.map((pointId) => owners.get(pointId));
    // A position several points share is the room's own anchor: every route into the room ends
    // there, so standing on it says nothing about using any one of the things that share it.
    if (claimed.some((owner) => owner === undefined)) continue;
    const real = claimed.filter((owner) => owner !== undefined)
      .filter((owner) => owner.entityType !== "generated_environment_service");
    if (real.length !== 1) continue;
    things.set(at, { entityId: real[0]!.entityId, label: words(real[0]!.entityType) });
  }

  const levels = new Map((home?.regions ?? []).map((region) => [region.regionId, region.level ?? 0]));

  return {
    inside: (regionId) => Boolean(regionId && dwelling.has(regionId)),
    thingAt: (position) => position ? things.get(key(position)) : undefined,
    levelOf: (regionId) => (regionId === null || regionId === undefined ? 0 : levels.get(regionId) ?? 0),
  };
}
