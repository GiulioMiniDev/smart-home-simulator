import { describe, expect, it } from "vitest";
import {
  addDoorway,
  addFurnitureAt,
  addSensorAt,
  addSensorInRegion,
  addStoreyByStairs,
  alignSensorModel,
  boxOf,
  createRoomFromBox,
  cutDoorways,
  dwellingRegionIds,
  magnet,
  movePlanObject,
  pirRange,
  planDoors,
  planFrontDoor,
  planProblems,
  planWalls,
  polygonArea,
  regionAt,
  removeSelection,
  renameSensor,
  resizePlanObject,
  rotatePlanObject,
  sensorIdFor,
  sensorSlug,
  sensorsByRoom,
  setPirRange,
  setRegionLevel,
  setSensorPosition,
  sharedWallAt,
  snap,
} from "../editor";
import type { HomeModel, Point, SensorBase, SensorModel } from "../types";

/** The area a detector watches, which the contract carries as an open field. */
const coverageOf = (sensor: SensorBase) => boxOf((sensor.coverage as { vertices: Point[] }).vertices);

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
  it("draws a room from the two corners it was dragged between", () => {
    // The room used to arrive as a fixed four-by-four box off the side of the plan, joined to
    // whichever room happened to be traversable first. It is drawn where it goes now.
    const first = createRoomFromBox(home(), { minX: 5.04, minY: 0, maxX: 8, maxY: 3.5 });
    expect(first.selectedId).toBe("room_02");
    expect(boxOf(first.model.regions[1]!.boundary.vertices)).toEqual({ minX: 5, minY: 0, maxX: 8, maxY: 3.5 });
    // Corners in any order, and an upstairs room remembers it is upstairs.
    const upstairs = createRoomFromBox(first.model, { minX: 8, minY: 3.5, maxX: 5, maxY: 0 }, 1);
    expect(upstairs.model.regions[2]!.level).toBe(1);
    expect(boxOf(upstairs.model.regions[2]!.boundary.vertices)).toEqual({ minX: 5, minY: 0, maxX: 8, maxY: 3.5 });
    // A room nothing was dragged out for is a slip, not a room.
    expect(() => createRoomFromBox(home(), { minX: 1, minY: 1, maxX: 1.1, maxY: 1.1 })).toThrow("30 cm");
  });

  it("opens a doorway on the wall two rooms actually share", () => {
    const two = createRoomFromBox(home(), { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model;
    const wall = sharedWallAt(two, { x: 4.1, y: 2 });
    expect(wall).toMatchObject({ regionAId: "room_01", regionBId: "room_02", x: 4, vertical: true });
    const opened = addDoorway(two, wall!);
    const door = opened.model.connections[0]!;
    expect(door).toMatchObject({ kind: "doorway", regionAId: "room_01", regionBId: "room_02" });
    // Each portal sits inside its own room, because navigable space is the room eroded by the body
    // radius and a point on the wall itself is never in it.
    expect(door.portalA!.x).toBeLessThan(4);
    expect(door.portalB!.x).toBeGreaterThan(4);
    expect(Math.hypot(door.portalA!.x - door.portalB!.x, door.portalA!.y - door.portalB!.y))
      .toBeLessThanOrEqual(door.widthMeters);
  });

  it("offers no doorway where there is no party wall, or too little of one", () => {
    const apart = createRoomFromBox(home(), { minX: 6, minY: 0, maxX: 9, maxY: 4 }).model;
    expect(sharedWallAt(apart, { x: 5, y: 2 })).toBeUndefined();
    // Touching, but over half a metre — not enough wall for a door to open in.
    const slither = createRoomFromBox(home(), { minX: 4, minY: 3.5, maxX: 8, maxY: 4 }).model;
    expect(sharedWallAt(slither, { x: 4.05, y: 3.8 })).toBeUndefined();
  });

  it("drops a real piece of furniture, not a nameless box", () => {
    // The tool used to add an untyped 0.8 by 0.8 obstacle: no drawing, and no entity, so nothing
    // in the home could ever be done at it. A piece of furniture is three coupled things.
    const dropped = addFurnitureAt(home(), "wardrobe", { x: 2.5, y: 1.5 });
    expect(dropped.selectedId).toBe("obstacle_wardrobe_01");
    const obstacle = dropped.model.obstacles[0]!;
    expect(obstacle.regionId).toBe("room_01");
    // Sized as a wardrobe is sized, and turned to face the room.
    expect(boxOf(obstacle.boundary.vertices)).toEqual({ minX: 1.9, minY: 1.2, maxX: 3.1, maxY: 1.8 });
    expect(obstacle.orientationDegrees).toBe(90);
    const entity = dropped.model.entities.find((item) => item.entityId === "wardrobe_01")!;
    expect(entity.entityType).toBe("wardrobe");
    expect(entity.capabilities.length).toBeGreaterThan(0);
    expect(entity.capabilities.every((item) => item.supportedOperations.length > 0)).toBe(true);
    // The contract refuses a capability whose roles repeat, and several of the pack's own aliases
    // for a type *are* the type name. The gate caught this one; the test keeps it caught.
    for (const item of entity.capabilities) {
      expect(new Set(item.roles).size).toBe(item.roles.length);
    }
    const point = dropped.model.interactionPoints.find((item) => item.interactionPointId === entity.interactionPointId)!;
    // In front of it, which is where a body stands and which way the drawing faces.
    expect(point.position.y).toBeGreaterThan(boxOf(obstacle.boundary.vertices).maxY);
    expect(point.regionId).toBe("room_01");

    // A second one of the same kind takes the shape of the first: it was built by the generator
    // from this scenario's own behaviour, so it names the operations this home exercises.
    const second = addFurnitureAt(dropped.model, "wardrobe", { x: 1, y: 3 });
    expect(second.selectedId).toBe("obstacle_wardrobe_02");
    expect(second.model.entities.at(-1)!.capabilities).toEqual(entity.capabilities);
    expect(() => addFurnitureAt(home(), "wardrobe", { x: 40, y: 40 })).toThrow("inside a room");
  });

  it("moves a room's own standing point out of the way rather than refusing the furniture", () => {
    // Every room carries an anchor, invisible and usually near the middle, which is exactly where
    // somebody drops a chair. Refusing the chair for it is refusing it for a reason nobody can see.
    const model = home();
    model.interactionPoints.push({
      interactionPointId: "anchor_room_01", regionId: "room_01",
      position: { x: 2, y: 2 }, approachRadiusMeters: 0.25,
    });
    const dropped = addFurnitureAt(model, "table", { x: 2, y: 2 });
    const anchor = dropped.model.interactionPoints.find((item) => item.interactionPointId === "anchor_room_01")!;
    expect(anchor.position).not.toEqual({ x: 2, y: 2 });
    expect(planProblems(dropped.model)).toEqual([]);

  });

  it("drops sensors where they were pointed at, and nowhere else", () => {
    const watching = addSensorAt(sensors(), home(), "pir", { x: 1.4, y: 3.2 });
    expect(watching.model.sensors[0]!.position).toEqual({ x: 1.4, y: 3.2 });
    expect(watching.model.sensors[0]!.regionIds).toEqual(["room_01"]);
    expect(addSensorAt(sensors(), home(), "temperature", { x: 1, y: 1 }).model.sensors[0]!.regionId)
      .toBe("room_01");
    expect(addSensorAt(sensors(), home(), "contact", { x: 1, y: 1 }).model.sensors[0]!.position)
      .toEqual({ x: 1, y: 1 });
    expect(() => addSensorAt(sensors(), home(), "pir", { x: 40, y: 40 })).toThrow("inside a room");
  });

  it("names a hand-placed sensor after what it watches, the way the policy does", () => {
    // The identifier is the whole of a sensor's identity in the exported log: a column called
    // `pir_01` beside the policy's own `pir_kitchen` is a reading nobody can place months later.
    expect(addSensorAt(sensors(), home(), "pir", { x: 2, y: 2 }).selectedId).toBe("pir_room_01");
    expect(addSensorAt(sensors(), home(), "temperature", { x: 2, y: 2 }).selectedId)
      .toBe("temperature_room_01");
    // A contact switch is fitted to a thing, so it is named after the thing.
    expect(addSensorAt(sensors(), home(), "contact", { x: 2, y: 2 }).selectedId).toBe("contact_door");
    const twice = addSensorAt(addSensorAt(sensors(), home(), "pir", { x: 1, y: 1 }).model, home(), "pir", { x: 3, y: 3 });
    expect(twice.selectedId).toBe("pir_room_01_2");
    // The first detector watches the room. The second is there to tell one end of it from the
    // other, so it arrives as a zone rather than as a second copy of the same coverage.
    expect(coverageOf(twice.model.sensors[0]!)).toEqual({ minX: 0, minY: 0, maxX: 4, maxY: 4 });
    expect(coverageOf(twice.model.sensors[1]!)).toEqual({ minX: 1.5, minY: 1.5, maxX: 4, maxY: 4 });
  });

  it("fits a contact switch to the nearest thing in the room that was clicked", () => {
    // It used to be fitted to `home.entities[0]` — the first provider of the whole flat, wherever
    // it happened to be — and the researcher then had to find the fridge again in a dropdown.
    const two: HomeModel = {
      ...home(),
      interactionPoints: [
        ...home().interactionPoints,
        { interactionPointId: "fridge_point", regionId: "room_01", position: { x: 3.5, y: 3.5 }, approachRadiusMeters: 0.5 },
      ],
      entities: [
        ...home().entities,
        { entityId: "refrigerator", entityType: "refrigerator", regionId: "room_01", interactionPointId: "fridge_point", capabilities: [], initialState: { open: false } },
      ],
    };
    const fitted = addSensorAt(sensors(), two, "contact", { x: 3.4, y: 3.4 });
    expect(fitted.model.sensors[0]!.entityId).toBe("refrigerator");
    expect(fitted.selectedId).toBe("contact_refrigerator");
    // A room with nothing in it still takes a switch: it is fitted to the nearest thing anywhere,
    // and a provider whose standing point the model has lost is simply the furthest away.
    const elsewhere: HomeModel = {
      ...createRoomFromBox(two, { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model,
      interactionPoints: two.interactionPoints.filter((item) => item.interactionPointId !== "point"),
    };
    expect(addSensorAt(sensors(), elsewhere, "contact", { x: 6, y: 2 }).selectedId)
      .toBe("contact_refrigerator");
    // An anchor with nothing to slugify leaves the kind of instrument as the whole name.
    expect(sensorIdFor("pir", "—", [])).toBe("pir");
  });

  it("renames a sensor, and refuses a name another one already answers to", () => {
    const field = addSensorAt(sensors(), home(), "pir", { x: 2, y: 2 }).model;
    // Typed the way a person types it; stored the way every other identifier is written.
    expect(renameSensor(field, "pir_room_01", "Kitchen East").sensors[0]!.sensorId)
      .toBe("kitchen_east");
    expect(sensorSlug(" Kitchen East ")).toBe("kitchen_east");
    const both = addSensorAt(field, home(), "temperature", { x: 2, y: 2 }).model;
    expect(() => renameSensor(both, "pir_room_01", "temperature_room_01"))
      .toThrow("already called temperature_room_01");
    expect(() => renameSensor(both, "pir_room_01", "  ")).toThrow("needs a name");
    // Renaming to the name it already has is not a collision with itself.
    expect(renameSensor(both, "pir_room_01", "pir_room_01")).toBe(both);
  });

  it("rebinds a detector dragged into another room, and leaves a doorway one alone", () => {
    const two = createRoomFromBox(home(), { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model;
    const field = addSensorAt(sensors(), two, "pir", { x: 2, y: 2 }).model;
    // Moving one used to move the drawing and nothing else: the node stood in the second room and
    // went on crediting every firing to the first.
    const moved = movePlanObject(two, field, "pir_room_01", 3.5, 0);
    expect(moved.sensors?.sensors[0]!.regionIds).toEqual(["room_02"]);
    expect(coverageOf(moved.sensors!.sensors[0]!).minX).toBeGreaterThanOrEqual(4);
    // A doorway detector names both rooms because straddling the threshold is what it is for.
    const doorway: SensorModel = {
      ...field,
      sensors: [{ ...field.sensors[0]!, sensorId: "pir_hall_door", regionIds: ["room_01", "room_02"] }],
    };
    expect(movePlanObject(two, doorway, "pir_hall_door", 3.5, 0).sensors?.sensors[0]!.regionIds)
      .toEqual(["room_01", "room_02"]);
    // Typing a coordinate is the same gesture as dragging it there.
    const typed = setSensorPosition(field, two, "pir_room_01", { x: 6, y: 2 });
    expect(typed.sensors[0]!.regionIds).toEqual(["room_02"]);
    expect(setSensorPosition(field, two, "pir_room_01", { x: Number.NaN, y: 2 })).toBe(field);
    // Dragged out of the house altogether it keeps the room it had: there is no other answer, and
    // a sensor watching nothing is what the bundle refuses.
    expect(setSensorPosition(field, two, "pir_room_01", { x: 40, y: 40 }).sensors[0]!.regionIds)
      .toEqual(["room_01"]);
  });

  it("carries a thermometer's room with it, and gives up a coverage the drag cut to nothing", () => {
    const two = createRoomFromBox(home(), { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model;
    const warmth = addSensorAt(sensors(), two, "temperature", { x: 2, y: 2 }).model;
    expect(movePlanObject(two, warmth, "temperature_room_01", 3.5, 0).sensors?.sensors[0]!.regionId)
      .toBe("room_02");
    // A detector whose coverage is a sliver at the far edge of the room it left has nothing left to
    // clip, so it watches the room it arrived in rather than a strip of floor by the wall.
    const sliver: SensorModel = {
      ...sensors(),
      sensors: [{
        ...addSensorAt(sensors(), two, "pir", { x: 3.9, y: 2 }).model.sensors[0]!,
        coverage: { vertices: [{ x: 3.8, y: 1.9 }, { x: 4, y: 1.9 }, { x: 4, y: 2.1 }, { x: 3.8, y: 2.1 }] },
      }],
    };
    const arrived = movePlanObject(two, sliver, "pir_room_01", 2.5, 0);
    expect(arrived.sensors?.sensors[0]!.regionIds).toEqual(["room_02"]);
    expect(coverageOf(arrived.sensors!.sensors[0]!)).toEqual({ minX: 4, minY: 0, maxX: 8, maxY: 4 });
  });

  it("lists every room of the dwelling against what watches it, empty ones included", () => {
    const two = createRoomFromBox(home(), { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model;
    const field = addSensorInRegion(sensors(), two, "pir", "room_01");
    expect(field.selectedId).toBe("pir_room_01");
    const rooms = sensorsByRoom(two, field.model);
    expect(rooms.map((item) => item.regionId)).toEqual(["room_01", "room_02"]);
    expect(rooms[0]!.sensors.map((item) => item.sensorId)).toEqual(["pir_room_01"]);
    // The room nothing watches is the one the drawing cannot show, because nothing is drawn there.
    expect(rooms[1]!.sensors).toEqual([]);
    // A contact switch is counted in the room its thing stands in.
    const contact = addSensorAt(field.model, two, "contact", { x: 1, y: 1 }).model;
    expect(sensorsByRoom(two, contact)[0]!.sensors).toHaveLength(2);
    expect(() => addSensorInRegion(sensors(), two, "pir", "nowhere")).toThrow("no room called");
  });

  it("rejects sensor creation without the providers a sensor needs", () => {
    const empty = { ...home(), entities: [] };
    expect(() => addSensorAt(sensors(), empty, "contact", { x: 1, y: 1 })).toThrow("contact sensor requires");
    expect(() => addSensorAt(sensors(), empty, "temperature", { x: 1, y: 1 })).toThrow("temperature sensor requires");
  });

  it("adds a storey only as the far end of a staircase, beside the plan rather than on top of it", () => {
    // A floor used to arrive on its own and the plan gate then refused the home for having a room
    // nothing reached. The flight is what the user builds; the storey comes with it.
    const added = addStoreyByStairs(home(), "room_01", "up");
    expect(added.level).toBe(1);
    const landing = added.model.regions.find((item) => item.regionId === added.selectedId)!;
    expect(landing.level).toBe(1);
    // Beside: two floors are two blocks of one coordinate plane, which is what keeps regions from
    // overlapping and every geometric rule in the model working unchanged.
    expect(boxOf(landing.boundary.vertices).minX).toBeGreaterThan(4);
    const stairs = added.model.connections.find((item) => item.kind === "stairway")!;
    expect(stairs).toMatchObject({ regionAId: "room_01", regionBId: landing.regionId, bidirectional: true });
    // Real treads at both ends, standing on real floor, which the furniture has to work round.
    expect(added.model.obstacles.filter((item) => item.obstacleId.includes("stairs"))).toHaveLength(2);
    const moved = setRegionLevel(added.model, "room_01", 1);
    expect(moved.regions[0]!.level).toBe(1);
    expect(regionAt(moved, { x: 2, y: 2 }, 1)).toBe("room_01");
    expect(regionAt(moved, { x: 2, y: 2 }, 0)).toBeUndefined();
  });

  it("digs a basement when the flight goes down, and refuses a second floor on the same side", () => {
    const dug = addStoreyByStairs(home(), "room_01", "down");
    expect(dug.level).toBe(-1);
    expect(dug.model.regions.find((item) => item.regionId === dug.selectedId)!.level).toBe(-1);
    // The climb is declared, not measured: the two ends sit metres apart in coordinates that say
    // nothing about how far up or down they are.
    expect(dug.model.connections[0]!.distanceMeters).toBe(4.5);
    expect(dug.model.connections[0]!.regionAId).toBe(dug.selectedId);
    expect(() => addStoreyByStairs(dug.model, "room_01", "down")).toThrow("already a floor below");
    expect(() => addStoreyByStairs(home(), "nowhere", "up")).toThrow("starts in a room");
    const outdoors = { ...home(), regions: [{ ...home().regions[0]!, traversable: false }] };
    expect(() => addStoreyByStairs(outdoors, "room_01", "up")).toThrow("a body can stand");
    // A cupboard is not the foot of a staircase, and the refusal costs nothing: the landing is
    // built into a copy that never leaves the call.
    const cupboard = {
      ...home(),
      regions: [{ ...home().regions[0]!, boundary: { vertices: [{ x: 0, y: 0 }, { x: 1.2, y: 0 }, { x: 1.2, y: 1.2 }, { x: 0, y: 1.2 }] } }],
      interactionPoints: [], entities: [],
    };
    expect(() => addStoreyByStairs(cupboard, "room_01", "up")).toThrow("room for a flight of stairs");
  });

  it("removes regions, providers and sensors with their dependent objects", () => {
    const withSensor = addSensorAt(sensors(), home(), "pir", { x: 2, y: 2 }).model;
    const noSensor = removeSelection(home(), withSensor, "pir_room_01");
    expect(noSensor.sensors?.sensors).toHaveLength(0);
    const noEntity = removeSelection(home(), withSensor, "door");
    expect(noEntity.home.entities).toHaveLength(0);
    expect(noEntity.home.interactionPoints).toHaveLength(0);
    const noRoom = removeSelection(home(), withSensor, "room_01");
    expect(noRoom.home.regions).toHaveLength(0);
    expect(noRoom.home.obstacles).toHaveLength(0);
    // The PIR watched that room and nothing else. An instrument reporting on a room nobody can
    // enter is not a record to keep tidy, it is a sensor the bundle will refuse later.
    expect(noRoom.sensors?.sensors).toHaveLength(0);
    expect(removeSelection(home(), undefined, "missing").sensors).toBeUndefined();
  });

  it("takes a piece of furniture away whole, whichever of its three parts was selected", () => {
    // The footprint, the provider and the spot the body stands on are one wardrobe. Deleting used
    // to work on whichever one the click landed on: by its box it left the use point behind, by
    // its provider it left the box blocking the floor, and the gate had nothing to say to either.
    const dropped = addFurnitureAt(home(), "wardrobe", { x: 2, y: 2 });
    expect(dropped.selectedId).toBe("obstacle_wardrobe_01");
    for (const handle of ["obstacle_wardrobe_01", "wardrobe_01"]) {
      const gone = removeSelection(dropped.model, undefined, handle).home;
      expect(gone.obstacles.map((item) => item.obstacleId)).not.toContain("obstacle_wardrobe_01");
      expect(gone.entities.map((item) => item.entityId)).not.toContain("wardrobe_01");
      expect(gone.interactionPoints.map((item) => item.interactionPointId)).not.toContain("point_wardrobe_01");
      // And nothing else goes with it: the room's own door is not part of the wardrobe.
      expect(gone.entities.map((item) => item.entityId)).toContain("door");
    }
  });

  it("takes a staircase away whole: both flights and the climb between them", () => {
    const added = addStoreyByStairs(home(), "room_01", "up");
    const stairs = added.model.connections.find((item) => item.kind === "stairway")!;
    const treads = added.model.obstacles.filter((item) => item.obstacleId.startsWith(`obstacle_${stairs.connectionId}_`));
    // Named after the flight they belong to, as the generator names its own: the treads are the
    // one kind of obstacle with no entity to own them.
    expect(treads).toHaveLength(2);
    for (const handle of [stairs.connectionId, treads[0]!.obstacleId, treads[1]!.obstacleId]) {
      const gone = removeSelection(added.model, undefined, handle).home;
      expect(gone.connections.filter((item) => item.kind === "stairway")).toHaveLength(0);
      expect(gone.obstacles).toHaveLength(0);
      // The storey itself stays. Pulling the stairs down does not demolish the floor above.
      expect(gone.regions).toHaveLength(2);
    }
    // And removing the storey takes the flight standing in the room below with it, rather than
    // leaving treads climbing to nowhere.
    const noUpstairs = removeSelection(added.model, undefined, added.selectedId).home;
    expect(noUpstairs.obstacles).toHaveLength(0);
    expect(noUpstairs.connections).toHaveLength(0);
  });

  it("keeps the sensor field's register of the home in step with the home", () => {
    // The sensor model carries its own list of the rooms and devices it was deployed against, and
    // the bundle demands the two match exactly. Drawing a room used to leave the list behind, and
    // publishing did not catch it: the server only looked for rooms the field names and the house
    // does not. The pair drifted in silence and the run refused it hours later.
    const field = sensors();
    expect(alignSensorModel(field, home())).toBe(field);

    const drawn = createRoomFromBox(home(), { minX: 5, minY: 0, maxX: 8, maxY: 3 }).model;
    expect(alignSensorModel(field, drawn).regionIds).toEqual(["room_01", "room_02"]);

    const furnished = addFurnitureAt(home(), "wardrobe", { x: 2, y: 2 }).model;
    expect(alignSensorModel(field, furnished).entityIds).toEqual(["door", "wardrobe_01"]);

    // A storey arrives with its landing, and the register gains it in the same breath.
    const upstairs = addStoreyByStairs(home(), "room_01", "up").model;
    expect(alignSensorModel(field, upstairs).regionIds).toEqual(["room_01", "landing_01"]);

    // And it shrinks again: a room deleted is a room the field must stop claiming, or publishing
    // refuses the model for naming a region the home has not got.
    const razed = removeSelection(furnished, field, "wardrobe_01").home;
    expect(alignSensorModel(field, razed).entityIds).toEqual(["door"]);
  });

  it("removes a doorway that is selected the moment it is placed", () => {
    // `addDoorway` hands back the connection as the selection, so Delete straight after placing one
    // aimed at an id that removal did not recognise and quietly did nothing at all.
    const two = createRoomFromBox(home(), { minX: 4, minY: 0, maxX: 8, maxY: 4 }).model;
    const opened = addDoorway(two, sharedWallAt(two, { x: 4.1, y: 2 })!);
    expect(opened.model.connections).toHaveLength(1);
    const gone = removeSelection(opened.model, undefined, opened.selectedId).home;
    expect(gone.connections).toHaveLength(0);
    expect(gone.regions).toHaveLength(2);
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

/** A four-by-four room holding a wardrobe against its left wall, and the spot you stand at to use it. */
const furnished = (): HomeModel => ({
  ...home(),
  obstacles: [{
    obstacleId: "obstacle_wardrobe",
    regionId: "room_01",
    orientationDegrees: 0,
    boundary: { vertices: [{ x: 0, y: 1 }, { x: 0.6, y: 1 }, { x: 0.6, y: 2.2 }, { x: 0, y: 2.2 }] },
  }],
  interactionPoints: [{ interactionPointId: "point", regionId: "room_01", position: { x: 1, y: 1.6 }, approachRadiusMeters: 0.5 }],
  entities: [{ entityId: "wardrobe", entityType: "wardrobe", regionId: "room_01", interactionPointId: "point", capabilities: [], initialState: {} }],
});

describe("turning a piece of furniture", () => {
  it("transposes the footprint, advances the bearing and carries the use point round", () => {
    // Moving and resizing were the only verbs the plan had, so a wardrobe generated against the
    // wrong wall could be stretched into the other proportion but never faced round.
    const turned = rotatePlanObject(furnished(), "obstacle_wardrobe");
    const box = boxOf(turned.obstacles[0]!.boundary.vertices);
    expect(box.maxX - box.minX).toBeCloseTo(1.2, 5);
    expect(box.maxY - box.minY).toBeCloseTo(0.6, 5);
    expect(turned.obstacles[0]!.orientationDegrees).toBe(90);
    // A quarter turn clockwise about the centre (0.3, 1.6) puts the point below the piece, and the
    // slide that keeps the piece inside the room carries it along.
    expect(turned.interactionPoints[0]!.position).toEqual({ x: 0.6, y: 2.3 });
  });

  it("slides a piece that its own turn pushed through a wall back into the room", () => {
    const turned = rotatePlanObject(furnished(), "obstacle_wardrobe");
    const box = boxOf(turned.obstacles[0]!.boundary.vertices);
    expect(box.minX).toBeGreaterThanOrEqual(0);
    expect(box.maxX).toBeLessThanOrEqual(4);
  });

  it("is reached by the entity as well as by its footprint, and four turns is where it started", () => {
    // Away from the walls, where nothing has to be slid back in, turning is its own inverse.
    const start = furnished();
    start.obstacles[0]!.boundary.vertices = [
      { x: 1.7, y: 1.4 }, { x: 2.3, y: 1.4 }, { x: 2.3, y: 2.6 }, { x: 1.7, y: 2.6 },
    ];
    const once = rotatePlanObject(start, "wardrobe");
    expect(once.obstacles[0]!.orientationDegrees).toBe(90);
    const full = [1, 2, 3, 4].reduce((model) => rotatePlanObject(model, "wardrobe"), start);
    expect(full.obstacles[0]!.orientationDegrees).toBe(0);
    expect(boxOf(full.obstacles[0]!.boundary.vertices)).toEqual(boxOf(start.obstacles[0]!.boundary.vertices));
  });

  it("leaves alone anything that is not furniture", () => {
    const model = furnished();
    expect(rotatePlanObject(model, "room_01")).toBe(model);
    expect(rotatePlanObject(model, "obstacle_wardrobe", 0)).toBe(model);
  });
});

describe("the magnet", () => {
  it("lines an edge up with the wall it was dropped near", () => {
    // 0.6 wide and standing at x = 1.0: dragged 0.9 to the left it lands at 0.1, which is four
    // centimetres of nothing between it and the wall. It should land on the wall.
    const model = furnished();
    model.obstacles[0]!.boundary.vertices = [
      { x: 1, y: 1 }, { x: 1.6, y: 1 }, { x: 1.6, y: 2.2 }, { x: 1, y: 2.2 },
    ];
    expect(magnet(model, "obstacle_wardrobe", -0.9, 0).dx).toBeCloseTo(-1, 5);
  });

  it("lines an edge up with a neighbour in the same room", () => {
    const model = furnished();
    model.obstacles.push({
      obstacleId: "obstacle_desk",
      regionId: "room_01",
      boundary: { vertices: [{ x: 2, y: 3 }, { x: 3, y: 3 }, { x: 3, y: 3.6 }, { x: 2, y: 3.6 }] },
    });
    // The wardrobe's left edge is at 0; nudged to 1.94 it should snap onto the desk's 2.
    expect(magnet(model, "obstacle_wardrobe", 1.94, 0).dx).toBeCloseTo(2, 5);
  });

  it("leaves a drag alone when there is nothing to line it up with", () => {
    expect(magnet(furnished(), "obstacle_wardrobe", 1.5, 1.5)).toEqual({ dx: 1.5, dy: 1.5 });
    expect(magnet(furnished(), "nothing_here", 0.3, 0)).toEqual({ dx: 0.3, dy: 0 });
  });
});

describe("what the gate would refuse, said now", () => {
  it("names a piece that has been pushed out of its room", () => {
    const model = furnished();
    model.obstacles[0]!.boundary.vertices = [
      { x: -0.5, y: 1 }, { x: 0.1, y: 1 }, { x: 0.1, y: 2.2 }, { x: -0.5, y: 2.2 },
    ];
    expect(planProblems(model)).toEqual([
      { objectId: "obstacle_wardrobe", message: "sticks out of room 01" },
    ]);
  });

  it("names both sides of an overlap, once each", () => {
    const model = furnished();
    model.obstacles.push({
      obstacleId: "obstacle_desk",
      regionId: "room_01",
      boundary: { vertices: [{ x: 0.4, y: 1.4 }, { x: 1.4, y: 1.4 }, { x: 1.4, y: 2 }, { x: 0.4, y: 2 }] },
    });
    const problems = planProblems(model);
    expect(problems.map((item) => item.objectId).sort()).toEqual(["obstacle_desk", "obstacle_wardrobe"]);
    expect(problems.every((item) => item.message.startsWith("overlaps"))).toBe(true);
  });

  it("names a piece standing in a doorway", () => {
    const model = furnished();
    model.connections = [{
      connectionId: "door", regionAId: "room_01", regionBId: "room_02", kind: "doorway",
      bidirectional: true, widthMeters: 1, portalA: { x: 0.3, y: 1.5 },
    }];
    expect(planProblems(model)[0]).toEqual({
      objectId: "obstacle_wardrobe", message: "stands in a doorway",
    });
  });

  it("names the piece that is standing on somewhere a body has to be", () => {
    const model = furnished();
    model.obstacles.push({
      obstacleId: "obstacle_sofa",
      regionId: "room_01",
      boundary: { vertices: [{ x: 0.8, y: 1.4 }, { x: 1.8, y: 1.4 }, { x: 1.8, y: 2 }, { x: 0.8, y: 2 }] },
    });
    // The sofa is the thing at fault, not the wardrobe it made unreachable: the sofa is what you
    // just moved and what has to move again.
    expect(planProblems(model).find((item) => item.objectId === "obstacle_sofa")?.message)
      .toContain("stands on to use wardrobe");
  });

  it("names a piece dropped on a room's own anchor, which belongs to no furniture at all", () => {
    // The two nobody thinks about: the anchor every room has and the per-region service point.
    // Dropping a bath in the middle of a sitting room lands on both, and until this was checked
    // here the only thing that said so was the gate, after the publish it rejected.
    const model = furnished();
    model.interactionPoints.push({
      interactionPointId: "anchor_room_01", regionId: "room_01",
      position: { x: 2.4, y: 2.3 }, approachRadiusMeters: 0.25,
    });
    // Clear of the wardrobe's own standing point, so the anchor is the only thing at stake.
    model.obstacles.push({
      obstacleId: "obstacle_bathtub",
      regionId: "room_01",
      boundary: { vertices: [{ x: 1.6, y: 2 }, { x: 3.3, y: 2 }, { x: 3.3, y: 2.75 }, { x: 1.6, y: 2.75 }] },
    });
    expect(planProblems(model).find((item) => item.objectId === "obstacle_bathtub")?.message)
      .toContain("anchor room 01");
  });

  it("says nothing about a plan that is fine", () => {
    expect(planProblems(furnished())).toEqual([]);
  });
});
