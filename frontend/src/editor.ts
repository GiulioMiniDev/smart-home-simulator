import { furnitureSize } from "./furniture";
import { declaredEntityTypes } from "./vocabulary/symbol-registry";
import type { HomeConnection, HomeEntity, HomeModel, Point, SensorBase, SensorModel } from "./types";

function centre(vertices: Point[]): Point {
  return {
    x: vertices.reduce((sum, point) => sum + point.x, 0) / vertices.length,
    y: vertices.reduce((sum, point) => sum + point.y, 0) / vertices.length,
  };
}

function nextId(prefix: string, existing: string[]): string {
  let index = 1;
  while (existing.includes(`${prefix}_${String(index).padStart(2, "0")}`)) index += 1;
  return `${prefix}_${String(index).padStart(2, "0")}`;
}

const timing = { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 };
const errorModel = { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 };

/**
 * The sensor a tool installs, before it is moved to where the researcher pointed.
 *
 * Not exported any more: every sensor now arrives through `addSensorAt`, because a sensor dropped
 * in "whichever room happens to be traversable first" is a sensor somebody then has to find and
 * drag, and having two ways in was how it stayed that way.
 */
function addSensor(model: SensorModel, home: HomeModel, type: SensorBase["sensorType"]): { model: SensorModel; selectedId: string } {
  const region = home.regions.find((item) => item.traversable) ?? home.regions[0];
  if (!region) throw new Error("Create a region before adding a sensor");
  const entity = home.entities[0];
  const id = nextId(type, model.sensors.map((item) => item.sensorId));
  const position = centre(region.boundary.vertices);
  const common = { sensorId: id, sensorType: type, position, timing: { ...timing }, errorModel: { ...errorModel }, failureWindows: [] };
  let sensor: SensorBase;
  if (type === "pir") {
    sensor = { ...common, regionIds: [region.regionId], coverage: structuredClone(region.boundary), holdMilliseconds: 30_000 };
  } else if (type === "contact") {
    if (!entity) throw new Error("A contact sensor requires at least one home entity");
    sensor = { ...common, entityId: entity.entityId, fact: "open", actionTypes: [], actionTrigger: "ended", pulseMilliseconds: 1000, openValue: true, closedValue: false };
  } else {
    if (!entity) throw new Error("A temperature sensor requires at least one home entity");
    sensor = { ...common, regionId: region.regionId, baselineCelsius: 20, sources: [{ entityId: entity.entityId, fact: "active", activeValue: true, deltaCelsius: 1, responseDelaySeconds: 0, riseDurationSeconds: 60, decayDurationSeconds: 300, sampleIntervalSeconds: 60 }] };
  }
  return { model: { ...model, sensors: [...model.sensors, sensor] }, selectedId: id };
}

/**
 * Bring the sensor field's register of the home back in line with the home itself.
 *
 * A sensor model carries its own list of the rooms and devices it was deployed against, and the
 * bundle demands the two agree exactly — `HOME_SENSOR_MISMATCH`, raised when a run is built. The
 * editor could draw rooms all afternoon without the register hearing about it, and publishing did
 * not catch it either: the server only looked for rooms the sensor field names and the home does
 * not, never the other way round. So the pair drifted in silence and the run refused it later,
 * with nothing on the plan to say why.
 *
 * Returned unchanged when nothing moved, so a redraw costs nothing.
 */
export function alignSensorModel(sensors: SensorModel, home: HomeModel): SensorModel {
  const regionIds = home.regions.map((item) => item.regionId);
  const entityIds = home.entities.map((item) => item.entityId);
  const same = (left: string[], right: string[]) =>
    left.length === right.length && left.every((item, index) => item === right[index]);
  if (same(sensors.regionIds, regionIds) && same(sensors.entityIds, entityIds)) return sensors;
  return { ...sensors, regionIds, entityIds };
}

/** Everything the plan holds that is one object under different ids. */
interface Removal {
  regions: Set<string>;
  connections: Set<string>;
  obstacles: Set<string>;
  entities: Set<string>;
  points: Set<string>;
}

/**
 * Resolve a selection to the whole object it is part of.
 *
 * Almost nothing you can point at in the plan is one record. A piece of furniture is three — the
 * footprint, the provider and the spot the body stands on — and a staircase is three of another
 * kind: a flight of treads at each end and the connection between them. Deletion used to work on
 * whichever of them the click happened to land on, so removing a wardrobe by its box left its use
 * point standing in the room, removing it by its provider left the box blocking the floor, and
 * neither state was anything the gate would complain about. A house with a ghost in it published
 * perfectly happily.
 *
 * The one thing deliberately left dangling is a binding: `resourceBindings` is what says this home
 * can host that scenario, so deleting the shower has to break it loudly at the gate rather than
 * quietly unbind a scenario the researcher still means to run.
 */
function coupledWith(home: HomeModel, selectedId: string): Removal {
  const removal: Removal = {
    regions: new Set(), connections: new Set(), obstacles: new Set(), entities: new Set(), points: new Set(),
  };
  const takeConnection = (connection: HomeConnection) => {
    removal.connections.add(connection.connectionId);
    // A flight stands on real floor at both ends. Its treads are the only obstacles with no entity
    // to own them, and they are named after the connection precisely so this can find them.
    if (connection.kind !== "stairway") return;
    for (const obstacle of home.obstacles) {
      if (obstacle.obstacleId.startsWith(`obstacle_${connection.connectionId}_`)) removal.obstacles.add(obstacle.obstacleId);
    }
  };
  const takeEntity = (entity: HomeEntity) => {
    removal.entities.add(entity.entityId);
    removal.points.add(entity.interactionPointId);
    removal.obstacles.add(`obstacle_${entity.entityId}`);
  };

  const region = home.regions.find((item) => item.regionId === selectedId);
  if (region) {
    removal.regions.add(region.regionId);
    // A staircase is not in a room, it is between two, so taking one end takes the flight at the
    // other: otherwise the storey left behind keeps a set of treads climbing to nowhere.
    for (const connection of home.connections) {
      if (connection.regionAId === selectedId || connection.regionBId === selectedId) takeConnection(connection);
    }
    return removal;
  }
  const entity = home.entities.find((item) => item.entityId === selectedId);
  if (entity) {
    takeEntity(entity);
    return removal;
  }
  const connection = home.connections.find((item) => item.connectionId === selectedId);
  if (connection) {
    takeConnection(connection);
    return removal;
  }
  const obstacle = home.obstacles.find((item) => item.obstacleId === selectedId);
  if (obstacle) {
    const flight = home.connections.find((item) =>
      item.kind === "stairway" && obstacle.obstacleId.startsWith(`obstacle_${item.connectionId}_`));
    if (flight) takeConnection(flight);
    else {
      removal.obstacles.add(obstacle.obstacleId);
      const owner = home.entities.find((item) => `obstacle_${item.entityId}` === obstacle.obstacleId);
      if (owner) takeEntity(owner);
    }
  }
  return removal;
}

/** Remove what was selected, and everything that was only ever part of it. */
export function removeSelection(home: HomeModel, sensorModel: SensorModel | undefined, selectedId: string): { home: HomeModel; sensors?: SensorModel } {
  const gone = coupledWith(home, selectedId);
  const inGoneRegion = (regionId: string | undefined) => regionId !== undefined && gone.regions.has(regionId);
  // A sensor watches a place or a thing. When that is gone the sensor is not an orphan record but
  // an instrument reporting on a room nobody can enter, and the bundle refuses the pair later.
  const stranded = (sensor: SensorBase): boolean => {
    if (sensor.sensorId === selectedId) return true;
    if (typeof sensor.entityId === "string" && gone.entities.has(sensor.entityId)) return true;
    if (typeof sensor.regionId === "string" && inGoneRegion(sensor.regionId)) return true;
    const watched = sensor.regionIds;
    return Array.isArray(watched) && watched.length > 0 && watched.every((item) => inGoneRegion(String(item)));
  };
  return {
    home: {
      ...home,
      regions: home.regions.filter((item) => !gone.regions.has(item.regionId)),
      connections: home.connections.filter((item) => !gone.connections.has(item.connectionId)),
      obstacles: home.obstacles.filter((item) => !gone.obstacles.has(item.obstacleId) && !inGoneRegion(item.regionId)),
      interactionPoints: home.interactionPoints.filter((item) => !gone.points.has(item.interactionPointId) && !inGoneRegion(item.regionId)),
      entities: home.entities.filter((item) => !gone.entities.has(item.entityId) && !inGoneRegion(item.regionId)),
    },
    sensors: sensorModel ? { ...sensorModel, sensors: sensorModel.sensors.filter((item) => !stranded(item)) } : undefined,
  };
}

/**
 * Direct manipulation on the plan: what a drag or a resize handle does to the model.
 *
 * Every function here is pure geometry over the two published models, so the canvas can stay a
 * renderer and the same operation can be driven by a pointer, a keyboard nudge or a test. Metres
 * are the only unit: the canvas hands over plan coordinates, never pixels.
 */

