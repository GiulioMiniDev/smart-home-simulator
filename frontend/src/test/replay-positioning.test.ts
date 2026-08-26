import { describe, expect, it } from "vitest";
import {
  currentRoute,
  interiorRoute,
  interiorRun,
  isUsableRoute,
  movementAt,
  movementEnd,
  movementPath,
  movementPositionAt,
  movementProgress,
  replayTimestamp,
  routeAt,
  waypointAtOrBefore,
} from "../replay/replay-positioning";
import type { ReplayEvent } from "../types";

function route(part: Partial<ReplayEvent> & Pick<ReplayEvent, "eventId">): ReplayEvent {
  return {
    at: "2026-10-30T08:00:00+01:00", end: "2026-10-30T08:00:40+01:00",
    kind: "movement", label: "", details: {},
    waypoints: [
      { at: "2026-10-30T08:00:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 0, y: 0 } },
      { at: "2026-10-30T08:00:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 4, y: 0 } },
    ],
    ...part,
  };
}

const walk = route({ eventId: "walk" });
const at = (iso: string) => Date.parse(iso);

describe("replayTimestamp", () => {
  it("keeps the microseconds a trace records, which Date.parse alone would drop", () => {
    expect(replayTimestamp("2026-10-30T12:40:00.734427+01:00"))
      .toBe(Date.parse("2026-10-30T12:40:00.734+01:00") + .427);
    expect(replayTimestamp("2026-10-30T12:40:00.734+01:00")).toBe(Date.parse("2026-10-30T12:40:00.734+01:00"));
    expect(replayTimestamp("2026-10-30T12:40:00Z")).toBe(Date.parse("2026-10-30T12:40:00Z"));
    expect(replayTimestamp("not a time")).toBeUndefined();
    expect(replayTimestamp(undefined)).toBeUndefined();
    expect(replayTimestamp(null)).toBeUndefined();
  });

  it("interpolates a route the way the trace's own microsecond waypoints do", () => {
    // Real waypoints from a generated run. Truncating them to whole milliseconds moved the
    // interpolated point by a quarter of a millimetre, which is enough to lose a walk.
    const microseconds = route({
      eventId: "precise",
      at: "2026-10-30T12:40:00+01:00", end: "2026-10-30T12:40:05.201202+01:00",
      waypoints: [
        { at: "2026-10-30T12:40:00.734427+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 9.0797, y: 4.0153 } },
        { at: "2026-10-30T12:40:01.471135+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 9.6938, y: 3.7653 } },
      ],
    });

    const position = movementPositionAt(microseconds, replayTimestamp("2026-10-30T12:40:01+01:00")!);

    expect(Math.abs(position!.x - 9.301074519212497)).toBeLessThan(1e-6);
    expect(Math.abs(position!.y - 3.9251784728820645)).toBeLessThan(1e-6);
  });
});

describe("routes", () => {
  it("is under way only inside its own half-open interval", () => {
    expect(movementAt(walk, at("2026-10-30T08:00:00+01:00"))).toBe(walk);
    expect(movementAt(walk, at("2026-10-30T08:00:39+01:00"))).toBe(walk);
    expect(movementAt(walk, at("2026-10-30T08:00:40+01:00"))).toBeUndefined();
    expect(movementAt(walk, undefined)).toBeUndefined();
    expect(movementAt(undefined, at("2026-10-30T08:00:10+01:00"))).toBeUndefined();
  });

  it("falls back to the last waypoint when a route declares no end", () => {
    const open = route({ eventId: "open-ended", end: null });
    expect(movementEnd(open)).toBe(replayTimestamp("2026-10-30T08:00:40+01:00"));
    expect(movementEnd(undefined)).toBeUndefined();
  });

  it("refuses a route that cannot place anybody anywhere", () => {
    expect(isUsableRoute(route({ eventId: "bare", waypoints: [] }))).toBe(false);
    expect(isUsableRoute(route({ eventId: "single", waypoints: [walk.waypoints[0]!] }))).toBe(false);
    expect(isUsableRoute(route({ eventId: "undated", waypoints: [{ ...walk.waypoints[0]!, at: "whenever" }, walk.waypoints[1]!] }))).toBe(false);
    expect(isUsableRoute(route({ eventId: "nowhere", waypoints: [{ ...walk.waypoints[0]!, position: { x: Number.NaN, y: 0 } }, walk.waypoints[1]!] }))).toBe(false);
    expect(isUsableRoute(route({ eventId: "backwards", end: "2026-10-30T07:00:00+01:00" }))).toBe(false);
    expect(isUsableRoute(walk)).toBe(true);
  });

  it("reports how far along a route is, and treats an instant one as finished", () => {
    expect(movementProgress(walk, at("2026-10-30T08:00:10+01:00"))).toBeCloseTo(.25);
    expect(movementProgress(walk, at("2026-10-30T07:00:00+01:00"))).toBe(0);
    expect(movementProgress(walk, at("2026-10-30T09:00:00+01:00"))).toBe(1);
    expect(movementProgress(route({ eventId: "instant", end: "2026-10-30T08:00:00+01:00" }), at("2026-10-30T08:00:00+01:00"))).toBe(1);
  });

  it("picks the last route started at or before the instant", () => {
    const later = route({ eventId: "later", at: "2026-10-30T09:00:00+01:00", end: "2026-10-30T09:00:40+01:00" });
    expect(routeAt([walk, later], at("2026-10-30T08:30:00+01:00"))).toBe(walk);
    expect(routeAt([walk, later], at("2026-10-30T09:30:00+01:00"))).toBe(later);
    expect(routeAt([walk, later], at("2026-10-30T07:00:00+01:00"))).toBeUndefined();
    expect(routeAt([walk], undefined)).toBeUndefined();
  });

  it("lets a finished route speak only for instants its anchor cannot know about", () => {
    const after = at("2026-10-30T08:05:00+01:00");
    // An anchor taken before the walk has not seen its outcome, so the walk is the fresher word.
    expect(currentRoute([walk], after, at("2026-10-30T07:00:00+01:00"))).toBe(walk);
    // An anchor taken after it has, and whatever it reports wins.
    expect(currentRoute([walk], after, at("2026-10-30T08:05:00+01:00"))).toBeUndefined();
    expect(currentRoute([walk], after, undefined)).toBe(walk);
    expect(currentRoute([walk], at("2026-10-30T08:00:10+01:00"), at("2026-10-30T09:00:00+01:00"))).toBe(walk);
    expect(currentRoute([], after, undefined)).toBeUndefined();
  });

  it("clamps a position to the route's own ends and reads duplicate waypoints right-continuously", () => {
    expect(movementPositionAt(walk, at("2026-10-30T07:00:00+01:00"))).toEqual({ x: 0, y: 0 });
    expect(movementPositionAt(walk, at("2026-10-30T09:00:00+01:00"))).toEqual({ x: 4, y: 0 });
    const duplicate = route({
      eventId: "duplicate",
      waypoints: [
        { at: "2026-10-30T08:00:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 1, y: 1 } },
        { at: "2026-10-30T08:00:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 3, y: 3 } },
        { at: "2026-10-30T08:00:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 4, y: 4 } },
      ],
    });
    expect(waypointAtOrBefore(duplicate, at("2026-10-30T08:00:00+01:00"))?.position).toEqual({ x: 3, y: 3 });
    expect(waypointAtOrBefore(walk, at("2026-10-30T07:00:00+01:00"))).toBeUndefined();
  });

  it("keeps only the run of a route that stays inside the flat", () => {
    const inside = (regionId: string) => regionId !== "outdoors";
    const leaving = route({
      eventId: "leaving",
      waypoints: [
        { at: "2026-10-30T08:00:00+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 0, y: 0 } },
        { at: "2026-10-30T08:00:20+01:00", regionId: "living_room", traversalMode: "walking", position: { x: 2, y: 0 } },
        { at: "2026-10-30T08:00:40+01:00", regionId: "outdoors", traversalMode: "walking", position: { x: 3, y: 22 } },
      ],
    });
    const arriving = route({
      eventId: "arriving",
      waypoints: [
        { at: "2026-10-30T08:00:00+01:00", regionId: "outdoors", traversalMode: "walking", position: { x: 3, y: 22 } },
        { at: "2026-10-30T08:00:40+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 0, y: 0 } },
      ],
    });

    expect(interiorRun(leaving, inside)).toEqual({ from: 0, to: 1 });
    expect(interiorRun(arriving, inside)).toEqual({ from: 1, to: 1 });
    expect(interiorRoute(leaving, inside)?.waypoints.map((waypoint) => waypoint.regionId))
      .toEqual(["kitchen", "living_room"]);
    // A route that never touches the flat has nothing this plan can draw.
    expect(interiorRun(route({ eventId: "elsewhere", waypoints: leaving.waypoints.slice(2) }), inside)).toBeUndefined();
    expect(interiorRoute(route({ eventId: "elsewhere", waypoints: leaving.waypoints.slice(2) }), inside)).toBeUndefined();
  });

  it("splits a route into the part walked and the part still ahead", () => {
    const half = movementPath(walk, at("2026-10-30T08:00:20+01:00"));
    expect(half.travelled).toEqual([{ x: 0, y: 0 }, { x: 2, y: 0 }]);
    expect(half.remaining).toEqual([{ x: 2, y: 0 }, { x: 4, y: 0 }]);
  });
});
