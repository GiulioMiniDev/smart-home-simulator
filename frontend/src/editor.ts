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
