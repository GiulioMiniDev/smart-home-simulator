import { describe, expect, it } from "vitest";
import { addObstacle, addRoom, addSensor, removeSelection } from "../editor";
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
