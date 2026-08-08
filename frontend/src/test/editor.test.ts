import { describe, expect, it } from "vitest";
import {
  addObstacle,
  addRoom,
  addSensor,
  boxOf,
  cutDoorways,
  dwellingRegionIds,
  movePlanObject,
  pirRange,
  planDoors,
  planFrontDoor,
  planWalls,
  polygonArea,
  removeSelection,
  resizePlanObject,
  setPirRange,
  snap,
} from "../editor";
import type { HomeModel, SensorModel } from "../types";

const home = (): HomeModel => ({
  schemaVersion: "1.0.0", documentType: "home_model", homeId: "home", homeVersion: "1", coordinateSystem: {},
  regions: [{ regionId: "room_01", kind: "room", boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] }, traversable: true }],
  connections: [], obstacles: [], interactionPoints: [{ interactionPointId: "point", regionId: "room_01", position: { x: 1, y: 1 }, approachRadiusMeters: 0.5 }],
  entities: [{ entityId: "door", entityType: "door", regionId: "room_01", interactionPointId: "point", capabilities: [], initialState: { open: false } }],
  locationBindings: [], resourceBindings: [], kinematicDefaults: {},
});

const sensors = (): SensorModel => ({
  schemaVersion: "1.0.0", documentType: "sensor_model", sensorModelId: "sensors", sensorModelVersion: "1", sourceBundleId: "bundle", sourceBundleSha256: "a".repeat(64), seed: 1,
  regionIds: ["room_01"], entityIds: ["door"], sensors: [],
});

describe("editor commands", () => {
  it("adds a connected room with collision-free identifiers", () => {
    const first = addRoom(home());
    const second = addRoom(first.model);
    expect(first.selectedId).toBe("room_02");
    expect(second.selectedId).toBe("room_03");
    expect(second.model.connections).toHaveLength(2);
    expect(second.model.regions[2].boundary.vertices[0].x).toBeGreaterThan(4);
    const isolated = addRoom({ ...home(), regions: home().regions.map((item) => ({ ...item, traversable: false })) });
    expect(isolated.model.connections).toHaveLength(0);
  });

  it("adds an obstacle to the selected or first region", () => {
    const first = addObstacle(home(), "room_01");
    const second = addObstacle(first.model, "missing");
    expect(second.model.obstacles.map((item) => item.obstacleId)).toEqual(["obstacle_01", "obstacle_02"]);
    expect(first.model.obstacles[0].regionId).toBe("room_01");
    expect(() => addObstacle({ ...home(), regions: [] })).toThrow("Create a region");
  });

  it.each(["pir", "contact", "temperature"] as const)("adds and configures a %s sensor", (type) => {
    const result = addSensor(sensors(), home(), type);
    expect(result.selectedId).toBe(`${type}_01`);
    expect(result.model.sensors[0].sensorType).toBe(type);
    expect(result.model.sensors[0].position).toEqual({ x: 2, y: 2 });
  });

  it("rejects sensor creation without required spatial providers", () => {
    const empty = { ...home(), entities: [] };
    expect(() => addSensor(sensors(), { ...empty, regions: [] }, "pir")).toThrow("Create a region");
    expect(() => addSensor(sensors(), empty, "contact")).toThrow("contact sensor requires");
    expect(() => addSensor(sensors(), empty, "temperature")).toThrow("temperature sensor requires");
  });

  it("removes regions, providers and sensors with their dependent objects", () => {
    const withSensor = addSensor(sensors(), home(), "pir").model;
    const noSensor = removeSelection(home(), withSensor, "pir_01");
    expect(noSensor.sensors?.sensors).toHaveLength(0);
    const noEntity = removeSelection(home(), withSensor, "door");
    expect(noEntity.home.entities).toHaveLength(0);
    expect(noEntity.home.interactionPoints).toHaveLength(0);
    const noRoom = removeSelection(home(), withSensor, "room_01");
    expect(noRoom.home.regions).toHaveLength(0);
    expect(noRoom.home.obstacles).toHaveLength(0);
    expect(removeSelection(home(), undefined, "missing").sensors).toBeUndefined();
  });
});