/** Anything the plan lets you grab. Regions and obstacles are areas; the rest are points. */
export type PlanObjectKind = "region" | "obstacle" | "entity" | "sensor" | "coverage";

export interface PlanBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export type ResizeHandle = "nw" | "ne" | "se" | "sw" | "n" | "e" | "s" | "w";

/** The smallest room, footprint or coverage a drag is allowed to leave behind. */
const MINIMUM_EXTENT = 0.3;

export function boxOf(vertices: Point[]): PlanBox {
  return {
    minX: Math.min(...vertices.map((point) => point.x)),
    minY: Math.min(...vertices.map((point) => point.y)),
    maxX: Math.max(...vertices.map((point) => point.x)),
    maxY: Math.max(...vertices.map((point) => point.y)),
  };
}

function rectangle(box: PlanBox): Point[] {
  return [
    { x: box.minX, y: box.minY },
    { x: box.maxX, y: box.minY },
    { x: box.maxX, y: box.maxY },
    { x: box.minX, y: box.maxY },
  ];
}

/** Round to the centimetre so dragging cannot smuggle floating-point noise into a published model. */
export function snap(value: number, grid = 0.1): number {
  if (grid <= 0) return Math.round(value * 1000) / 1000;
  return Math.round(Math.round(value / grid) * grid * 1000) / 1000;
}

function translate(vertices: Point[], dx: number, dy: number): Point[] {
  return vertices.map((point) => ({ x: snap(point.x + dx), y: snap(point.y + dy) }));
}

/**
 * The box a resize handle produces, kept the right way round and never smaller than a threshold.
 *
 * Dragging the west edge past the east one is a slip, not an intent to mirror the room, so the
 * moved edge stops rather than crossing over.
 */
export function resizeBox(box: PlanBox, handle: ResizeHandle, dx: number, dy: number): PlanBox {
  const next = { ...box };
  if (handle.includes("w")) next.minX = Math.min(snap(box.minX + dx), box.maxX - MINIMUM_EXTENT);
  if (handle.includes("e")) next.maxX = Math.max(snap(box.maxX + dx), box.minX + MINIMUM_EXTENT);
  if (handle.includes("n")) next.minY = Math.min(snap(box.minY + dy), box.maxY - MINIMUM_EXTENT);
  if (handle.includes("s")) next.maxY = Math.max(snap(box.maxY + dy), box.minY + MINIMUM_EXTENT);
  return next;
}

/**
 * Move one object on the plan by (dx, dy) metres.
 *
 * Furniture is three coupled things — the entity, its footprint and the interaction point the
 * resident walks to — and moving one without the others produces a home whose validator says the
 * wardrobe is unreachable. So dragging a provider moves the whole trio, and dragging a PIR carries
 * its coverage along instead of leaving it watching the old corner.
 */
export function movePlanObject(
  home: HomeModel,
  sensors: SensorModel | undefined,
  selectedId: string,
  dx: number,
  dy: number,
): { home: HomeModel; sensors?: SensorModel } {
  const sensor = sensors?.sensors.find((item) => item.sensorId === selectedId);
  if (sensor && sensors) {
    return { home, sensors: { ...sensors, sensors: sensors.sensors.map((item) => item.sensorId === selectedId ? moveSensor(item, dx, dy) : item) } };
  }
  const region = home.regions.find((item) => item.regionId === selectedId);
  if (region) {
    // A room takes its contents with it: everything inside keeps the arrangement it had.
    const inside = (id: string) => id === region.regionId;
    return {
      home: {
        ...home,
        regions: home.regions.map((item) => item.regionId === selectedId
          ? { ...item, boundary: { vertices: translate(item.boundary.vertices, dx, dy) } }
          : item),
        obstacles: home.obstacles.map((item) => inside(item.regionId)
          ? { ...item, boundary: { vertices: translate(item.boundary.vertices, dx, dy) } }
          : item),
        interactionPoints: home.interactionPoints.map((item) => inside(item.regionId)
          ? { ...item, position: { x: snap(item.position.x + dx), y: snap(item.position.y + dy) } }
          : item),
        connections: home.connections.map((item) => ({
          ...item,
          portalA: item.regionAId === selectedId && item.portalA
            ? { x: snap(item.portalA.x + dx), y: snap(item.portalA.y + dy) }
            : item.portalA,
          portalB: item.regionBId === selectedId && item.portalB
            ? { x: snap(item.portalB.x + dx), y: snap(item.portalB.y + dy) }
            : item.portalB,
        })),
      },
      sensors,
    };
  }
  const obstacle = home.obstacles.find((item) => item.obstacleId === selectedId);
  const entity = home.entities.find((item) => item.entityId === selectedId)
    ?? (obstacle ? home.entities.find((item) => `obstacle_${item.entityId}` === obstacle.obstacleId) : undefined);
  const obstacleId = obstacle?.obstacleId ?? (entity ? `obstacle_${entity.entityId}` : undefined);
  if (!obstacleId && !entity) return { home, sensors };
  return {
    home: {
      ...home,
      obstacles: home.obstacles.map((item) => item.obstacleId === obstacleId
        ? { ...item, boundary: { vertices: translate(item.boundary.vertices, dx, dy) } }
        : item),
      interactionPoints: home.interactionPoints.map((item) => item.interactionPointId === entity?.interactionPointId
        ? { ...item, position: { x: snap(item.position.x + dx), y: snap(item.position.y + dy) } }
        : item),
    },
    sensors,
  };
}

function moveSensor(sensor: SensorBase, dx: number, dy: number): SensorBase {
  const coverage = sensor.coverage as { vertices: Point[] } | undefined;
  return {
    ...sensor,
    position: { x: snap(sensor.position.x + dx), y: snap(sensor.position.y + dy) },
    coverage: coverage ? { vertices: translate(coverage.vertices, dx, dy) } : sensor.coverage,
  };
}

/**
 * Resize one object by dragging a handle.
 *
 * A PIR's coverage is resized through the same path as a room, because to the researcher it is the
 * same gesture — drag the edge of the area until it covers what it should. The sensor itself then
 * moves to the centre of what it watches, which is the only position the projection accepts for a
 * coverage that no longer surrounds where the node used to sit.
 */
export function resizePlanObject(
  home: HomeModel,
  sensors: SensorModel | undefined,
  selectedId: string,
  handle: ResizeHandle,
  dx: number,
  dy: number,
): { home: HomeModel; sensors?: SensorModel } {
  const sensor = sensors?.sensors.find((item) => item.sensorId === selectedId);
  if (sensor && sensors) {
    const coverage = sensor.coverage as { vertices: Point[] } | undefined;
    if (!coverage) return { home, sensors };
    const box = clampToRegions(resizeBox(boxOf(coverage.vertices), handle, dx, dy), home, sensor);
    return {
      home,
      sensors: {
        ...sensors,
        sensors: sensors.sensors.map((item) => item.sensorId === selectedId
          ? { ...item, coverage: { vertices: rectangle(box) }, position: centreOf(box) }
          : item),
      },
    };
  }
  const region = home.regions.find((item) => item.regionId === selectedId);
  if (region) {
    const box = resizeBox(boxOf(region.boundary.vertices), handle, dx, dy);
    return {
      home: {
        ...home,
        regions: home.regions.map((item) => item.regionId === selectedId
          ? { ...item, boundary: { vertices: rectangle(box) } }
          : item),
      },
      sensors,
    };
  }
  const obstacle = home.obstacles.find((item) => item.obstacleId === selectedId);
  if (!obstacle) return { home, sensors };
  const box = resizeBox(boxOf(obstacle.boundary.vertices), handle, dx, dy);
  return {
    home: {
      ...home,
      obstacles: home.obstacles.map((item) => item.obstacleId === selectedId
        ? { ...item, boundary: { vertices: rectangle(box) } }
        : item),
    },
    sensors,
  };
}

function centreOf(box: PlanBox): Point {
  return { x: snap((box.minX + box.maxX) / 2), y: snap((box.minY + box.maxY) / 2) };
}

/**
 * Hold a coverage inside the rooms its sensor declares.
 *
 * The projection refuses a PIR whose coverage spills outside the regions it monitors — a sensor
 * cannot see through a wall — so widening the range stops at the room instead of producing a model
 * that only fails on publication.
 */
function clampToRegions(box: PlanBox, home: HomeModel, sensor: SensorBase): PlanBox {
  const regionIds = (sensor.regionIds as string[] | undefined) ?? [];
  const boxes = home.regions
    .filter((item) => regionIds.includes(item.regionId))
    .map((item) => boxOf(item.boundary.vertices));
  if (boxes.length === 0) return box;
  const limit = {
    minX: Math.min(...boxes.map((item) => item.minX)),
    minY: Math.min(...boxes.map((item) => item.minY)),
    maxX: Math.max(...boxes.map((item) => item.maxX)),
    maxY: Math.max(...boxes.map((item) => item.maxY)),
  };
  return {
    minX: Math.max(box.minX, limit.minX),
    minY: Math.max(box.minY, limit.minY),
    maxX: Math.min(box.maxX, limit.maxX),
    maxY: Math.min(box.maxY, limit.maxY),
  };
}

