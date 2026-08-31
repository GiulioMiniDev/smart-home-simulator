import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, type CSSProperties } from "react";
import { cutDoorways, dwellingRegionIds, planDoors, planFrontDoor, planWalls } from "../editor";
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
    // The way out is a transit connection, not a doorway, so it is not among the holes in the
    // walls — and the one door in the flat that opens and shuts was the one the scene never drew.
    const front = planFrontDoor(home, dwelling);
    const doors = [...planDoors(home, dwelling), ...(front ? [front] : [])];
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

/**
 * What a thing does while it is running, for the things whose whole point is that they do it.
 *
 * `active` is one bit in the trace and it used to be one static halo, which said a kettle and a
 * television were the same event. They are not: one of them steams and the other one flickers, and
 * a scene that shows the difference is a scene where "making coffee" is legible without the caption
 * underneath it. Anything not named here still gets the halo — the halo is the general case.
 */
const EMITTERS: Record<string, "steam" | "water" | "screen" | "sound"> = {
  stove: "steam", oven: "steam", kettle: "steam", coffee_machine: "steam", moka_coffee_maker: "steam",
  microwave: "steam",
  shower: "water", sink: "water", bathtub: "water", washing_machine: "water", dishwasher: "water",
  toilet: "water", bidet: "water",
  television: "screen",
  radio: "sound",
};

/** The moving part of a running thing, drawn over its own footprint. */
function Emission({ kind, box }: { kind: "steam" | "water" | "screen" | "sound"; box: ReturnType<typeof bounds> }) {
  const x = (box.minX + box.maxX) / 2;
  const y = (box.minY + box.maxY) / 2;
  if (kind === "screen") {
    return <rect
      className="scene-emit-screen"
      x={box.minX} y={box.minY}
      width={box.maxX - box.minX} height={box.maxY - box.minY}
    />;
  }
  if (kind === "sound") {
    return <g className="scene-emit-sound">
      {[.28, .42, .56].map((radius, index) => (
        <circle key={radius} cx={x} cy={y} r={radius} style={{ animationDelay: `${String(index * .45)}s` }} />
      ))}
    </g>;
  }
  // Steam rises off the top of the thing; water falls through it. Three of each, offset in time,
  // because two read as a pair and four is a fountain.
  return <g className={kind === "steam" ? "scene-emit-steam" : "scene-emit-water"}>
    {[-.13, 0, .13].map((offset, index) => (
      <circle
        key={offset}
        cx={x + offset}
        cy={kind === "steam" ? box.minY : y}
        r={kind === "steam" ? .05 : .028}
        style={{ animationDelay: `${String(index * .38)}s` }}
      />
    ))}
  </g>;
}

/**
 * Furniture you get onto, rather than stand at and operate.
 *
 * A trace puts a resident on the interaction point of the thing they are using, and an interaction
 * point is by construction a patch of *free floor* — it is where a body stands, which is the only
 * place the router can legally put one. For a fridge that is exactly right. For a bed it drew her
 * lying rigidly on the carpet beside it, and for a chair and a sofa it drew her standing next to
 * the furniture she is recorded as sitting on. The trace was never wrong; the picture was.
 */
const OCCUPIED = new Set([
  "bed", "single_bed", "sofa", "armchair", "chair", "stool", "bench", "toilet", "bathtub",
]);

/**
 * How far onto the furniture the body goes, and which way it lies once it is there.
 *
 * Not all the way for sitting: perching towards the near edge reads as sat down, where the middle
 * of a double bed reads as swallowed by it. Lying goes to the centre and turns along the long axis
 * of the piece, taken from its own footprint — `orientationDegrees` means a different thing for a
 * bed than for a hob, and a body is not worth guessing wrong about.
 */
function seatPose(
  furniture: { entityId?: string; box: ReturnType<typeof bounds> }[],
  resident: WorldResident,
): { x: number; y: number; recline?: number } | undefined {
  const seated = resident.posture === "sitting";
  const lying = resident.posture === "lying";
  if ((!seated && !lying) || !resident.position) return undefined;

  // Evidence first. The engine records the berth she is on — which side of the bed, which end of
  // the sofa — and that is an answer this cannot work out: two people asleep in one bed are two
  // places, and geometry alone would put both of them in the middle of it. The guess below is the
  // fallback for traces written before the engine said so, and for nothing else.
  if (resident.restingAt) {
    const pose = {
      x: resident.restingAt.x - resident.position.x,
      y: resident.restingAt.y - resident.position.y,
    };
    if (!lying) return pose;
    const piece = furniture.find((item) => item.entityId === resident.using?.entityId);
    return piece ? { ...pose, recline: reclineOn(piece.box, resident.position) } : pose;
  }
  if (!resident.using) return undefined;
  if (!OCCUPIED.has(resident.using.label.replaceAll(" ", "_"))) return undefined;
  const piece = furniture.find((item) => item.entityId === resident.using?.entityId);
  if (!piece) return undefined;

  const centreX = (piece.box.minX + piece.box.maxX) / 2;
  const centreY = (piece.box.minY + piece.box.maxY) / 2;
  const reach = lying ? 1 : .78;
  const pose = {
    x: (centreX - resident.position.x) * reach,
    y: (centreY - resident.position.y) * reach,
  };
  if (!lying) return pose;

  return { ...pose, recline: reclineOn(piece.box, resident.position) };
}

