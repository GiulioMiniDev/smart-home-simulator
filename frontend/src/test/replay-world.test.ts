import { describe, expect, it } from "vitest";
import { movementPositionAt, replayTimestamp } from "../replay/replay-positioning";
import { scenePlace } from "../replay/replay-place";
import { buildScript } from "../replay/replay-script";
import { foldWorld } from "../replay/replay-world";
import { sceneMotion } from "../replay/scene-motion";
import type { HomeModel, ReplayEvent, ReplayEventWindow, ReplayFrame } from "../types";

const home = {
  regions: [
    { regionId: "hallway", kind: "room", boundary: { vertices: [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 2, y: 2 }, { x: 0, y: 2 }] } },
    { regionId: "kitchen", kind: "room", boundary: { vertices: [{ x: 2, y: 0 }, { x: 6, y: 0 }, { x: 6, y: 2 }, { x: 2, y: 2 }] } },
    { regionId: "outdoors", kind: "external", boundary: { vertices: [{ x: 0, y: 20 }, { x: 4, y: 20 }, { x: 4, y: 24 }, { x: 0, y: 24 }] } },
  ],
  connections: [],
  obstacles: [],
  interactionPoints: [
    { interactionPointId: "point_chair", regionId: "kitchen", position: { x: 4, y: 0 } },
    { interactionPointId: "point_anchor", regionId: "kitchen", position: { x: 3, y: 1 } },
    { interactionPointId: "point_service", regionId: "kitchen", position: { x: 3, y: 1 } },
  ],
  entities: [
    { entityId: "refrigerator", entityType: "refrigerator" },
    { entityId: "television", entityType: "television" },
    { entityId: "chair_kitchen", entityType: "chair", interactionPointId: "point_chair" },
    { entityId: "service_kitchen", entityType: "generated_environment_service", interactionPointId: "point_service" },
  ],
} as unknown as HomeModel;

const place = scenePlace(home);

