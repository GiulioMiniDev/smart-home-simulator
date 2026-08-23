import { describe, expect, it } from "vitest";
import { advanceTime, clusterEvents, interpolateWaypoints } from "../replay/replay-clock";
import type { ReplayEvent } from "../types";

const event = (eventId: string, offsetMs: number): ReplayEvent => ({
  at: new Date(offsetMs).toISOString(),
  kind: "action",
  eventId,
  label: eventId,
  waypoints: [],
  details: {},
});

describe("replay clock", () => {
  it("advances simulation time by wall time times speed and clamps at the trace end", () => {
    const start = Date.parse("2026-08-23T08:00:00Z");
    expect(advanceTime(start, 500, 8, start + 3_000)).toBe(start + 3_000);
  });

  it("does not cross the trace start when rewinding", () => {
    const start = Date.parse("2026-08-23T08:00:00Z");
    expect(advanceTime(start + 100, -500, 1, start + 10_000, start)).toBe(start);
  });

  it("leaves a clock tick inside the trace unchanged by clamping", () => {
    const start = Date.parse("2026-08-23T08:00:00Z");
    expect(advanceTime(start + 1_000, 500, 2, start + 10_000, start)).toBe(start + 2_000);
  });

  it("interpolates timestamped waypoints rather than event indexes", () => {
    const point = interpolateWaypoints([
      { at: "2026-08-23T08:00:00Z", regionId: "hall", traversalMode: "walking", position: { x: 0, y: 2 } },
      { at: "2026-08-23T08:00:10Z", regionId: "kitchen", traversalMode: "walking", position: { x: 10, y: 4 } },
    ], Date.parse("2026-08-23T08:00:05Z"));
    expect(point).toEqual({ x: 5, y: 3 });
  });

  it("returns no position for an empty trajectory", () => {
    expect(interpolateWaypoints([], Date.now())).toBeUndefined();
  });

  it("holds the first and last authoritative waypoint outside its trajectory", () => {
    const waypoints = [
      { at: "2026-08-23T08:00:00Z", regionId: "hall", traversalMode: "walking", position: { x: 1, y: 2 } },
      { at: "2026-08-23T08:00:10Z", regionId: "kitchen", traversalMode: "walking", position: { x: 3, y: 4 } },
    ];
    expect(interpolateWaypoints(waypoints, Date.parse("2026-08-23T07:59:59Z"))).toEqual({ x: 1, y: 2 });
    expect(interpolateWaypoints(waypoints, Date.parse("2026-08-23T08:00:11Z"))).toEqual({ x: 3, y: 4 });
  });

  it("ignores malformed waypoint timestamps instead of inventing a position", () => {
    expect(interpolateWaypoints([
      { at: "not-a-time", regionId: "hall", traversalMode: "walking", position: { x: 1, y: 2 } },
    ], Date.now())).toBeUndefined();
  });

  it("clusters dense events without dropping their ids", () => {
    const clusters = clusterEvents([event("a", 0), event("b", 1)], 0, 10, 10);
    expect(clusters.flatMap((item) => item.eventIds)).toEqual(["a", "b"]);
  });

  it("keeps marks at least six pixels apart as separate clusters", () => {
    const clusters = clusterEvents([event("a", 0), event("b", 10)], 0, 10, 10);
    expect(clusters).toHaveLength(2);
  });

  it("keeps a degenerate timeline deterministic", () => {
    expect(clusterEvents([event("a", 0)], 0, 0, 10)).toEqual([{ eventIds: ["a"], x: 0 }]);
  });
});