/**
 * Which way a body lies on a piece: along it, head away from the side she got in from.
 *
 * Taken from the footprint rather than from `orientationDegrees`, which means a different thing
 * for a bed than for a hob. Approached square on the two ends are equally good and it takes the
 * first.
 */
function reclineOn(box: ReturnType<typeof bounds>, from: Point): number {
  const centreX = (box.minX + box.maxX) / 2;
  const centreY = (box.minY + box.maxY) / 2;
  const along = box.maxX - box.minX >= box.maxY - box.minY ? { x: 1, y: 0 } : { x: 0, y: 1 };
  const away = along.x * (centreX - from.x) + along.y * (centreY - from.y);
  return ((Math.atan2(along.y, along.x) + (away < 0 ? Math.PI : 0)) * 180) / Math.PI;
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
      <ellipse className="scene-avatar-shadow" cx="0" cy=".04" rx=".145" ry=".075" />
      {/* Facing turns the body, never the name: a label that rotates with the walk is read
          sideways and then upside down, which is the one thing on screen nobody can follow. */}
      <g className="scene-avatar-facing">
        <g className="scene-avatar-climb">
          <g className="scene-avatar-posture">
            <g className="scene-avatar-body">
              {/* Feet first, so they read as swinging out from under her rather than on top of
                  her. Seen from overhead that alternation is most of what a walk looks like. */}
              <ellipse className="scene-avatar-foot is-left" cx="0" cy="-.105" rx=".038" ry=".028" />
              <ellipse className="scene-avatar-foot is-right" cx="0" cy=".105" rx=".038" ry=".028" />
              {/* Shoulders: from above a body is wider across than it is deep. */}
              <ellipse className="scene-avatar-torso" cx="0" cy="0" rx=".105" ry=".155" />
              <circle className="scene-avatar-head" cx=".028" cy="0" r=".068" />
              {/* Which way she is looking, so a body standing at the sink is not just a blob. */}
              <path className="scene-avatar-face" d="M.062-.026L.128 0 .062.026Z" />
              {carrying && <rect className="scene-avatar-load" x=".02" y="-.235" width=".115" height=".115" rx=".028" />}
            </g>
          </g>
        </g>
      </g>
    </g>
  );
}

/**
 * The seat as custom properties, so React owns getting onto the furniture and the clock owns
 * getting across the floor. They never write the same property, which is what keeps a re-render
 * from stamping on a position the animation frame has just set.
 */
function seatStyle(seat: ReturnType<typeof seatPose>): CSSProperties {
  return {
    "--scene-seat-x": `${String(seat?.x ?? 0)}px`,
    "--scene-seat-y": `${String(seat?.y ?? 0)}px`,
    ...(seat?.recline === undefined ? {} : { "--scene-recline": `${String(seat.recline)}deg` }),
  } as CSSProperties;
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
  // The front door is an entity, the doorway is a connection, and only the entity has a state. The
  // home names the one that is the way out; everything else in the flat is a hole in a wall.
  const frontDoorId = home?.entities.find((entity) => entity.entityType === "entrance_door")?.entityId;
  const frontDoorOpen = frontDoorId ? world.entities[frontDoorId]?.open === true : false;
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
        marker.setAttribute("transform", `translate(${String(item.position.x)} ${String(item.position.y)})`);
        // Facing and the climb ride as custom properties rather than as part of the transform, so
        // the body can turn on its own easing while the position keeps up with the clock exactly,
        // and so the name above her head stays the right way up.
        if (item.heading !== undefined) {
          marker.style.setProperty("--scene-facing", `${String((item.heading * 180) / Math.PI)}deg`);
        }
        marker.style.setProperty("--scene-climbing", String(item.climbing));
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

        <g className="scene-set" key={storey}>
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
            <g key={door.connectionId}>
              <line className={`scene-door scene-door-${door.kind}`} x1={door.x1} y1={door.y1} x2={door.x2} y2={door.y2} />
              {/* The one door in the model that has a state worth drawing. She leaves through it
                  and comes back through it, and a front door that never moves makes both of those
                  the same nothing. It swings on its own hinge, which is the end it is drawn from. */}
              {door.kind === "entrance" && (
                <line
                  className="scene-door-leaf"
                  data-open={frontDoorOpen ? "true" : "false"}
                  x1={door.x1} y1={door.y1} x2={door.x2} y2={door.y2}
                  style={{ transformOrigin: `${String(door.x1)}px ${String(door.y1)}px` }}
                />
              )}
            </g>
          ))}
        </g>

        <g className="scene-furniture">
          {set.furniture.map((item) => {
            const state = item.entityId ? world.entities[item.entityId] : undefined;
            const emission = state?.active && item.entityType ? EMITTERS[item.entityType] : undefined;
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
                {emission && <Emission kind={emission} box={item.box} />}
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
              style={seatStyle(seatPose(set.furniture, resident))}
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