/**
 * Set how far a PIR sees, as the half-width in metres of the square it covers.
 *
 * The contract models coverage as a polygon rather than a radius, which is more expressive than
 * anything a slider can express; this is the one control that speaks the researcher's language —
 * "this node watches about two metres around itself" — and leaves the polygon free to be edited by
 * hand for the cases that need it.
 */
export function setPirRange(
  model: SensorModel,
  home: HomeModel,
  sensorId: string,
  rangeMeters: number,
): SensorModel {
  const range = Math.max(MINIMUM_EXTENT / 2, rangeMeters);
  return {
    ...model,
    sensors: model.sensors.map((sensor) => {
      if (sensor.sensorId !== sensorId || sensor.sensorType !== "pir") return sensor;
      const box = clampToRegions({
        minX: snap(sensor.position.x - range),
        minY: snap(sensor.position.y - range),
        maxX: snap(sensor.position.x + range),
        maxY: snap(sensor.position.y + range),
      }, home, sensor);
      return { ...sensor, coverage: { vertices: rectangle(box) }, position: centreOf(box) };
    }),
  };
}

/** The range control's current value: half the shorter side of the covered area. */
export function pirRange(sensor: SensorBase): number {
  const coverage = sensor.coverage as { vertices: Point[] } | undefined;
  if (!coverage) return 0;
  const box = boxOf(coverage.vertices);
  return snap(Math.min(box.maxX - box.minX, box.maxY - box.minY) / 2);
}

/**
 * The regions that are the dwelling, as opposed to the places the resident travels to.
 *
 * A home model carries more than a house. ADR-015 materializes every declared location, so the
 * supermarket, the bar and the relative's flat become regions too — parked far away and reached by
 * `transit` connections, because the simulator needs somewhere to put the resident when they are
 * out. On a drawing they are not architecture: they push the viewport out to tens of metres and
 * squeeze the actual flat into a corner of the canvas.
 *
 * Membership is decided by how you get there, not by what the region is called: a region belongs to
 * the dwelling if it is a room you can be in, or if a door or passage — never a transit link —
 * joins it to one. A balcony is part of the home; the pharmacy you walk to is not.
 *
 * `transit` regions are deliberately not seeds. The generator materializes only `room` locations
 * into the floorplan, so a landing declared as transit — `home_entrance` in the generated flats —
 * is parked with the far-away places and would drag the viewport thirty metres out, plus a dashed
 * link across the drawing, for a threshold nobody wants to see on a planimetry. One joined to the
 * flat by an actual door still comes in through the growth below.
 */
export function dwellingRegionIds(home: HomeModel): Set<string> {
  const inside = new Set(
    home.regions.filter((item) => item.kind === "room").map((item) => item.regionId),
  );
  const walkable = home.connections.filter((item) => item.kind !== "transit");
  // Doors chain: a balcony reached through a hallway is as much part of the flat as the hallway.
  for (let pass = 0; pass < walkable.length; pass += 1) {
    let grew = false;
    for (const connection of walkable) {
      if (inside.has(connection.regionAId) && !inside.has(connection.regionBId)) {
        inside.add(connection.regionBId);
        grew = true;
      } else if (inside.has(connection.regionBId) && !inside.has(connection.regionAId)) {
        inside.add(connection.regionAId);
        grew = true;
      }
    }
    if (!grew) break;
  }
  return inside;
}

/**
 * The drawing primitives of a floorplan: walls with a thickness, and doors that are holes in them.
 *
 * The model has none of this. It has regions that happen to touch and connections that declare two
 * points either side of a wall, which is everything the simulator needs and nothing a reader needs:
 * drawn literally it gives an outline per room and a dotted line floating over the label. These
 * functions derive what an architect would draw — an envelope, partitions inside it, and openings
 * with a swing — from exactly the same data.
 */

export interface WallPiece {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** A wall with nothing on the other side: the envelope of the dwelling. */
  exterior: boolean;
}

export interface DoorGlyph {
  connectionId: string;
  kind: string;
  /** The opening itself, along the wall. */
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** The leaf, hinged at (x1, y1) and swung into one of the two rooms. */
  leafX: number;
  leafY: number;
  /** Quarter-circle arc from the leaf tip back to the far jamb. */
  arc: string;
}

function pointInPolygon(x: number, y: number, vertices: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i, i += 1) {
    const a = vertices[i];
    const b = vertices[j];
    if (!a || !b) continue;
    if ((a.y > y) !== (b.y > y) && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

export function polygonArea(vertices: Point[]): number {
  let sum = 0;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i, i += 1) {
    const a = vertices[i];
    const b = vertices[j];
    if (!a || !b) continue;
    sum += (b.x + a.x) * (b.y - a.y);
  }
  return Math.abs(sum) / 2;
}

/** How far off a wall to look when asking what is on the other side of it. */
const PROBE_METERS = 0.06;

/**
 * Which visible region, if any, lies on the far side of this edge.
 *
 * Both sides are probed and the one still inside the room itself is discarded, so the answer does
 * not depend on which way round the polygon happens to be wound.
 */
function regionBehind(
  regions: HomeModel["regions"],
  self: HomeModel["regions"][number],
  a: Point,
  b: Point,
): string | undefined {
  const length = Math.hypot(b.x - a.x, b.y - a.y);
  if (length < 1e-9) return undefined;
  const nx = (-(b.y - a.y) / length) * PROBE_METERS;
  const ny = ((b.x - a.x) / length) * PROBE_METERS;
  const midX = (a.x + b.x) / 2;
  const midY = (a.y + b.y) / 2;
  const inward = pointInPolygon(midX + nx, midY + ny, self.boundary.vertices);
  const x = inward ? midX - nx : midX + nx;
  const y = inward ? midY - ny : midY + ny;
  return regions.find(
    (other) => other.regionId !== self.regionId && pointInPolygon(x, y, other.boundary.vertices),
  )?.regionId;
}

/**
 * Every wall of the plan, told apart by what stands on the other side.
 *
 * An edge with a room behind it is a partition; one with nothing behind it is the outside of the
 * building. Drawing those two the same way is what makes a plan read as a pile of boxes rather
 * than a flat, so the distinction is made here rather than left to the stylesheet.
 */
export function planWalls(home: HomeModel, visibleRegionIds: Set<string>): WallPiece[] {
  const shown = home.regions.filter((region) => visibleRegionIds.has(region.regionId));
  const pieces: WallPiece[] = [];
  for (const region of shown) {
    const vertices = region.boundary.vertices;
    for (let index = 0; index < vertices.length; index += 1) {
      const a = vertices[index];
      const b = vertices[(index + 1) % vertices.length];
      // A repeated vertex is a zero-length edge, which is not a wall anyone can draw.
      if (!a || !b || Math.hypot(b.x - a.x, b.y - a.y) < 1e-9) continue;
      const behind = regionBehind(shown, region, a, b);
      // A partition is walked twice, once from each of the rooms it separates; keep one pass.
      if (behind !== undefined && behind < region.regionId) continue;
      pieces.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, exterior: behind === undefined });
    }
  }
  return pieces;
}

/**
 * The doors and passages, as an opening in the wall plus a leaf and its swing.
 *
 * A connection declares one point in each room, straddling the wall it crosses: their midpoint is
 * where the opening sits and the line between them is its normal, so the opening runs across that,
 * as wide as the connection declares. The leaf is hinged at one jamb and swings into the second
 * room — the convention every plan uses to say which way a door opens.
 */
export function planDoors(home: HomeModel, visibleRegionIds: Set<string>): DoorGlyph[] {
  const doors: DoorGlyph[] = [];
  for (const connection of home.connections) {
    if (connection.kind === "transit") continue;
    if (!visibleRegionIds.has(connection.regionAId)) continue;
    if (!visibleRegionIds.has(connection.regionBId)) continue;
    const a = connection.portalA;
    const b = connection.portalB;
    if (!a || !b) continue;
    const span = Math.hypot(b.x - a.x, b.y - a.y);
    if (span < 1e-9) continue;
    // Across the wall — so the wall itself runs at ninety degrees to it.
    const nx = (b.x - a.x) / span;
    const ny = (b.y - a.y) / span;
    const half = connection.widthMeters / 2;
    const cx = (a.x + b.x) / 2;
    const cy = (a.y + b.y) / 2;
    const x1 = cx + ny * half;
    const y1 = cy - nx * half;
    const x2 = cx - ny * half;
    const y2 = cy + nx * half;
    const leafX = x1 + nx * connection.widthMeters;
    const leafY = y1 + ny * connection.widthMeters;
    doors.push({
      connectionId: connection.connectionId,
      kind: connection.kind,
      x1,
      y1,
      x2,
      y2,
      leafX,
      leafY,
      arc: `M ${leafX} ${leafY} A ${connection.widthMeters} ${connection.widthMeters} 0 0 1 ${x2} ${y2}`,
    });
  }
  return doors;
}