const walk: ReplayEvent = {
  at: "2026-10-30T07:42:00+01:00", end: "2026-10-30T07:42:40+01:00",
  kind: "movement", eventId: "walk", label: "", actorId: "resident_mario_rossi", details: {},
  waypoints: [
    { at: "2026-10-30T07:42:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 0, y: 0 } },
    { at: "2026-10-30T07:42:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 4, y: 0 } },
  ],
};

const events: ReplayEventWindow = {
  total: 5,
  traceStart: "2026-10-30T00:00:00+01:00", traceEnd: "2026-10-31T00:00:00+01:00",
  windowStart: "2026-10-30T00:00:00+01:00", windowEnd: "2026-10-31T00:00:00+01:00",
  items: [
    walk,
    { at: "2026-10-30T07:43:00+01:00", kind: "state_transition", eventId: "fridge-open", label: "entity.open", waypoints: [], details: { value: true, subjectId: "refrigerator" } },
    { at: "2026-10-30T07:44:00+01:00", kind: "state_transition", eventId: "fridge-shut", label: "entity.open", waypoints: [], details: { value: false, subjectId: "refrigerator" } },
    { at: "2026-10-30T07:45:00+01:00", kind: "state_transition", eventId: "carry", label: "resident.carrying.ingredients", actorId: "resident_mario_rossi", waypoints: [], details: { value: true } },
    { at: "2026-10-30T07:46:00+01:00", kind: "state_transition", eventId: "sit", label: "resident.posture", actorId: "resident_mario_rossi", waypoints: [], details: { value: "sitting" } },
  ],
};

const frame: ReplayFrame = {
  runId: "run", at: "2026-10-30T00:00:00+01:00",
  traceStart: "2026-10-30T00:00:00+01:00", traceEnd: "2026-10-31T00:00:00+01:00",
  residents: [{
    residentId: "resident_mario_rossi", regionId: "hallway", position: { x: 0, y: 0 },
    posture: "standing", executionState: "idle", heldResourceIds: [],
    facts: { "carrying.drinking_glass": true, "carrying.ingredients": false, awake: true },
  }],
  sensorStates: [],
  entityStates: { refrigerator: { open: false, active: false }, television: { open: false, active: true } },
  environmentFacts: {}, resourceAvailableUnits: {},
};

const script = buildScript(events, home);
const at = (iso: string) => Date.parse(iso);

describe("foldWorld", () => {
  it("carries the frame forward with the day's own state changes", () => {
    const before = foldWorld(script, frame, at("2026-10-30T07:43:30+01:00"), place);
    const after = foldWorld(script, frame, at("2026-10-30T07:47:00+01:00"), place);

    expect(before.entities.refrigerator).toEqual({ open: true, active: false });
    expect(after.entities.refrigerator).toEqual({ open: false, active: false });
    // Nothing in the day touches the television, so it keeps what the frame said about it.
    expect(after.entities.television).toEqual({ open: false, active: true });
    expect(after.residents[0]?.posture).toBe("sitting");
    expect(after.residents[0]?.carrying.sort()).toEqual(["drinking_glass", "ingredients"]);
  });

  it("never folds in a change the clock has not reached", () => {
    const early = foldWorld(script, frame, at("2026-10-30T07:00:00+01:00"), place);

    expect(early.entities.refrigerator).toEqual({ open: false, active: false });
    expect(early.residents[0]?.posture).toBe("standing");
    expect(early.residents[0]?.carrying).toEqual(["drinking_glass"]);
  });

  it("walks the resident along the trace's own waypoints between rooms", () => {
    const half = foldWorld(script, frame, at("2026-10-30T07:42:20+01:00"), place).residents[0];
    const arrived = foldWorld(script, frame, at("2026-10-30T07:43:30+01:00"), place).residents[0];

    expect(half?.position).toEqual({ x: 2, y: 0 });
    expect(half?.moving).toBe(true);
    expect(half?.regionId).toBe("hallway");
    expect(arrived?.moving).toBe(false);
    expect(arrived?.position).toEqual({ x: 4, y: 0 });
    expect(arrived?.regionId).toBe("kitchen");
  });

  it("gives a walker a heading and a standing resident none", () => {
    expect(foldWorld(script, frame, at("2026-10-30T07:42:20+01:00"), place).residents[0]?.heading).toBeCloseTo(0);
    expect(foldWorld(script, frame, at("2026-10-30T07:50:00+01:00"), place).residents[0]?.heading).toBeUndefined();
  });

  it("stops the walk at the door when the route leaves the flat", () => {
    // The trace records one leg from the living room to a place twenty metres south, because
    // that is where it puts the office. Drawn as a line it crosses the kitchen and a wall.
    const leaving = buildScript({
      ...events,
      items: [{
        ...walk, eventId: "leaving",
        at: "2026-10-30T08:15:00+01:00", end: "2026-10-30T08:16:00+01:00",
        waypoints: [
          { at: "2026-10-30T08:15:00+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 5, y: 1 } },
          { at: "2026-10-30T08:15:20+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 1, y: 1 } },
          { at: "2026-10-30T08:16:00+01:00", regionId: "outdoors", traversalMode: "walking", position: { x: 3, y: 22 } },
        ],
      }],
    }, home);
    const outside = { ...frame, residents: [{ ...frame.residents[0]!, regionId: "outdoors", position: { x: 3, y: 22 } }] };

    const halfway = foldWorld(leaving, outside, at("2026-10-30T08:15:10+01:00"), place).residents[0];
    const gone = foldWorld(leaving, outside, at("2026-10-30T08:30:00+01:00"), place).residents[0];

    expect(halfway?.position).toEqual({ x: 3, y: 1 });
    expect(halfway?.away).toBe(false);
    // Past the last waypoint inside the flat there is nothing honest left to draw.
    expect(gone?.away).toBe(true);
    expect(gone?.position).toBeUndefined();
    expect(gone?.moving).toBe(false);
  });

  it("reads where somebody is from the step they are on, not from the day's anchor", () => {
    // A resident out at midnight is out in the anchor frame all day long: the trace's own
    // waypoints are the only thing that says when they came back in.
    const cameHome = buildScript({
      ...events,
      items: [{
        ...walk, eventId: "home",
        at: "2027-04-02T01:00:00+01:00", end: "2027-04-02T01:01:00+01:00",
        waypoints: [
          { at: "2027-04-02T01:00:00+01:00", regionId: "outdoors", traversalMode: "walking", position: { x: 3, y: 22 } },
          { at: "2027-04-02T01:01:00+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 4, y: 1 } },
        ],
      }],
    }, home);
    const outAtMidnight = {
      ...frame, at: "2027-04-02T00:00:00+01:00",
      traceStart: "2027-04-02T00:00:00+01:00", traceEnd: "2027-04-03T00:00:00+01:00",
      residents: [{ ...frame.residents[0]!, regionId: "outdoors", position: { x: 3, y: 22 } }],
    };

    const stillOut = foldWorld(cameHome, outAtMidnight, at("2027-04-02T00:30:00+01:00"), place).residents[0];
    const indoors = foldWorld(cameHome, outAtMidnight, at("2027-04-02T09:00:00+01:00"), place).residents[0];

    expect(stillOut?.away).toBe(true);
    expect(indoors?.away).toBe(false);
    expect(indoors?.regionId).toBe("kitchen");
    expect(indoors?.position).toEqual({ x: 4, y: 1 });
  });

  it("says nothing is drawable for somebody the frame puts outside the flat", () => {
    const atWork = foldWorld(buildScript({ ...events, items: [] }, home), {
      ...frame,
      residents: [{ ...frame.residents[0]!, regionId: "outdoors", position: { x: 3, y: 22 } }],
    }, at("2026-10-30T12:00:00+01:00"), place).residents[0];

    expect(atWork?.away).toBe(true);
    expect(atWork?.position).toBeUndefined();
    expect(atWork?.regionId).toBe("outdoors");
  });

  it("names the thing somebody is standing at, and stays quiet on a shared room anchor", () => {
    const still = buildScript({ ...events, items: [] }, home);
    const onTheChair = foldWorld(still, {
      ...frame, residents: [{ ...frame.residents[0]!, regionId: "kitchen", position: { x: 4, y: 0 } }],
    }, at("2026-10-30T12:00:00+01:00"), place).residents[0];
    // Three points share the room's anchor, so standing on it names none of them.
    const onTheAnchor = foldWorld(still, {
      ...frame, residents: [{ ...frame.residents[0]!, regionId: "kitchen", position: { x: 3, y: 1 } }],
    }, at("2026-10-30T12:00:00+01:00"), place).residents[0];

    expect(onTheChair?.using).toEqual({ entityId: "chair_kitchen", label: "chair" });
    expect(onTheAnchor?.using).toBeUndefined();
  });

  it("ignores a change the anchor has already accounted for", () => {
    // The frame is authoritative for everything up to its own instant, so replaying a
    // transition from before it would apply the same change twice.
    const later = { ...frame, at: "2026-10-30T07:44:30+01:00", entityStates: { refrigerator: { open: true, active: false } } };

    expect(foldWorld(script, later, at("2026-10-30T07:45:30+01:00"), place).entities.refrigerator)
      .toEqual({ open: true, active: false });
  });

  it("takes on a thing the frame never mentioned, and switches it on and off", () => {
    const lamp = buildScript({
      ...events,
      items: [
        { at: "2026-10-30T07:43:00+01:00", kind: "state_transition", eventId: "on", label: "entity.active", waypoints: [], details: { value: true, subjectId: "lamp" } },
        { at: "2026-10-30T07:44:00+01:00", kind: "state_transition", eventId: "off", label: "entity.active", waypoints: [], details: { value: false, subjectId: "lamp" } },
      ],
    }, home);

    expect(foldWorld(lamp, frame, at("2026-10-30T07:43:30+01:00"), place).entities.lamp).toEqual({ open: false, active: true });
    expect(foldWorld(lamp, frame, at("2026-10-30T07:45:00+01:00"), place).entities.lamp).toEqual({ open: false, active: false });
  });

  it("names an unnamed resident rather than losing them", () => {
    const anonymous = foldWorld(script, {
      ...frame,
      residents: [{ ...frame.residents[0]!, residentId: undefined, posture: null }],
    }, at("2026-10-30T07:50:00+01:00"), place);

    expect(anonymous.residents[0]?.residentId).toBe("resident");
    expect(anonymous.residents[0]?.posture).toBe("standing");
  });

  it("draws nobody without a frame, but still believes what the day said about the objects", () => {
    const empty = foldWorld(script, undefined, at("2026-10-30T07:50:00+01:00"), place);

    // Only the frame knows who is in the flat; the day's own transitions still say the fridge
    // was opened and shut again, and there is no reason to disbelieve them.
    expect(empty.residents).toEqual([]);
    expect(empty.entities.refrigerator).toEqual({ open: false, active: false });
    expect(empty.entities.television).toBeUndefined();
  });
});

describe("sceneMotion", () => {
  const world = foldWorld(script, frame, at("2026-10-30T07:42:20+01:00"), place);
  const motion = sceneMotion(world, replayTimestamp(frame.at), () => () => undefined, place);

  it("samples a pose from one route rather than from the whole day", () => {
    const early = motion.sample(at("2026-10-30T07:42:10+01:00")).resident_mario_rossi;
    const late = motion.sample(at("2026-10-30T07:42:30+01:00")).resident_mario_rossi;

    expect(early?.position).toEqual(movementPositionAt(walk, at("2026-10-30T07:42:10+01:00")));
    expect(late?.position).toEqual({ x: 3, y: 0 });
    expect(late?.travelled.at(-1)).toEqual({ x: 3, y: 0 });
    expect(late?.heading).toBeCloseTo(0);
  });

  it("stops drawing a path once the walk is over", () => {
    const settled = motion.sample(at("2026-10-30T07:44:00+01:00")).resident_mario_rossi;

    expect(settled?.position).toEqual({ x: 4, y: 0 });
    expect(settled?.travelled).toEqual([]);
    expect(settled?.heading).toBeUndefined();
  });

  it("gives no heading to a step that goes nowhere", () => {
    const still = buildScript({
      ...events,
      items: [{
        ...walk, eventId: "still",
        waypoints: [
          { at: "2026-10-30T07:42:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 1, y: 1 } },
          { at: "2026-10-30T07:42:20+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 1, y: 1 } },
          { at: "2026-10-30T07:42:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 4, y: 0 } },
        ],
      }],
    }, home);
    const world = foldWorld(still, frame, at("2026-10-30T07:42:10+01:00"), place);

    expect(sceneMotion(world, replayTimestamp(frame.at), () => () => undefined, place)
      .sample(at("2026-10-30T07:42:10+01:00")).resident_mario_rossi?.heading).toBeUndefined();
  });

  it("keeps the frame's position when a route yields none of its own", () => {
    const unusable = buildScript({
      ...events,
      items: [{ ...walk, eventId: "unusable", waypoints: [] }],
    }, home);
    const world = foldWorld(unusable, frame, at("2026-10-30T07:42:20+01:00"), place);

    expect(sceneMotion(world, replayTimestamp(frame.at), () => () => undefined, place)
      .sample(at("2026-10-30T07:42:20+01:00")).resident_mario_rossi)
      .toEqual({ position: { x: 0, y: 0 }, travelled: [], climbing: 0, level: 0 });
  });

  it("leaves someone the frame gives no position exactly where the frame left them", () => {
    const placeless = foldWorld(script, {
      ...frame,
      residents: [{ ...frame.residents[0]!, position: null }],
    }, at("2026-10-30T07:42:20+01:00"), place);
    const sampled = sceneMotion(placeless, replayTimestamp(frame.at), () => () => undefined, place)
      .sample(at("2026-10-30T07:42:20+01:00")).resident_mario_rossi;

    expect(sampled?.position).toBeUndefined();
    expect(sampled?.travelled).toEqual([]);
  });
});
