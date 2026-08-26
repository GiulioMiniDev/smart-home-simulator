import { describe, expect, it } from "vitest";
import { scenePlace } from "../replay/replay-place";
import type { HomeModel } from "../types";

const home = {
  regions: [
    { regionId: "kitchen", kind: "room", boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } },
    { regionId: "balcony", kind: "outdoor", boundary: { vertices: [{ x: 4, y: 0 }, { x: 6, y: 0 }, { x: 6, y: 2 }, { x: 4, y: 2 }] } },
    { regionId: "office", kind: "external", boundary: { vertices: [{ x: 0, y: 20 }, { x: 4, y: 20 }, { x: 4, y: 24 }, { x: 0, y: 24 }] } },
  ],
  connections: [
    { connectionId: "door_balcony", regionAId: "kitchen", regionBId: "balcony", kind: "doorway" },
    { connectionId: "transit_office", regionAId: "kitchen", regionBId: "office", kind: "transit" },
  ],
  obstacles: [],
  interactionPoints: [
    { interactionPointId: "point_stove", regionId: "kitchen", position: { x: 1, y: 1 } },
    { interactionPointId: "point_anchor", regionId: "kitchen", position: { x: 2, y: 2 } },
    { interactionPointId: "point_door", regionId: "kitchen", position: { x: 2, y: 2 } },
    { interactionPointId: "point_service", regionId: "kitchen", position: { x: 3, y: 3 } },
    { interactionPointId: "point_sink", regionId: "kitchen", position: { x: 3, y: 3 } },
  ],
  entities: [
    { entityId: "stove_main", entityType: "stove", interactionPointId: "point_stove" },
    { entityId: "entrance_door", entityType: "entrance_door", interactionPointId: "point_door" },
    { entityId: "service_kitchen", entityType: "generated_environment_service", interactionPointId: "point_service" },
    { entityId: "kitchen_sink", entityType: "sink", interactionPointId: "point_sink" },
  ],
} as unknown as HomeModel;

describe("scenePlace", () => {
  const place = scenePlace(home);

  it("counts the rooms and whatever a door reaches as the flat, and nothing a transit reaches", () => {
    // A balcony behind a door is as much the flat as the kitchen; an office twenty metres away
    // is somewhere the plan does not draw.
    expect(place.inside("kitchen")).toBe(true);
    expect(place.inside("balcony")).toBe(true);
    expect(place.inside("office")).toBe(false);
    expect(place.inside(undefined)).toBe(false);
    expect(place.inside(null)).toBe(false);
  });

  it("names the thing at a position exactly one entity claims", () => {
    expect(place.thingAt({ x: 1, y: 1 })).toEqual({ entityId: "stove_main", label: "stove" });
    // A service point shares this spot, and it is not a thing anybody uses by standing on it.
    expect(place.thingAt({ x: 3, y: 3 })).toEqual({ entityId: "kitchen_sink", label: "sink" });
  });

  it("stays quiet on the room's own anchor, which every route into the room ends on", () => {
    expect(place.thingAt({ x: 2, y: 2 })).toBeUndefined();
    expect(place.thingAt({ x: 9, y: 9 })).toBeUndefined();
    expect(place.thingAt(undefined)).toBeUndefined();
  });

  it("answers safely for a run whose home never arrived", () => {
    const nowhere = scenePlace(undefined);
    expect(nowhere.inside("kitchen")).toBe(false);
    expect(nowhere.thingAt({ x: 1, y: 1 })).toBeUndefined();
  });
});