/**
 * The walls, minus the openings cut into them.
 *
 * Painting a door as a background-coloured line over the wall works until the wall sits over a
 * fill, a grid or another door, so the hole is taken out of the geometry instead.
 */
export function cutDoorways(walls: WallPiece[], doors: DoorGlyph[]): WallPiece[] {
  const pieces: WallPiece[] = [];
  for (const wall of walls) {
    const length = Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1);
    if (length < 1e-9) continue;
    const dx = (wall.x2 - wall.x1) / length;
    const dy = (wall.y2 - wall.y1) / length;
    const along = (x: number, y: number) => (x - wall.x1) * dx + (y - wall.y1) * dy;
    const across = (x: number, y: number) => Math.abs((x - wall.x1) * -dy + (y - wall.y1) * dx);
    const cuts: Array<[number, number]> = [];
    for (const door of doors) {
      // Only openings lying on this very wall cut it, not ones that merely cross its line.
      if (across(door.x1, door.y1) > 0.06 || across(door.x2, door.y2) > 0.06) continue;
      const from = Math.max(0, Math.min(along(door.x1, door.y1), along(door.x2, door.y2)));
      const to = Math.min(length, Math.max(along(door.x1, door.y1), along(door.x2, door.y2)));
      if (to > from) cuts.push([from, to]);
    }
    cuts.sort((left, right) => left[0] - right[0]);
    let cursor = 0;
    for (const [from, to] of cuts) {
      if (from > cursor) {
        pieces.push({
          ...wall,
          x1: wall.x1 + dx * cursor,
          y1: wall.y1 + dy * cursor,
          x2: wall.x1 + dx * from,
          y2: wall.y1 + dy * from,
        });
      }
      cursor = Math.max(cursor, to);
    }
    if (cursor < length - 1e-9) {
      pieces.push({
        ...wall,
        x1: wall.x1 + dx * cursor,
        y1: wall.y1 + dy * cursor,
        x2: wall.x2,
        y2: wall.y2,
      });
    }
  }
  return pieces;
}

/**
 * The front door: where the resident actually leaves the flat.
 *
 * The model never draws one. Going out is a `transit` connection from a room to a place kept
 * kilometres away, and the door itself is an *entity* — the thing the `enter_home` and `leave_home`
 * actions bind to, and the thing the entrance contact sensor watches. So on a planimetry the one
 * opening a reader looks for first is the only one missing.
 *
 * It is found by what it can do rather than by what it is called: the entity whose capabilities
 * carry `leave_home` or `enter_home`. Its interaction point is where the resident stands to use it,
 * so the opening is drawn on the exterior wall of its room nearest that point, swinging out.
 */
export function planFrontDoor(
  home: HomeModel,
  visibleRegionIds: Set<string>,
): DoorGlyph | undefined {
  // Tolerant of an entity with no capabilities at all: the scene draws whatever home it is handed,
  // and a model that is missing them is one to render plainly rather than one to crash on.
  const entrance = home.entities.find((entity) =>
    (entity.capabilities ?? []).some((capability) =>
      (capability.supportedOperations ?? []).some((item) => item === "leave_home" || item === "enter_home"),
    ),
  );
  if (!entrance || !visibleRegionIds.has(entrance.regionId)) return undefined;
  const point = home.interactionPoints.find(
    (item) => item.interactionPointId === entrance.interactionPointId,
  );
  const region = home.regions.find((item) => item.regionId === entrance.regionId);
  if (!point || !region) return undefined;

  let best: { x: number; y: number; nx: number; ny: number; distance: number } | undefined;
  for (const wall of planWalls(home, visibleRegionIds)) {
    if (!wall.exterior) continue;
    if (!pointInPolygon((wall.x1 + wall.x2) / 2 - 1e-6, (wall.y1 + wall.y2) / 2, region.boundary.vertices)
      && !onEdgeOf(wall, region.boundary.vertices)) continue;
    const length = Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1);
    if (length < 1e-9) continue;
    const dx = (wall.x2 - wall.x1) / length;
    const dy = (wall.y2 - wall.y1) / length;
    const along = Math.max(
      0.5,
      Math.min(length - 0.5, (point.position.x - wall.x1) * dx + (point.position.y - wall.y1) * dy),
    );
    const x = wall.x1 + dx * along;
    const y = wall.y1 + dy * along;
    const distance = Math.hypot(point.position.x - x, point.position.y - y);
    if (best && distance >= best.distance) continue;
    // Outward: away from the room the door belongs to.
    const inward = pointInPolygon(x - dy * 0.05, y + dx * 0.05, region.boundary.vertices);
    best = { x, y, nx: inward ? dy : -dy, ny: inward ? -dx : dx, distance };
  }
  if (!best) return undefined;

  const width = 0.9;
  const half = width / 2;
  const tx = -best.ny;
  const ty = best.nx;
  const x1 = best.x - tx * half;
  const y1 = best.y - ty * half;
  const x2 = best.x + tx * half;
  const y2 = best.y + ty * half;
  return {
    connectionId: `front_door_${entrance.entityId}`,
    kind: "entrance",
    x1,
    y1,
    x2,
    y2,
    leafX: x1 + best.nx * width,
    leafY: y1 + best.ny * width,
    arc: `M ${x1 + best.nx * width} ${y1 + best.ny * width} A ${width} ${width} 0 0 1 ${x2} ${y2}`,
  };
}

/** Whether a wall piece lies along one of this polygon's own edges. */
function onEdgeOf(wall: WallPiece, vertices: Point[]): boolean {
  const midX = (wall.x1 + wall.x2) / 2;
  const midY = (wall.y1 + wall.y2) / 2;
  for (let index = 0; index < vertices.length; index += 1) {
    const a = vertices[index];
    const b = vertices[(index + 1) % vertices.length];
    if (!a || !b) continue;
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (length < 1e-9) continue;
    const dx = (b.x - a.x) / length;
    const dy = (b.y - a.y) / length;
    const along = (midX - a.x) * dx + (midY - a.y) * dy;
    const across = Math.abs((midX - a.x) * -dy + (midY - a.y) * dx);
    if (across < 1e-6 && along > -1e-6 && along < length + 1e-6) return true;
  }
  return false;
}

/**
 * Turn the selected piece of furniture a quarter of the way round.
 *
 * Moving and resizing were the only two verbs the plan had, which meant the one edit a furnished
 * room actually needs — "that wardrobe is facing the wall, turn it" — could only be done by
 * resizing the box into the other proportion and leaving the drawing facing the way it was. A
 * footprint, its bearing and the spot the resident stands on are one object turned together.
 *
 * Rooms and sensors are not rotated: a room is a rectangle whose corners are dragged, and a PIR is
 * shaped by its coverage.
 */
export function rotatePlanObject(
  home: HomeModel,
  selectedId: string,
  quarterTurns = 1,
): HomeModel {
  const entity = home.entities.find((item) => item.entityId === selectedId);
  const obstacleId = entity ? `obstacle_${entity.entityId}` : selectedId;
  const obstacle = home.obstacles.find((item) => item.obstacleId === obstacleId);
  if (!obstacle) return home;

  const turns = ((quarterTurns % 4) + 4) % 4;
  if (turns === 0) return home;
  const box = boxOf(obstacle.boundary.vertices);
  const pivot = { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 };
  const width = box.maxX - box.minX;
  const height = box.maxY - box.minY;
  // An odd number of quarter turns transposes the footprint; an even one puts it back.
  const [nextWidth, nextHeight] = turns % 2 === 1 ? [height, width] : [width, height];
  // Turning about the centre pushes a piece that was flush against a wall through it — half the
  // difference between its two dimensions, which for a wardrobe is thirty centimetres of masonry.
  // Sliding it back is what the person doing it would then do by hand, so it is done for them.
  const room = home.regions.find((item) => item.regionId === obstacle.regionId);
  const shift = room
    ? containWithin(
        { minX: pivot.x - nextWidth / 2, minY: pivot.y - nextHeight / 2,
          maxX: pivot.x + nextWidth / 2, maxY: pivot.y + nextHeight / 2 },
        boxOf(room.boundary.vertices),
      )
    : { dx: 0, dy: 0 };
  const turned = rectangle({
    minX: snap(pivot.x - nextWidth / 2 + shift.dx),
    minY: snap(pivot.y - nextHeight / 2 + shift.dy),
    maxX: snap(pivot.x + nextWidth / 2 + shift.dx),
    maxY: snap(pivot.y + nextHeight / 2 + shift.dy),
  });
  // The canvas plots the model's axes straight, so a quarter turn of the drawing is a quarter turn
  // clockwise on the page, and the standing point has to travel round with it or the resident is
  // left facing the back of the thing.
  const owner = entity ?? home.entities.find((item) => `obstacle_${item.entityId}` === obstacleId);

  return {
    ...home,
    obstacles: home.obstacles.map((item) =>
      item.obstacleId === obstacleId
        ? {
            ...item,
            boundary: { vertices: turned },
            // Absent means "drawn unturned", which is the authoring convention's own 90 degrees.
            orientationDegrees: (((item.orientationDegrees ?? 90) + turns * 90) % 360 + 360) % 360,
          }
        : item,
    ),
    interactionPoints: home.interactionPoints.map((item) => {
      if (item.interactionPointId !== owner?.interactionPointId) return item;
      const turnedPoint = rotateAbout(item.position, pivot, turns);
      return { ...item, position: { x: snap(turnedPoint.x + shift.dx), y: snap(turnedPoint.y + shift.dy) } };
    }),
  };
}