describe("direct manipulation on the plan", () => {
  const furnished = (): HomeModel => ({
    ...home(),
    obstacles: [{ obstacleId: "obstacle_door", regionId: "room_01", boundary: { vertices: [{ x: 1, y: 1 }, { x: 1.8, y: 1 }, { x: 1.8, y: 1.6 }, { x: 1, y: 1.6 }] } }],
  });
  const withPir = (): SensorModel => ({
    ...sensors(),
    sensors: [{
      sensorId: "pir_01", sensorType: "pir", position: { x: 2, y: 2 }, regionIds: ["room_01"],
      coverage: { vertices: [{ x: 1, y: 1 }, { x: 3, y: 1 }, { x: 3, y: 3 }, { x: 1, y: 3 }] },
      timing: { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 },
      errorModel: { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 },
      failureWindows: [],
    }],
  });

  it("drags furniture as one piece: footprint and the point you walk to", () => {
    // Moving the footprint alone leaves the resident reaching for a wardrobe that is no longer
    // there, and the home validator says so — so the whole provider travels together.
    const result = movePlanObject(furnished(), undefined, "obstacle_door", 0.5, 0.25);
    expect(result.home.obstacles[0].boundary.vertices[0]).toEqual({ x: 1.5, y: 1.3 });
    expect(result.home.interactionPoints[0].position).toEqual({ x: 1.5, y: 1.3 });
    // Selecting the provider instead of its footprint is the same gesture.
    const byEntity = movePlanObject(furnished(), undefined, "door", 0.5, 0.25);
    expect(byEntity.home).toEqual(result.home);
  });

  it("moves a room with everything standing in it", () => {
    const result = movePlanObject(furnished(), undefined, "room_01", 1, 0);
    expect(result.home.regions[0].boundary.vertices[1].x).toBe(5);
    expect(result.home.obstacles[0].boundary.vertices[0].x).toBe(2);
    expect(result.home.interactionPoints[0].position.x).toBe(2);
  });

  it("carries a PIR's coverage with the node instead of leaving it behind", () => {
    const result = movePlanObject(home(), withPir(), "pir_01", -0.5, 0);
    const sensor = result.sensors?.sensors[0];
    expect(sensor?.position).toEqual({ x: 1.5, y: 2 });
    expect((sensor?.coverage as { vertices: Array<{ x: number }> }).vertices[0].x).toBe(0.5);
  });

  it("resizes by the handle that was grabbed and refuses to turn the box inside out", () => {
    const widened = resizePlanObject(furnished(), undefined, "room_01", "e", 2, 0);
    expect(boxOf(widened.home.regions[0].boundary.vertices)).toMatchObject({ minX: 0, maxX: 6 });
    // Dragging the east edge past the west one is a slip, not a request to mirror the room.
    const collapsed = resizePlanObject(furnished(), undefined, "room_01", "e", -10, 0);
    const box = boxOf(collapsed.home.regions[0].boundary.vertices);
    expect(box.maxX).toBeGreaterThan(box.minX);
  });

  it("keeps a widened coverage inside the rooms the sensor monitors", () => {
    // A PIR cannot see through a wall, and the projection rejects a coverage that leaves its
    // regions — so the range stops at the room rather than failing on publication.
    const result = resizePlanObject(home(), withPir(), "pir_01", "e", 10, 0);
    const box = boxOf((result.sensors?.sensors[0].coverage as { vertices: Array<{ x: number; y: number }> }).vertices);
    expect(box.maxX).toBe(4);
    expect(result.sensors?.sensors[0].position).toEqual({ x: 2.5, y: 2 });
  });

  it("reads and sets a PIR range in metres around the node", () => {
    expect(pirRange(withPir().sensors[0])).toBe(1);
    const wider = setPirRange(withPir(), home(), "pir_01", 1.5);
    expect(pirRange(wider.sensors[0])).toBe(1.5);
    const clamped = setPirRange(withPir(), home(), "pir_01", 9);
    expect(boxOf((clamped.sensors[0].coverage as { vertices: Array<{ x: number; y: number }> }).vertices)).toEqual({ minX: 0, minY: 0, maxX: 4, maxY: 4 });
    // A contact sensor has no coverage to widen and is left exactly as it was.
    const contacts = { ...withPir(), sensors: [{ ...withPir().sensors[0], sensorType: "contact" as const }] };
    expect(setPirRange(contacts, home(), "pir_01", 2)).toEqual(contacts);
  });

  it("takes doorways along when their room moves, and ignores a selection it cannot place", () => {
    const withDoor: HomeModel = {
      ...furnished(),
      regions: [
        ...furnished().regions,
        { regionId: "room_02", kind: "room", traversable: true, boundary: { vertices: [{ x: 4.2, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 4 }, { x: 4.2, y: 4 }] } },
      ],
      connections: [{ connectionId: "door", regionAId: "room_01", regionBId: "room_02", kind: "doorway", bidirectional: true, widthMeters: 1, portalA: { x: 4, y: 2 }, portalB: { x: 4.2, y: 2 } }],
    };
    const moved = movePlanObject(withDoor, undefined, "room_01", 1, 0);
    // The doorway of the room that moved follows it; the far side stays on the room that did not.
    expect(moved.home.connections[0].portalA).toEqual({ x: 5, y: 2 });
    expect(moved.home.connections[0].portalB).toEqual({ x: 4.2, y: 2 });
    expect(movePlanObject(withDoor, undefined, "nothing", 1, 1).home).toEqual(withDoor);
    // The other side of the same door, and a connection drawn without portals at all.
    const fromB = movePlanObject(withDoor, undefined, "room_02", 1, 0);
    expect(fromB.home.connections[0].portalB).toEqual({ x: 5.2, y: 2 });
    expect(fromB.home.connections[0].portalA).toEqual({ x: 4, y: 2 });
    const portalless: HomeModel = { ...withDoor, connections: [{ ...withDoor.connections[0], portalA: undefined, portalB: undefined }] };
    expect(movePlanObject(portalless, undefined, "room_01", 1, 0).home.connections[0].portalA).toBeUndefined();
  });

  it("resizes a footprint, and leaves a selection with no area untouched", () => {
    const grown = resizePlanObject(furnished(), undefined, "obstacle_door", "se", 0.4, 0.4);
    expect(boxOf(grown.home.obstacles[0].boundary.vertices)).toMatchObject({ maxX: 2.2, maxY: 2 });
    expect(resizePlanObject(furnished(), undefined, "point", "se", 1, 1).home).toEqual(furnished());
    // A contact sensor has no coverage, so there is nothing to stretch.
    const contact = { ...withPir(), sensors: [{ ...withPir().sensors[0], coverage: undefined }] };
    expect(resizePlanObject(home(), contact, "pir_01", "e", 1, 0).sensors).toEqual(contact);
  });

  it("leaves a coverage alone when its sensor declares no region to stay inside", () => {
    const unbounded = { ...withPir(), sensors: [{ ...withPir().sensors[0], regionIds: undefined }] };
    const result = resizePlanObject(home(), unbounded, "pir_01", "e", 10, 0);
    expect(boxOf((result.sensors?.sensors[0].coverage as { vertices: Array<{ x: number; y: number }> }).vertices).maxX).toBe(13);
  });

  it("resizes only what was grabbed, leaving its neighbours alone", () => {
    const twoRooms: HomeModel = {
      ...furnished(),
      regions: [
        ...furnished().regions,
        { regionId: "room_02", kind: "room", traversable: true, boundary: { vertices: [{ x: 5, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 4 }, { x: 5, y: 4 }] } },
      ],
      obstacles: [
        ...furnished().obstacles,
        { obstacleId: "obstacle_chair", regionId: "room_01", boundary: { vertices: [{ x: 3, y: 3 }, { x: 3.4, y: 3 }, { x: 3.4, y: 3.4 }, { x: 3, y: 3.4 }] } },
      ],
    };
    const twoSensors: SensorModel = { ...withPir(), sensors: [...withPir().sensors, { ...withPir().sensors[0], sensorId: "pir_02" }] };

    const rooms = resizePlanObject(twoRooms, undefined, "room_01", "s", 1, 1);
    expect(rooms.home.regions[1].boundary).toEqual(twoRooms.regions[1].boundary);
    const obstacles = resizePlanObject(twoRooms, undefined, "obstacle_door", "se", 0.2, 0.2);
    expect(obstacles.home.obstacles[1].boundary).toEqual(twoRooms.obstacles[1].boundary);
    const covered = resizePlanObject(twoRooms, twoSensors, "pir_01", "e", 0.5, 0);
    expect(covered.sensors?.sensors[1]).toEqual(twoSensors.sensors[1]);
  });

  it("answers safely for a plan with no sensors and a sensor with no coverage", () => {
    expect(resizePlanObject(furnished(), undefined, "pir_01", "e", 1, 0).sensors).toBeUndefined();
    expect(movePlanObject(furnished(), undefined, "pir_01", 1, 0).sensors).toBeUndefined();
    expect(pirRange({ ...withPir().sensors[0], coverage: undefined })).toBe(0);
    // A range of zero is not a sensor that sees nothing, it is a coverage the contract refuses.
    const tiny = setPirRange(withPir(), home(), "pir_01", 0);
    expect(pirRange(tiny.sensors[0])).toBeGreaterThan(0);
  });

  it("snaps to the centimetre so a drag cannot publish floating-point noise", () => {
    const result = movePlanObject(furnished(), undefined, "room_01", 0.037, -0.061);
    expect(result.home.regions[0].boundary.vertices[0]).toEqual({ x: 0, y: -0.1 });
    expect(snap(1.234)).toBe(1.2);
  });
});

