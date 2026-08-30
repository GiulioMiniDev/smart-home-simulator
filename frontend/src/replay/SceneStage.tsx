import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { cutDoorways, dwellingRegionIds, planDoors, planWalls } from "../editor";
import { furnitureSymbol, structuralSymbol } from "../furniture";
import { FurnitureGlyph } from "../furniture-glyph";
import { FurnitureSymbols } from "../furniture-symbols";
import { CustomFurnitureSymbols } from "../vocabulary/CustomFurnitureSymbols";
import type { HomeModel, Point } from "../types";
import type { SceneWorld, WorldResident } from "./replay-world";
import type { SceneMotion } from "./scene-motion";

/** Metres of empty floor kept around the flat so nothing touches the edge of the picture. */
const MARGIN = .6;

function bounds(points: Point[]): { minX: number; minY: number; maxX: number; maxY: number } {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
}

function polygonPoints(points: Point[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

function words(value: string): string {
  return value.replaceAll("_", " ");
}

/**
 * The flat, once: rooms, walls, doors and the furniture that stands in them.
 *
 * The geometry is the same the plan editor draws, because it is the same home. What differs is
 * everything else -- no grid, no measurements, no device glyphs -- because this picture is for
 * watching somebody live in the place rather than for checking where a wall is.
 */
function useSet(home: HomeModel | undefined, storey: number) {
  return useMemo(() => {
    if (!home) return undefined;
    // One storey at a time. Two floors live in one coordinate plane, side by side and metres apart,
    // so a house drawn whole is two half-size floors with a gulf between them and a resident who
    // teleports across it on the stairs. The camera follows her up instead.
    const dwelling = new Set(
      [...dwellingRegionIds(home)].filter((regionId) =>
        home.regions.some(
          (region) => region.regionId === regionId && (region.level ?? 0) === storey,
        ),
      ),
    );
    const regions = home.regions.filter((region) => dwelling.has(region.regionId));
    if (regions.length === 0) return undefined;
    const walls = cutDoorways(planWalls(home, dwelling), planDoors(home, dwelling));
    const doors = planDoors(home, dwelling);
    const entityByObstacle = new Map(home.entities.map((entity) => [`obstacle_${entity.entityId}`, entity]));
    const furniture = home.obstacles
      .filter((obstacle) => obstacle.regionId === undefined || dwelling.has(obstacle.regionId))
      .map((obstacle) => {
        const entity = entityByObstacle.get(obstacle.obstacleId);
        return {
          obstacleId: obstacle.obstacleId,
          entityId: entity?.entityId,
          entityType: entity?.entityType,
          symbol: furnitureSymbol(entity?.entityType) ?? structuralSymbol(obstacle.obstacleId),
          orientationDegrees: obstacle.orientationDegrees,
          vertices: obstacle.boundary.vertices,
          box: bounds(obstacle.boundary.vertices),
        };
      });
    const extent = bounds(regions.flatMap((region) => region.boundary.vertices));
    return {
      regions, walls, doors, furniture,
      view: {
        x: extent.minX - MARGIN,
        y: extent.minY - MARGIN,
        width: extent.maxX - extent.minX + MARGIN * 2,
        height: extent.maxY - extent.minY + MARGIN * 2,
      },
    };
  }, [home, storey]);
}

/** The storey to draw: the one somebody is standing on, and the ground floor when nobody is. */
function occupiedStorey(home: HomeModel | undefined, regionIds: (string | undefined)[]): number {
  if (!home) return 0;
  for (const regionId of regionIds) {
    const region = home.regions.find((item) => item.regionId === regionId);
    if (region) return region.level ?? 0;
  }
  return 0;
}

function Avatar({ resident }: { resident: WorldResident }) {
  const carrying = resident.carrying.length > 0;
  return (
    <g className="scene-avatar" data-posture={resident.posture} data-moving={resident.moving ? "true" : "false"}>
      <ellipse className="scene-avatar-shadow" cx="0" cy=".2" rx=".22" ry=".08" />
      <g className="scene-avatar-body">
        {resident.posture === "lying" ? (
          <>
            <rect x="-.34" y="-.12" width=".62" height=".24" rx=".12" className="scene-avatar-torso" />
            <circle cx="-.36" cy="0" r=".12" className="scene-avatar-head" />
          </>
        ) : (
          <>
            <rect
              x="-.15"
              y={resident.posture === "sitting" ? "-.02" : "-.08"}
              width=".3"
              height={resident.posture === "sitting" ? ".22" : ".3"}
              rx=".14"
              className="scene-avatar-torso"
            />
            <circle cx="0" cy={resident.posture === "sitting" ? "-.14" : "-.2"} r=".13" className="scene-avatar-head" />
          </>
        )}
      </g>
      {carrying && <rect className="scene-avatar-load" x=".13" y="-.06" width=".16" height=".16" rx=".03" />}
    </g>
  );
}

export function SceneStage({
  home,
  world,
  motion,
  activeRegionId,
  usingEntityId,
}: {
  home: HomeModel | undefined;
  world: SceneWorld;
  motion?: SceneMotion;
  activeRegionId?: string;
  usingEntityId?: string;
}) {
  const storey = occupiedStorey(home, [
    activeRegionId,
    ...world.residents.map((resident) => resident.regionId),
  ]);
  const set = useSet(home, storey);
  const markers = useRef(new Map<string, SVGGElement | null>());
  const trails = useRef(new Map<string, SVGPolylineElement | null>());
  const sample = useRef(motion?.sample);
  const lastAt = useRef<number | undefined>(undefined);
  sample.current = motion?.sample;

  const pose = useCallback((atMs: number | undefined) => {
    if (atMs === undefined) return;
    const poses = sample.current?.(atMs);
    if (!poses) return;
    for (const [residentId, item] of Object.entries(poses)) {
      const marker = markers.current.get(residentId);
      if (marker && item.position) {
        const facing = item.heading === undefined ? "" : ` rotate(${String((item.heading * 180) / Math.PI)})`;
        marker.setAttribute("transform", `translate(${String(item.position.x)} ${String(item.position.y)})${facing}`);
      }
      trails.current.get(residentId)?.setAttribute("points", polygonPoints(item.travelled));
    }
  }, []);

  const subscribe = motion?.subscribe;
  useEffect(() => {
    if (!subscribe) return;
    return subscribe((atMs) => { lastAt.current = atMs; pose(atMs); });
  }, [pose, subscribe]);
  useLayoutEffect(() => { pose(lastAt.current); });

  if (!set) return <p className="scene-unavailable" role="status">The home for this run is not available.</p>;

  return (
    <div className="scene-stage">
      <svg
        className="scene-canvas"
        viewBox={`${String(set.view.x)} ${String(set.view.y)} ${String(set.view.width)} ${String(set.view.height)}`}
        role="img"
        aria-label={`The flat, seen from above, with ${String(world.residents.length)} resident${world.residents.length === 1 ? "" : "s"}`}
      >
        <defs><FurnitureSymbols /><CustomFurnitureSymbols /></defs>

        <g className="scene-rooms">
          {set.regions.map((region) => (
            <g key={region.regionId} data-region-id={region.regionId} className={region.regionId === activeRegionId ? "is-occupied" : undefined}>
              <polygon className="scene-floor" points={polygonPoints(region.boundary.vertices)} />
            </g>
          ))}
        </g>

        <g className="scene-walls">
          {set.walls.map((wall, index) => (
            <line
              key={`wall-${String(index)}`}
              className={wall.exterior ? "scene-wall is-exterior" : "scene-wall"}
              x1={wall.x1} y1={wall.y1} x2={wall.x2} y2={wall.y2}
            />
          ))}
        </g>

        <g className="scene-doors">
          {set.doors.map((door) => (
            <line key={door.connectionId} className={`scene-door scene-door-${door.kind}`} x1={door.x1} y1={door.y1} x2={door.x2} y2={door.y2} />
          ))}
        </g>

        <g className="scene-furniture">
          {set.furniture.map((item) => {
            const state = item.entityId ? world.entities[item.entityId] : undefined;
            const classes = [
              "scene-thing",
              state?.active ? "is-active" : "",
              state?.open ? "is-open" : "",
              // The thing somebody is standing at, so "watching television" has a referent.
              item.entityId && item.entityId === usingEntityId ? "is-in-use" : "",
            ].filter(Boolean).join(" ");
            return (
              <g key={item.obstacleId} className={classes} aria-hidden="true">
                {item.entityId === usingEntityId && <rect
                  className="scene-thing-use"
                  x={item.box.minX - .1} y={item.box.minY - .1}
                  width={item.box.maxX - item.box.minX + .2}
                  height={item.box.maxY - item.box.minY + .2}
                  rx=".14"
                />}
                {state?.active && <rect
                  className="scene-thing-glow"
                  x={item.box.minX - .12} y={item.box.minY - .12}
                  width={item.box.maxX - item.box.minX + .24}
                  height={item.box.maxY - item.box.minY + .24}
                  rx=".18"
                />}
                {item.symbol
                  ? <FurnitureGlyph
                    symbol={item.symbol}
                    box={item.box}
                    orientationDegrees={item.orientationDegrees}
                  />
                  : <polygon className="scene-block" points={polygonPoints(item.vertices)} />}
              </g>
            );
          })}
        </g>

        <g className="scene-labels">
          {set.regions.map((region) => {
            const box = bounds(region.boundary.vertices);
            return <text
              key={region.regionId}
              className={region.regionId === activeRegionId ? "scene-room-name is-occupied" : "scene-room-name"}
              x={(box.minX + box.maxX) / 2}
              y={box.minY + .42}
            >{words(region.regionId)}</text>;
          })}
        </g>

        <g className="scene-trails">
          {world.residents.map((resident) => (
            <polyline
              key={resident.residentId}
              ref={(node) => { trails.current.set(resident.residentId, node); }}
              className="scene-trail"
              points=""
            />
          ))}
        </g>

        <g className="scene-people">
          {world.residents.map((resident) => resident.position ? (
            <g
              key={resident.residentId}
              ref={(node) => { markers.current.set(resident.residentId, node); }}
              transform={`translate(${String(resident.position.x)} ${String(resident.position.y)})`}
            >
              <Avatar resident={resident} />
              <text className="scene-avatar-name" y="-.36">{resident.name}</text>
            </g>
          ) : null)}
        </g>
      </svg>
    </div>
  );
}