/** How far a box has to move to sit inside another one, or zero if it already does or cannot. */
function containWithin(box: PlanBox, outer: PlanBox): { dx: number; dy: number } {
  const fits = (low: number, high: number, floor: number, ceiling: number) => {
    if (high - low > ceiling - floor) return 0;
    if (low < floor) return floor - low;
    if (high > ceiling) return ceiling - high;
    return 0;
  };
  return {
    dx: fits(box.minX, box.maxX, outer.minX, outer.maxX),
    dy: fits(box.minY, box.maxY, outer.minY, outer.maxY),
  };
}

function rotateAbout(point: Point, pivot: Point, quarterTurns: number): Point {
  let current = { x: point.x, y: point.y };
  for (let turn = 0; turn < quarterTurns; turn += 1) {
    current = {
      x: pivot.x - (current.y - pivot.y),
      y: pivot.y + (current.x - pivot.x),
    };
  }
  return { x: snap(current.x), y: snap(current.y) };
}

/** How close an edge has to come to a wall or a neighbour before the drag lines it up. */
const MAGNET_METRES = 0.12;

/**
 * Nudge a drag so the thing being dragged lands *against* something rather than near it.
 *
 * Without it, arranging a room is an exercise in pixel-hunting: a wardrobe placed by hand sits four
 * centimetres off the wall and two centimetres out of line with the chest of drawers beside it, and
 * the plan reads as a plan somebody fought with. The candidates are the walls of the room the
 * object is in and the edges of everything else in that room, which are the lines a person is
 * actually trying to hit.
 */
export interface Magnet {
  dx: number;
  dy: number;
  /** The lines the drag landed on, in plan metres, for the canvas to draw while it is held. */
  guideX?: number;
  guideY?: number;
}

export function magnet(home: HomeModel, selectedId: string, dx: number, dy: number): Magnet {
  const entity = home.entities.find((item) => item.entityId === selectedId);
  const obstacleId = entity ? `obstacle_${entity.entityId}` : selectedId;
  const obstacle = home.obstacles.find((item) => item.obstacleId === obstacleId);
  if (!obstacle) return { dx, dy };
  const region = home.regions.find((item) => item.regionId === obstacle.regionId);
  if (!region) return { dx, dy };

  const room = boxOf(region.boundary.vertices);
  const moved = boxOf(obstacle.boundary.vertices);
  const guidesX = [room.minX, room.maxX];
  const guidesY = [room.minY, room.maxY];
  for (const other of home.obstacles) {
    if (other.obstacleId === obstacleId || other.regionId !== obstacle.regionId) continue;
    const box = boxOf(other.boundary.vertices);
    guidesX.push(box.minX, box.maxX);
    guidesY.push(box.minY, box.maxY);
  }

  const across = pull(moved.minX, moved.maxX, dx, guidesX);
  const down = pull(moved.minY, moved.maxY, dy, guidesY);
  return { dx: across.delta, dy: down.delta, guideX: across.guide, guideY: down.guide };
}

/** The delta, corrected so the nearest edge lands on the nearest guide, and the guide it hit. */
function pull(
  low: number,
  high: number,
  delta: number,
  guides: number[],
): { delta: number; guide?: number } {
  let best: number | undefined;
  let hit: number | undefined;
  for (const guide of guides) {
    for (const edge of [low + delta, high + delta]) {
      const correction = guide - edge;
      if (Math.abs(correction) > MAGNET_METRES) continue;
      if (best !== undefined && Math.abs(correction) >= Math.abs(best)) continue;
      best = correction;
      hit = guide;
    }
  }
  return best === undefined ? { delta } : { delta: snap(delta + best, 0.01), guide: hit };
}

export interface PlanProblem {
  objectId: string;
  message: string;
}

/**
 * What is wrong with the plan as it stands, said now instead of at publication.
 *
 * The authoritative answer is the M4 gate on the server, and it stays that way: this is the same
 * few questions asked cheaply, in the browser, while the researcher is still holding the object.
 * Learning that a wardrobe overlaps the bed after pressing publish — and having the whole edit
 * rejected for it — is the difference between a tool and a form.
 */
export function planProblems(home: HomeModel): PlanProblem[] {
  const problems: PlanProblem[] = [];
  const regions = new Map(home.regions.map((item) => [item.regionId, boxOf(item.boundary.vertices)]));
  const boxes = home.obstacles.map((item) => ({ item, box: boxOf(item.boundary.vertices) }));

  for (const { item, box } of boxes) {
    const room = regions.get(item.regionId);
    if (!room) {
      problems.push({ objectId: item.obstacleId, message: `is in no region called ${item.regionId}` });
      continue;
    }
    if (box.minX < room.minX - 1e-6 || box.minY < room.minY - 1e-6
      || box.maxX > room.maxX + 1e-6 || box.maxY > room.maxY + 1e-6) {
      problems.push({ objectId: item.obstacleId, message: `sticks out of ${words(item.regionId)}` });
    }
  }
  for (let index = 0; index < boxes.length; index += 1) {
    for (let other = index + 1; other < boxes.length; other += 1) {
      const left = boxes[index]!;
      const right = boxes[other]!;
      if (left.item.regionId !== right.item.regionId) continue;
      if (!overlaps(left.box, right.box)) continue;
      problems.push({ objectId: left.item.obstacleId, message: `overlaps ${label(right.item.obstacleId)}` });
      problems.push({ objectId: right.item.obstacleId, message: `overlaps ${label(left.item.obstacleId)}` });
    }
  }
  // A doorway somebody has parked the sofa across is a room the resident cannot leave, and the
  // router refuses the whole home for it rather than routing round.
  for (const connection of home.connections) {
    for (const [portal, regionId] of [
      [connection.portalA, connection.regionAId],
      [connection.portalB, connection.regionBId],
    ] as const) {
      if (!portal) continue;
      for (const { item, box } of boxes) {
        if (item.regionId !== regionId) continue;
        if (portal.x < box.minX || portal.x > box.maxX || portal.y < box.minY || portal.y > box.maxY) continue;
        problems.push({ objectId: item.obstacleId, message: "stands in a doorway" });
      }
    }
  }
  // Every standing point, not only the ones furniture owns. A room's own anchor and the per-region
  // service point are the two nobody thinks about, and dropping a bath in the middle of the sitting
  // room lands on both — which the gate refuses and, until this, refused only at publication.
  const owner = new Map(home.entities.map((item) => [item.interactionPointId, `obstacle_${item.entityId}`]));
  for (const point of home.interactionPoints) {
    const own = owner.get(point.interactionPointId);
    // Near enough is blocked, not just on top of: the gate grows each obstacle by the point's own
    // approach radius before asking. Testing bare containment here said a plan was fine and the
    // publish then refused it, which is the worst of both.
    const reach = point.approachRadiusMeters || 0.25;
    const blocking = boxes.find(({ item, box }) =>
      item.obstacleId !== own
      && item.regionId === point.regionId
      && point.position.x >= box.minX - reach && point.position.x <= box.maxX + reach
      && point.position.y >= box.minY - reach && point.position.y <= box.maxY + reach);
    if (blocking) {
      problems.push({
        objectId: blocking.item.obstacleId,
        message: own
          ? `is too close to the spot somebody stands on to use ${label(own)}`
          : `is too close to ${words(point.interactionPointId)}, which somebody has to stand on`,
      });
      continue;
    }
    // And a body needs the same room around it: a point within its own reach of a wall is a point
    // nobody fits on.
    const room = regions.get(point.regionId);
    if (!own || !room) continue;
    if (point.position.x < room.minX + reach || point.position.x > room.maxX - reach
      || point.position.y < room.minY + reach || point.position.y > room.maxY - reach) {
      problems.push({ objectId: own, message: "is used from a spot too close to the wall to stand on" });
    }
  }
  // A room nothing opens onto is a home the router refuses whole, and drawing rooms is now
  // something the editor lets you do — so it is also something you can now forget to join up.
  const joined = new Set<string>();
  for (const connection of home.connections) {
    joined.add(connection.regionAId);
    joined.add(connection.regionBId);
  }
  for (const region of home.regions) {
    if (home.regions.length > 1 && !joined.has(region.regionId)) {
      problems.push({ objectId: region.regionId, message: "has no way in or out" });
    }
  }
  // One line per object, so a piece with three faults does not fill the panel with three rows.
  const seen = new Set<string>();
  return problems.filter((item) => {
    if (seen.has(item.objectId)) return false;
    seen.add(item.objectId);
    return true;
  });
}