describe("what belongs to the house", () => {
  const town = (): HomeModel => ({
    ...home(),
    regions: [
      ...home().regions,
      { regionId: "hallway", kind: "room", traversable: true, boundary: { vertices: [{ x: 4, y: 0 }, { x: 6, y: 0 }, { x: 6, y: 3 }, { x: 4, y: 3 }] } },
      { regionId: "balcony", kind: "outdoor", traversable: true, boundary: { vertices: [{ x: 6, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 2 }, { x: 6, y: 2 }] } },
      { regionId: "supermarket", kind: "external", traversable: true, boundary: { vertices: [{ x: 0, y: 20 }, { x: 6, y: 20 }, { x: 6, y: 26 }, { x: 0, y: 26 } ] } },
      { regionId: "outside", kind: "outdoor", traversable: true, boundary: { vertices: [{ x: 8, y: 20 }, { x: 14, y: 20 }, { x: 14, y: 26 }, { x: 8, y: 26 }] } },
    ],
    connections: [
      { connectionId: "d1", regionAId: "room_01", regionBId: "hallway", kind: "doorway", bidirectional: true, widthMeters: 1 },
      { connectionId: "d2", regionAId: "hallway", regionBId: "balcony", kind: "doorway", bidirectional: true, widthMeters: 1 },
      { connectionId: "t1", regionAId: "hallway", regionBId: "supermarket", kind: "transit", bidirectional: true, widthMeters: 1 },
      { connectionId: "t2", regionAId: "hallway", regionBId: "outside", kind: "transit", bidirectional: true, widthMeters: 1 },
    ],
  });

  it("keeps the rooms and whatever a door leads to, and drops what you travel to", () => {
    // The balcony is outdoor and still part of the flat, because you reach it through a door.
    // The supermarket is 20 metres away down a transit link: it is a place, not a room.
    expect([...dwellingRegionIds(town())].sort()).toEqual(["balcony", "hallway", "room_01"]);
  });

  it("treats a plan with no external places as entirely the house", () => {
    expect([...dwellingRegionIds(home())]).toEqual(["room_01"]);
  });

  it("leaves out a landing that is only a transit region, however close it claims to be", () => {
    // The generator tiles only rooms into the floorplan, so a `transit` location — the landing
    // outside the front door — is parked with the far-away places. On a planimetry it is a stray
    // box thirty metres out, dragging a dashed line across the flat.
    const withLanding: HomeModel = {
      ...town(),
      regions: [
        ...town().regions,
        { regionId: "home_entrance", kind: "transit", traversable: true, boundary: { vertices: [{ x: 30, y: 20 }, { x: 36, y: 20 }, { x: 36, y: 26 }, { x: 30, y: 26 }] } },
      ],
      connections: [
        ...town().connections,
        { connectionId: "t3", regionAId: "hallway", regionBId: "home_entrance", kind: "transit", bidirectional: true, widthMeters: 1 },
      ],
    };

    expect(dwellingRegionIds(withLanding).has("home_entrance")).toBe(false);

    // A landing you actually walk through a door into is part of the flat, whatever it is typed.
    const withDoor: HomeModel = {
      ...withLanding,
      connections: withLanding.connections.map((item) => item.connectionId === "t3" ? { ...item, kind: "doorway" as const } : item),
    };
    expect(dwellingRegionIds(withDoor).has("home_entrance")).toBe(true);
  });
});

