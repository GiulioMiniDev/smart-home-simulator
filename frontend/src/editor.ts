import type { HomeModel, Point, SensorBase, SensorModel } from "./types";

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

export function addRoom(home: HomeModel): { model: HomeModel; selectedId: string } {
  const id = nextId("room", home.regions.map((item) => item.regionId));
  const maximumX = Math.max(...home.regions.flatMap((item) => item.boundary.vertices.map((point) => point.x)));
  const vertices = [
    { x: maximumX + 1, y: 0 },
    { x: maximumX + 5, y: 0 },
    { x: maximumX + 5, y: 4 },
    { x: maximumX + 1, y: 4 },
  ];
  const anchor = home.regions.find((item) => item.traversable);
  return {
    model: {
      ...home,
      regions: [...home.regions, { regionId: id, kind: "room", boundary: { vertices }, traversable: true }],
      connections: anchor ? [...home.connections, {
        connectionId: nextId("passage", home.connections.map((item) => item.connectionId)),
        regionAId: anchor.regionId,
        regionBId: id,
        kind: "passage",
        bidirectional: true,
        widthMeters: 1,
      }] : home.connections,
    },
    selectedId: id,
  };
}

export function addObstacle(home: HomeModel, regionId?: string): { model: HomeModel; selectedId: string } {
  const region = home.regions.find((item) => item.regionId === regionId) ?? home.regions[0];
  if (!region) throw new Error("Create a region before adding an obstacle");
  const id = nextId("obstacle", home.obstacles.map((item) => item.obstacleId));
  const point = centre(region.boundary.vertices);
  const vertices = [
    { x: point.x - 0.4, y: point.y - 0.4 },
    { x: point.x + 0.4, y: point.y - 0.4 },
    { x: point.x + 0.4, y: point.y + 0.4 },
    { x: point.x - 0.4, y: point.y + 0.4 },
  ];
  return {
    model: { ...home, obstacles: [...home.obstacles, { obstacleId: id, regionId: region.regionId, boundary: { vertices } }] },
    selectedId: id,
  };
}

const timing = { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 };
const errorModel = { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 };

export function addSensor(model: SensorModel, home: HomeModel, type: SensorBase["sensorType"]): { model: SensorModel; selectedId: string } {
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

export function removeSelection(home: HomeModel, sensorModel: SensorModel | undefined, selectedId: string): { home: HomeModel; sensors?: SensorModel } {
  const entity = home.entities.find((item) => item.entityId === selectedId);
  const region = home.regions.find((item) => item.regionId === selectedId);
  const interactionPointId = entity?.interactionPointId;
  return {
    home: {
      ...home,
      regions: home.regions.filter((item) => item.regionId !== selectedId),
      connections: region ? home.connections.filter((item) => item.regionAId !== selectedId && item.regionBId !== selectedId) : home.connections,
      obstacles: home.obstacles.filter((item) => item.obstacleId !== selectedId && item.regionId !== selectedId),
      interactionPoints: home.interactionPoints.filter((item) => item.interactionPointId !== selectedId && item.interactionPointId !== interactionPointId && item.regionId !== selectedId),
      entities: home.entities.filter((item) => item.entityId !== selectedId && item.regionId !== selectedId),
    },
    sensors: sensorModel ? { ...sensorModel, sensors: sensorModel.sensors.filter((item) => item.sensorId !== selectedId) } : undefined,
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
  const entrance = home.entities.find((entity) =>
    entity.capabilities.some((capability) =>
      capability.supportedOperations.some((item) => item === "leave_home" || item === "enter_home"),
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