function overlaps(left: PlanBox, right: PlanBox): boolean {
  return left.minX < right.maxX - 1e-6 && right.minX < left.maxX - 1e-6
    && left.minY < right.maxY - 1e-6 && right.minY < left.maxY - 1e-6;
}

function label(obstacleId: string): string {
  return words(obstacleId.replace(/^obstacle_/, ""));
}

function words(value: string): string {
  return value.replaceAll("_", " ");
}

/** Which region on this storey covers the point, innermost first. */
export function regionAt(home: HomeModel, point: Point, level = 0): string | undefined {
  const covering = home.regions.filter((region) => {
    if ((region.level ?? 0) !== level) return false;
    const box = boxOf(region.boundary.vertices);
    return point.x >= box.minX && point.x <= box.maxX && point.y >= box.minY && point.y <= box.maxY;
  });
  // The smallest one, so a room drawn inside another is the one you meant.
  return covering.sort((left, right) => area(left.boundary.vertices) - area(right.boundary.vertices))[0]?.regionId;
}

function area(vertices: Point[]): number {
  const box = boxOf(vertices);
  return (box.maxX - box.minX) * (box.maxY - box.minY);
}

/**
 * Draw a room by dragging its two corners out, instead of receiving a four-by-four box off-screen.
 *
 * The old `addRoom` put a fixed rectangle to the right of everything already drawn and joined it to
 * the first traversable room it found, which is a room somewhere else connected to something
 * arbitrary. Drawing it is what somebody planning a flat is actually doing.
 */
export function createRoomFromBox(
  home: HomeModel,
  box: PlanBox,
  level = 0,
): { model: HomeModel; selectedId: string } {
  const id = nextId("room", home.regions.map((item) => item.regionId));
  const tidy: PlanBox = {
    minX: snap(Math.min(box.minX, box.maxX)),
    minY: snap(Math.min(box.minY, box.maxY)),
    maxX: snap(Math.max(box.minX, box.maxX)),
    maxY: snap(Math.max(box.minY, box.maxY)),
  };
  if (tidy.maxX - tidy.minX < MINIMUM_EXTENT || tidy.maxY - tidy.minY < MINIMUM_EXTENT) {
    throw new Error("A room has to be dragged out to at least 30 cm across.");
  }
  return {
    model: {
      ...home,
      regions: [...home.regions, {
        regionId: id,
        kind: "room",
        boundary: { vertices: rectangle(tidy) },
        traversable: true,
        ...(level ? { level } : {}),
      }],
    },
    selectedId: id,
  };
}

export interface WallCandidate {
  regionAId: string;
  regionBId: string;
  /** Where the doorway would go, on the shared wall. */
  x: number;
  y: number;
  vertical: boolean;
  /** How much wall the two rooms share there. */
  overlapMetres: number;
}

/** How near the pointer has to come to a shared wall for the door tool to offer it. */
const WALL_REACH_METRES = 0.45;

/**
 * The party wall under the pointer, if two rooms meet there with room enough for a door.
 *
 * A doorway is the one thing the plan is made of that the editor could not make: rooms could be
 * added, furniture could be added, sensors could be added, and the way between two rooms could only
 * be got by adding a room, which invented a passage to whichever room happened to be first.
 */
export function sharedWallAt(
  home: HomeModel,
  point: Point,
  level = 0,
  minimumOverlap = 0.9,
): WallCandidate | undefined {
  const rooms = home.regions
    .filter((region) => (region.level ?? 0) === level)
    .map((region) => ({ id: region.regionId, box: boxOf(region.boundary.vertices) }));
  let best: WallCandidate | undefined;
  let nearest = WALL_REACH_METRES;
  for (const left of rooms) {
    for (const right of rooms) {
      if (left.id >= right.id) continue;
      for (const [a, b] of [[left, right], [right, left]] as const) {
        // Vertical contact: a's right edge against b's left edge.
        if (Math.abs(a.box.maxX - b.box.minX) < 1e-6) {
          const low = Math.max(a.box.minY, b.box.minY);
          const high = Math.min(a.box.maxY, b.box.maxY);
          if (high - low < minimumOverlap) continue;
          const y = Math.min(Math.max(point.y, low + 0.5), high - 0.5);
          const distance = Math.hypot(point.x - a.box.maxX, point.y - y);
          if (distance >= nearest) continue;
          nearest = distance;
          best = { regionAId: left.id, regionBId: right.id, x: a.box.maxX, y, vertical: true, overlapMetres: high - low };
        }
        if (Math.abs(a.box.maxY - b.box.minY) < 1e-6) {
          const low = Math.max(a.box.minX, b.box.minX);
          const high = Math.min(a.box.maxX, b.box.maxX);
          if (high - low < minimumOverlap) continue;
          const x = Math.min(Math.max(point.x, low + 0.5), high - 0.5);
          const distance = Math.hypot(point.x - x, point.y - a.box.maxY);
          if (distance >= nearest) continue;
          nearest = distance;
          best = { regionAId: left.id, regionBId: right.id, x, y: a.box.maxY, vertical: false, overlapMetres: high - low };
        }
      }
    }
  }
  return best;
}

/** Half a doorway's width, which is how far inside each room its own portal sits. */
const PORTAL_INSET = 0.4;

export function addDoorway(
  home: HomeModel,
  wall: WallCandidate,
): { model: HomeModel; selectedId: string } {
  const id = nextId("door", home.connections.map((item) => item.connectionId));
  const boxes = new Map(home.regions.map((region) => [region.regionId, boxOf(region.boundary.vertices)]));
  // Portals sit *inside* their own room, because navigable space is the room eroded by the body
  // radius and a point on the wall itself is never in it.
  const inset = (regionId: string): Point => {
    const box = boxes.get(regionId);
    if (!box) return { x: wall.x, y: wall.y };
    if (wall.vertical) {
      const centreX = (box.minX + box.maxX) / 2;
      return { x: snap(wall.x + (centreX < wall.x ? -PORTAL_INSET : PORTAL_INSET)), y: snap(wall.y) };
    }
    const centreY = (box.minY + box.maxY) / 2;
    return { x: snap(wall.x), y: snap(wall.y + (centreY < wall.y ? -PORTAL_INSET : PORTAL_INSET)) };
  };
  return {
    model: {
      ...home,
      connections: [...home.connections, {
        connectionId: id,
        regionAId: wall.regionAId,
        regionBId: wall.regionBId,
        kind: "doorway",
        bidirectional: true,
        widthMeters: 1,
        portalA: inset(wall.regionAId),
        portalB: inset(wall.regionBId),
      }],
    },
    selectedId: id,
  };
}

/**
 * The action a capability is exercised through, for capabilities this home does not already use.
 *
 * Read off the home first — an existing wardrobe shows exactly what a wardrobe's `graspable` is
 * exercised by — and only fall back to this. Both are the action catalog's own vocabulary; what
 * this table cannot know is which operations *this* behaviour happens to name, which is why the
 * home is asked first.
 */
const CAPABILITY_ACTIONS: Record<string, string[]> = {
  cleanable: ["clean"],
  communication: ["communicate"],
  consumable: ["consume"],
  exercise_support: ["exercise"],
  food_preparation: ["prepare_food"],
  graspable: ["take_item"],
  inspectable: ["inspect"],
  interaction_point: ["move_to_capability"],
  laundry_support: ["laundry_step"],
  leisure_support: ["leisure"],
  medication_support: ["manage_medication"],
  openable: ["open", "close"],
  personal_care_support: ["personal_care"],
  reachable: ["move_to"],
  storable: ["put_item"],
  storage_support: ["organize"],
  switchable: ["activate", "deactivate"],
  transport_reachable: ["travel_to"],
  wearable: ["dress"],
  work_support: ["perform_work"],
};

/**
 * Put a real piece of furniture where it was dropped.
 *
 * The furniture tool used to add a nameless 0.8 by 0.8 box: no type, so no drawing and no glyph,
 * and no entity, so nothing in the home could ever be done at it. A bed is three coupled things —
 * a footprint the planner walks round, an entity saying what it is for, and the spot the resident
 * stands on to use it — and adding one means adding all three.
 */