describe("drawing a floorplan out of a simulation model", () => {
  // Two rooms sharing the wall x = 4, with a metre-wide door in it.
  const flat = (): HomeModel => ({
    ...home(),
    regions: [
      { regionId: "kitchen", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 3 }, { x: 0, y: 3 }] } },
      { regionId: "living_room", kind: "room", traversable: true, boundary: { vertices: [{ x: 4, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 3 }, { x: 4, y: 3 }] } },
    ],
    connections: [{ connectionId: "door", regionAId: "kitchen", regionBId: "living_room", kind: "doorway", bidirectional: true, widthMeters: 1, portalA: { x: 3.6, y: 1.5 }, portalB: { x: 4.4, y: 1.5 } }],
    obstacles: [],
    interactionPoints: [],
    entities: [],
  });
  const ids = (home: HomeModel) => new Set(home.regions.map((item) => item.regionId));

  it("tells the envelope of the flat from what merely divides it", () => {
    const walls = planWalls(flat(), ids(flat()));
    const shared = walls.filter((item) => !item.exterior);
    // The wall at x = 4 has a room on both sides; it is drawn once, not once per room.
    expect(shared).toHaveLength(1);
    expect([shared[0]?.x1, shared[0]?.x2]).toEqual([4, 4]);
    // Six outer edges: three of each room, the fourth being the shared one.
    expect(walls.filter((item) => item.exterior)).toHaveLength(6);
  });

  it("puts the opening across the wall the two portals straddle", () => {
    const [door] = planDoors(flat(), ids(flat()));
    expect(door).toBeDefined();
    // Portals sit either side of x = 4 at y = 1.5, so the opening runs along the wall through it.
    expect([door!.x1, door!.x2]).toEqual([4, 4]);
    expect([door!.y1, door!.y2].sort()).toEqual([1, 2]);
    // The leaf swings a full width into the room the connection points at.
    expect(door!.leafX).toBe(5);
    expect(door!.arc).toContain("A 1 1");
  });

  it("cuts the opening out of the wall instead of painting over it", () => {
    const doors = planDoors(flat(), ids(flat()));
    const cut = cutDoorways(planWalls(flat(), ids(flat())), doors);
    const partitions = cut.filter((item) => !item.exterior);
    // The shared wall comes back in two pieces, above and below the door, totalling 3 - 1 metres.
    expect(partitions).toHaveLength(2);
    const length = partitions.reduce((sum, item) => sum + Math.hypot(item.x2 - item.x1, item.y2 - item.y1), 0);
    expect(length).toBeCloseTo(2, 6);
    // Outer walls have no openings and are left whole.
    expect(cut.filter((item) => item.exterior)).toHaveLength(6);
  });

  it("ignores transit links and places nobody can see", () => {
    const withOutside: HomeModel = {
      ...flat(),
      regions: [...flat().regions, { regionId: "supermarket", kind: "external", traversable: true, boundary: { vertices: [{ x: 0, y: 20 }, { x: 6, y: 20 }, { x: 6, y: 26 }, { x: 0, y: 26 }] } }],
      connections: [...flat().connections, { connectionId: "t", regionAId: "kitchen", regionBId: "supermarket", kind: "transit", bidirectional: true, widthMeters: 1, portalA: { x: 2, y: 0 }, portalB: { x: 2, y: 20 } }],
    };
    expect(planDoors(withOutside, dwellingRegionIds(withOutside))).toHaveLength(1);
  });

  it("skips connections it cannot draw and walls with no length", () => {
    // A model may carry a connection without portals (the editor creates one when you add a room)
    // and a degenerate edge; neither is a door or a wall, and neither should throw.
    const odd: HomeModel = {
      ...flat(),
      connections: [
        { connectionId: "no-portals", regionAId: "kitchen", regionBId: "living_room", kind: "passage", bidirectional: true, widthMeters: 1 },
        { connectionId: "degenerate", regionAId: "kitchen", regionBId: "living_room", kind: "doorway", bidirectional: true, widthMeters: 1, portalA: { x: 4, y: 1 }, portalB: { x: 4, y: 1 } },
      ],
    };
    expect(planDoors(odd, ids(odd))).toEqual([]);
    expect(cutDoorways([{ x1: 1, y1: 1, x2: 1, y2: 1, exterior: true }], [])).toEqual([]);
    // A door that lies on another wall's line but not on the wall itself leaves it whole.
    const wall = { x1: 0, y1: 0, x2: 0, y2: 3, exterior: false };
    const elsewhere = planDoors(flat(), ids(flat()));
    expect(cutDoorways([wall], elsewhere)).toEqual([wall]);
  });

  it("reads the same plan whichever way round its polygons are wound", () => {
    // Nothing in the contract fixes the winding, so a home authored by hand can arrive mirrored.
    const reversed: HomeModel = {
      ...flat(),
      regions: flat().regions.map((region) => ({
        ...region,
        boundary: { vertices: [...region.boundary.vertices].reverse() },
      })),
    };
    const walls = planWalls(reversed, ids(reversed));
    expect(walls.filter((item) => !item.exterior)).toHaveLength(1);
    expect(walls.filter((item) => item.exterior)).toHaveLength(6);

    // A repeated vertex is a zero-length edge: not a wall, and not a crash either.
    const degenerate: HomeModel = {
      ...flat(),
      regions: [{ ...flat().regions[0]!, boundary: { vertices: [{ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 3 }, { x: 0, y: 3 }] } }],
    };
    expect(planWalls(degenerate, new Set(["kitchen"]))).toHaveLength(4);
  });

  it("finds the way out by what the door can do, not by what it is called", () => {
    // Leaving home is a transit link plus an entity the enter/leave actions bind to; nothing in
    // the model draws an opening. The plan puts one on the exterior wall nearest where the
    // resident stands to use it, swinging outwards.
    const withDoor: HomeModel = {
      ...flat(),
      interactionPoints: [{ interactionPointId: "point_entrance", regionId: "living_room", position: { x: 7, y: 2.4 }, approachRadiusMeters: 0.3 }],
      entities: [{ entityId: "entrance_door", entityType: "entrance_door", regionId: "living_room", interactionPointId: "point_entrance", capabilities: [{ capability: "home_egress", roles: ["entrance"], supportedOperations: ["leave_home"] }], initialState: {} }],
    };

    const door = planFrontDoor(withDoor, ids(withDoor));

    expect(door).toBeDefined();
    expect(door!.kind).toBe("entrance");
    // The living room's own exterior wall at y = 3 is the closest one to (7, 2.4).
    expect(door!.y1).toBe(3);
    expect(door!.y2).toBe(3);
    // And it swings out of the flat, not back into the room.
    expect(door!.leafY).toBeGreaterThan(3);
    // The opening is cut out of that wall like any other.
    const cut = cutDoorways(planWalls(withDoor, ids(withDoor)), [door!]);
    expect(cut.filter((item) => item.exterior)).toHaveLength(7);
  });

  it("swings the front door outwards whichever way the room is wound", () => {
    const base: HomeModel = {
      ...flat(),
      regions: flat().regions.map((region) => ({ ...region, boundary: { vertices: [...region.boundary.vertices].reverse() } })),
      interactionPoints: [{ interactionPointId: "point_entrance", regionId: "living_room", position: { x: 7, y: 2.4 }, approachRadiusMeters: 0.3 }],
      entities: [{ entityId: "entrance_door", entityType: "entrance_door", regionId: "living_room", interactionPointId: "point_entrance", capabilities: [{ capability: "home_egress", roles: [], supportedOperations: ["leave_home"] }], initialState: {} }],
    };
    const door = planFrontDoor(base, ids(base));
    expect(door!.y1).toBe(3);
    expect(door!.leafY).toBeGreaterThan(3);
  });

  it("draws no front door when nothing in the home can be left through", () => {
    expect(planFrontDoor(flat(), ids(flat()))).toBeUndefined();
    // An entity whose interaction point is missing has no place to put an opening.
    const orphan: HomeModel = {
      ...flat(),
      interactionPoints: [],
      entities: [{ entityId: "door", entityType: "entrance_door", regionId: "living_room", interactionPointId: "gone", capabilities: [{ capability: "home_egress", roles: [], supportedOperations: ["leave_home"] }], initialState: {} }],
    };
    expect(planFrontDoor(orphan, ids(orphan))).toBeUndefined();
    // A room with a repeated vertex still resolves: the zero-length edge is simply not a wall.
    const degenerate: HomeModel = {
      ...flat(),
      regions: [{ regionId: "living_room", kind: "room", traversable: true, boundary: { vertices: [{ x: 4, y: 0 }, { x: 4, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 3 }, { x: 4, y: 3 }] } }],
      interactionPoints: [{ interactionPointId: "p", regionId: "living_room", position: { x: 7, y: 2.4 }, approachRadiusMeters: 0.3 }],
      entities: [{ entityId: "door", entityType: "entrance_door", regionId: "living_room", interactionPointId: "p", capabilities: [{ capability: "home_egress", roles: [], supportedOperations: ["leave_home"] }], initialState: {} }],
    };
    expect(planFrontDoor(degenerate, new Set(["living_room"]))?.y1).toBe(3);
    // Nor when the door is in a room the plan is not showing.
    const outsideOnly: HomeModel = {
      ...flat(),
      interactionPoints: [{ interactionPointId: "p", regionId: "hidden", position: { x: 0, y: 0 }, approachRadiusMeters: 0.3 }],
      entities: [{ entityId: "door", entityType: "entrance_door", regionId: "hidden", interactionPointId: "p", capabilities: [{ capability: "home_ingress", roles: [], supportedOperations: ["enter_home"] }], initialState: {} }],
    };
    expect(planFrontDoor(outsideOnly, ids(flat()))).toBeUndefined();
  });

  it("measures the floor area a caption reports", () => {
    expect(polygonArea(flat().regions[0]!.boundary.vertices)).toBe(12);
  });
});