export function addFurnitureAt(
  home: HomeModel,
  entityType: string,
  point: Point,
  level = 0,
): { model: HomeModel; selectedId: string } {
  const regionId = regionAt(home, point, level);
  if (!regionId) throw new Error("Drop furniture inside a room.");
  const entityId = nextId(entityType, home.entities.map((item) => item.entityId));
  const [extent, depth] = furnitureSize(entityType);
  const declared = declaredEntityTypes()[entityType];
  // A set, because several of the pack's own role aliases *are* the type name — `sofa` answers to
  // "sofa", "seating" and "rest_area" — and the contract refuses a capability whose roles repeat.
  const roles = [...new Set([entityType, ...(declared?.roleAliases ?? [])])].sort();
  const capabilities = entityCapabilities(home, entityType, roles, declared?.capabilities);
  const pointId = `point_${entityId}`;
  const footprint: PlanBox = {
    minX: snap(point.x - extent / 2), minY: snap(point.y - depth / 2),
    maxX: snap(point.x + extent / 2), maxY: snap(point.y + depth / 2),
  };
  return {
    model: {
      ...home,
      obstacles: [...home.obstacles, {
        obstacleId: `obstacle_${entityId}`,
        regionId,
        // Authored facing the room, which is the bearing the symbols are drawn at.
        orientationDegrees: 90,
        boundary: { vertices: rectangle(footprint) },
      }],
      entities: [...home.entities, {
        entityId,
        entityType,
        regionId,
        interactionPointId: pointId,
        capabilities,
        // Both are required the moment a capability is openable or switchable, and harmless
        // otherwise: the generator writes them on every entity for the same reason.
        initialState: { open: false, active: false },
      }],
      interactionPoints: [
        // Every room carries an anchor and a service point, both invisible and both usually near
        // the middle — which is exactly where somebody drops a chair. Refusing the chair for them
        // is refusing it for a reason nobody can see, and they are only "a spot in the room's free
        // space" anyway: the free space moved, so they move with it.
        ...home.interactionPoints.map((item) =>
          item.regionId === regionId ? stepAside(item, footprint, home, regionId) : item),
        {
          interactionPointId: pointId,
          regionId,
          // In front of the piece, which is where the body stands and which way the glyph faces.
          position: { x: snap(point.x), y: snap(point.y + depth / 2 + 0.35) },
          approachRadiusMeters: 0.25,
        },
      ],
    },
    selectedId: `obstacle_${entityId}`,
  };
}

/**
 * Move a standing point that the piece just dropped has landed on, to the nearest floor that works.
 *
 * "Nearest that works" means the same thing the gate means: inside the room by the point's own
 * reach, and that far from every obstacle. The search is a coarse grid because the answer only has
 * to be somewhere a body fits, not somewhere optimal.
 */
function stepAside(
  point: HomeModel["interactionPoints"][number],
  placed: PlanBox,
  home: HomeModel,
  regionId: string,
): HomeModel["interactionPoints"][number] {
  const reach = point.approachRadiusMeters || 0.25;
  const clear = (box: PlanBox, at: Point) =>
    at.x < box.minX - reach || at.x > box.maxX + reach || at.y < box.minY - reach || at.y > box.maxY + reach;
  if (clear(placed, point.position)) return point;
  const region = home.regions.find((item) => item.regionId === regionId);
  if (!region) return point;
  const room = boxOf(region.boundary.vertices);
  const blockers = [
    placed,
    ...home.obstacles.filter((item) => item.regionId === regionId).map((item) => boxOf(item.boundary.vertices)),
  ];
  const step = 0.2;
  let best: Point | undefined;
  let nearest = Infinity;
  for (let x = room.minX + reach; x <= room.maxX - reach + 1e-9; x += step) {
    for (let y = room.minY + reach; y <= room.maxY - reach + 1e-9; y += step) {
      const candidate = { x: snap(x), y: snap(y) };
      if (!blockers.every((box) => clear(box, candidate))) continue;
      const distance = Math.hypot(candidate.x - point.position.x, candidate.y - point.position.y);
      if (distance >= nearest) continue;
      nearest = distance;
      best = candidate;
    }
  }
  // Nowhere in the room works: leave the point where it is and let the fault report say so, rather
  // than moving it somewhere that is wrong in a different way.
  return best ? { ...point, position: best } : point;
}

function entityCapabilities(
  home: HomeModel,
  entityType: string,
  roles: string[],
  declared: string[] | undefined,
): HomeEntity["capabilities"] {
  // A sibling already in this home is the best answer there is: it was built by the generator from
  // this scenario's own behaviour, so it names the operations this home actually exercises.
  const sibling = home.entities.find((item) => item.entityType === entityType);
  if (sibling) {
    return sibling.capabilities.map((item) => ({ ...item, roles: [...roles] }));
  }
  const used = new Map<string, string[]>();
  for (const entity of home.entities) {
    for (const item of entity.capabilities) {
      if (!used.has(item.capability)) used.set(item.capability, [...item.supportedOperations]);
    }
  }
  const names = declared?.length ? declared : ["cleanable"];
  const built = [...new Set([...names, "interaction_point"])]
    .map((capability) => ({
      capability,
      roles: [...roles],
      supportedOperations: used.get(capability) ?? CAPABILITY_ACTIONS[capability] ?? [],
    }))
    .filter((item) => item.supportedOperations.length > 0)
    .sort((left, right) => left.capability.localeCompare(right.capability));
  // The contract wants at least one, and something you can walk to is the least a thing can be.
  return built.length > 0
    ? built
    : [{ capability: "interaction_point", roles: [...roles], supportedOperations: ["move_to_capability"] }];
}

/** The same for a sensor: installed where the researcher pointed at, not where the code guessed. */
export function addSensorAt(
  model: SensorModel,
  home: HomeModel,
  type: SensorBase["sensorType"],
  point: Point,
  level = 0,
): { model: SensorModel; selectedId: string } {
  const regionId = regionAt(home, point, level);
  if (!regionId) throw new Error("Install a sensor inside a room.");
  const placed = addSensor(model, home, type);
  const region = home.regions.find((item) => item.regionId === regionId);
  return {
    model: {
      ...placed.model,
      sensors: placed.model.sensors.map((sensor) => {
        if (sensor.sensorId !== placed.selectedId) return sensor;
        const moved: SensorBase = { ...sensor, position: { x: snap(point.x), y: snap(point.y) } };
        // A PIR watches the room it was dropped in; the others belong to a thing, not to a place.
        if (moved.sensorType === "pir" && region) {
          return { ...moved, regionIds: [regionId], coverage: structuredClone(region.boundary) };
        }
        if (moved.sensorType === "temperature") return { ...moved, regionId };
        return moved;
      }),
    },
    selectedId: placed.selectedId,
  };
}

/** How far apart two storeys are drawn, matching the generator's own spacing. */
const STOREY_GAP_METRES = 4;

/**
 * A landing to arrive on, beside the plan rather than on top of it.
 *
 * Two floors are two blocks of one coordinate plane, which is what keeps every geometric rule in
 * the model working. Internal on purpose: a storey is only ever made by the flight that reaches
 * it, and a landing on its own is the orphan floor the plan gate rightly refuses.
 */
function landingOn(home: HomeModel, level: number): { model: HomeModel; selectedId: string } {
  const used = home.regions.flatMap((item) => item.boundary.vertices.map((point) => point.x));
  const originX = snap(Math.max(...used, 0) + STOREY_GAP_METRES);
  const id = nextId("landing", home.regions.map((item) => item.regionId));
  return {
    model: {
      ...home,
      regions: [...home.regions, {
        regionId: id,
        kind: "room",
        traversable: true,
        level,
        boundary: { vertices: rectangle({ minX: originX, minY: 0, maxX: originX + 3, maxY: 2.4 }) },
      }],
    },
    selectedId: id,
  };
}

/** Move a room, and everything standing in it, to another storey. */
export function setRegionLevel(home: HomeModel, regionId: string, level: number): HomeModel {
  return {
    ...home,
    regions: home.regions.map((item) => item.regionId === regionId ? { ...item, level } : item),
  };
}


/** A flight is a metre wide and, at most, two and a half metres of tread. */
const STAIR_WIDTH = 1;
const STAIR_RUN = 2.6;
/** How long the climb actually is, matching the generator's own `stairRunMeters`. */
const STAIR_CLIMB_METRES = 4.5;

/**
 * Where a flight of stairs goes in a room, and the point at its foot.
 *
 * Against the wall furthest from the doorways, because that is where stairs go and because a
 * staircase across a doorway is a room nobody can leave. Cut short rather than refused when the
 * room is shallow: a landing is a small room, and a full-length flight in one leaves twenty
 * centimetres of floor at the bottom — less than a body.
 */
function stairPose(home: HomeModel, regionId: string): { box: PlanBox; foot: Point } | undefined {
  const region = home.regions.find((item) => item.regionId === regionId);
  if (!region) return undefined;
  const room = boxOf(region.boundary.vertices);
  const reach = 0.35;
  const doors: Point[] = [];
  for (const connection of home.connections) {
    if (connection.regionAId === regionId && connection.portalA) doors.push(connection.portalA);
    if (connection.regionBId === regionId && connection.portalB) doors.push(connection.portalB);
  }
  const taken = home.obstacles
    .filter((item) => item.regionId === regionId)
    .map((item) => boxOf(item.boundary.vertices));
  const clearOf = (box: PlanBox, at: Point, margin: number) =>
    at.x < box.minX - margin || at.x > box.maxX + margin
    || at.y < box.minY - margin || at.y > box.maxY + margin;

  let best: { box: PlanBox; foot: Point; margin: number } | undefined;
  for (const facing of [[0, 1], [0, -1], [1, 0], [-1, 0]] as const) {
    const vertical = facing[0] === 0;
    const along = vertical ? room.maxX - room.minX : room.maxY - room.minY;
    const across = vertical ? room.maxY - room.minY : room.maxX - room.minX;
    const width = Math.min(STAIR_WIDTH, along - 2 * reach);
    if (width < 0.7) continue;
    for (const run of [STAIR_RUN, 2.2, 1.8, 1.4, 1.1]) {
      if (run > across - reach * 2 - 0.1) continue;
      const low = vertical ? room.minX : room.minY;
      for (let offset = 0; offset <= along - width + 1e-9; offset += 0.2) {
        const centre = low + offset + width / 2;
        const box: PlanBox = vertical
          ? {
              minX: snap(centre - width / 2), maxX: snap(centre + width / 2),
              minY: snap(facing[1] > 0 ? room.minY : room.maxY - run),
              maxY: snap(facing[1] > 0 ? room.minY + run : room.maxY),
            }
          : {
              minY: snap(centre - width / 2), maxY: snap(centre + width / 2),
              minX: snap(facing[0] > 0 ? room.minX : room.maxX - run),
              maxX: snap(facing[0] > 0 ? room.minX + run : room.maxX),
            };
        const foot: Point = {
          x: snap(vertical ? centre : (facing[0] > 0 ? box.maxX + reach : box.minX - reach)),
          y: snap(vertical ? (facing[1] > 0 ? box.maxY + reach : box.minY - reach) : centre),
        };
        if (foot.x < room.minX + reach || foot.x > room.maxX - reach) continue;
        if (foot.y < room.minY + reach || foot.y > room.maxY - reach) continue;
        if (taken.some((other) => !clearOf(other, { x: box.minX, y: box.minY }, 0) && !clearOf(box, { x: other.minX, y: other.minY }, 0))) continue;
        if (taken.some((other) => other.minX < box.maxX && box.minX < other.maxX && other.minY < box.maxY && box.minY < other.maxY)) continue;
        // The doorways stay usable, and so does the foot of the flight itself.
        const margin = Math.min(
          ...doors.map((door) => Math.min(distanceToBox(door, box), Math.hypot(door.x - foot.x, door.y - foot.y))),
          99,
        );
        if (margin < 0.8) continue;
        // Longest flight first, then the quietest corner of the room.
        if (best && (best.box.maxY - best.box.minY) * (best.box.maxX - best.box.minX) > (box.maxX - box.minX) * (box.maxY - box.minY)) continue;
        if (best && margin <= best.margin) continue;
        best = { box, foot, margin };
      }
    }
    if (best) break;
  }
  return best ? { box: best.box, foot: best.foot } : undefined;
}

function distanceToBox(point: Point, box: PlanBox): number {
  const dx = Math.max(box.minX - point.x, 0, point.x - box.maxX);
  const dy = Math.max(box.minY - point.y, 0, point.y - box.maxY);
  return Math.hypot(dx, dy);
}

/**
 * Join two storeys with a staircase.
 *
 * The one thing a second floor cannot be without, which is why it is no longer something you add
 * afterwards: `addStoreyByStairs` builds the flight and the storey in the same breath, and this is
 * the half that makes the new landing reachable.
 *
 * A stairway is walked, like a doorway, but its two ends do not touch: each storey is tiled in its
 * own block of the plan, so the portals sit metres apart in coordinates that say nothing about how
 * far the climb is. It therefore declares its own length. And it is a real object at both ends,
 * standing on real floor, which is why each end gets a footprint the furniture has to work round.
 */
function addStairway(
  home: HomeModel,
  fromRegionId: string,
  toRegionId: string,
): { model: HomeModel; selectedId: string } {
  const from = home.regions.find((item) => item.regionId === fromRegionId);
  const to = home.regions.find((item) => item.regionId === toRegionId);
  if (!from || !to) throw new Error("A staircase joins two rooms of this home.");
  if ((from.level ?? 0) === (to.level ?? 0)) {
    throw new Error("A staircase joins two storeys. Two rooms on the same floor want a doorway.");
  }
  const lower = (from.level ?? 0) < (to.level ?? 0) ? from : to;
  const upper = lower === from ? to : from;
  const bottom = stairPose(home, lower.regionId);
  const top = stairPose(home, upper.regionId);
  for (const [pose, region] of [[bottom, lower], [top, upper]] as const) {
    if (!pose) {
      throw new Error(`There is no wall in ${region.regionId.replaceAll("_", " ")} with room for a flight of stairs and somewhere to step off it.`);
    }
  }
  const flights = [
    { region: lower, pose: bottom!, bearing: stairBearing(home, lower.regionId, bottom!.box, bottom!.foot) },
    { region: upper, pose: top!, bearing: stairBearing(home, upper.regionId, top!.box, top!.foot) },
  ];
  const connectionId = nextId("stairs", home.connections.map((item) => item.connectionId));
  let model: HomeModel = { ...home };
  for (const flight of flights) {
    // Named after the flight it belongs to, exactly as the generator names its own
    // (`obstacle_stairs_<bottom>_<top>_<region>`): the treads are the only obstacles with no entity
    // to own them, so the id is the one thing that says which staircase they are the foot of.
    model = {
      ...model,
      obstacles: [...model.obstacles, {
        obstacleId: `obstacle_${connectionId}_${flight.region.regionId}`,
        regionId: flight.region.regionId,
        orientationDegrees: flight.bearing,
        boundary: { vertices: rectangle(flight.pose.box) },
      }],
      interactionPoints: model.interactionPoints.map((item) =>
        item.regionId === flight.region.regionId ? stepAside(item, flight.pose.box, model, flight.region.regionId) : item),
    };
  }
  return {
    model: {
      ...model,
      connections: [...model.connections, {
        connectionId,
        regionAId: lower.regionId,
        regionBId: upper.regionId,
        kind: "stairway",
        bidirectional: true,
        widthMeters: 1,
        distanceMeters: STAIR_CLIMB_METRES,
        portalA: bottom!.foot,
        portalB: top!.foot,
      }],
    },
    selectedId: connectionId,
  };
}

/**
 * Add a storey by building the flight that reaches it: up, or down when what you want is a cellar.
 *
 * A floor nobody can climb to is not a floor. `Add floor` used to hand you a landing and, in the
 * same breath, the warning that nothing reached it — and the plan gate then refused the home for
 * exactly that reason. So the staircase is the thing the user draws, and the storey arrives with
 * it: pick the room the flight starts in, say which way it goes, and the landing at the far end is
 * born already joined to the house.
 */
export function addStoreyByStairs(
  home: HomeModel,
  fromRegionId: string,
  direction: "up" | "down",
): { model: HomeModel; selectedId: string; level: number } {
  const from = home.regions.find((item) => item.regionId === fromRegionId);
  if (!from) throw new Error("A staircase starts in a room of this home.");
  if (from.kind !== "room" || !from.traversable) {
    throw new Error("A staircase starts in a room a body can stand in, not on a balcony or out in the street.");
  }
  const level = (from.level ?? 0) + (direction === "up" ? 1 : -1);
  if (home.regions.some((item) => (item.level ?? 0) === level)) {
    throw new Error(`There is already a floor ${direction === "up" ? "above" : "below"} this one.`);
  }
  // Nothing escapes a refusal: the landing is built into a copy, and if no flight fits at either
  // end the whole call throws with that model still unreferenced.
  const landing = landingOn(home, level);
  const joined = addStairway(landing.model, fromRegionId, landing.selectedId);
  return { model: joined.model, selectedId: landing.selectedId, level };
}

/** Which way somebody stepping off the flight is facing, as a bearing in the home's own frame. */
function stairBearing(home: HomeModel, regionId: string, box: PlanBox, foot: Point): number {
  const centreX = (box.minX + box.maxX) / 2;
  const centreY = (box.minY + box.maxY) / 2;
  const degrees = (Math.atan2(foot.y - centreY, foot.x - centreX) * 180) / Math.PI;
  return Math.round(((degrees % 360) + 360) % 360 / 90) * 90 % 360;
}
