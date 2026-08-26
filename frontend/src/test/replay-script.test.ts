import { describe, expect, it } from "vitest";
import {
  activityAt,
  activityTitle,
  activityWish,
  beatsUpTo,
  buildScript,
  residentName,
} from "../replay/replay-script";
import type { HomeModel, ReplayEvent, ReplayEventWindow } from "../types";

const home = {
  entities: [
    { entityId: "refrigerator", entityType: "refrigerator" },
    { entityId: "stove", entityType: "stove" },
    { entityId: "service_kitchen", entityType: "generated_environment_service" },
  ],
} as unknown as HomeModel;

function event(part: Partial<ReplayEvent> & Pick<ReplayEvent, "at" | "kind" | "eventId">): ReplayEvent {
  return { label: "", waypoints: [], details: {}, ...part };
}

function windowOf(items: ReplayEvent[], total = items.length): ReplayEventWindow {
  return {
    items, total,
    traceStart: "2026-10-30T00:00:00+01:00", traceEnd: "2026-10-31T00:00:00+01:00",
    windowStart: "2026-10-30T00:00:00+01:00", windowEnd: "2026-10-31T00:00:00+01:00",
  };
}

describe("activity wording", () => {
  it("puts each clause that opens on a verb into the present, and joins the rest", () => {
    expect(activityTitle("eat_breakfast_and_listen_to_radio")).toBe("eating breakfast and listening to radio");
    expect(activityTitle("prepare_simple_lunch")).toBe("preparing simple lunch");
    expect(activityTitle("tidy_living_room_and_hallway")).toBe("tidying living room and hallway");
    // Nothing in "evening hygiene" is a verb, so it is something the resident is busy with.
    expect(activityTitle("evening_hygiene")).toBe("busy with evening hygiene");
  });

  it("says the same activity as the wish the trace calls an intent", () => {
    expect(activityWish("eat_breakfast")).toBe("wants to eat breakfast");
    expect(activityWish("sleep")).toBe("wants to sleep");
    expect(activityWish("evening_hygiene")).toBe("is about to start evening hygiene");
  });

  it("reads a resident identifier as a name", () => {
    expect(residentName("resident_mario_rossi")).toBe("Mario Rossi");
    expect(residentName(undefined)).toBe("The resident");
  });
});

describe("buildScript", () => {
  const script = buildScript(windowOf([
    event({ at: "2026-10-30T07:52:00+01:00", end: "2026-10-30T08:10:00+01:00", kind: "activity", eventId: "breakfast", label: "prepare_weekend_breakfast", status: "completed", actorId: "resident_mario_rossi" }),
    event({
      at: "2026-10-30T07:42:00+01:00", end: "2026-10-30T07:42:30+01:00", kind: "movement", eventId: "walk",
      actorId: "resident_mario_rossi",
      waypoints: [
        { at: "2026-10-30T07:42:00+01:00", regionId: "hallway", traversalMode: "walking", position: { x: 0, y: 0 } },
        { at: "2026-10-30T07:42:30+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 2, y: 0 } },
      ],
    }),
    event({ at: "2026-10-30T07:52:06+01:00", kind: "state_transition", eventId: "open-fridge", label: "entity.open", details: { value: true, previousValue: false, subjectId: "refrigerator" } }),
    event({ at: "2026-10-30T07:52:21+01:00", kind: "state_transition", eventId: "shut-fridge", label: "entity.open", details: { value: false, previousValue: true, subjectId: "refrigerator" } }),
    event({ at: "2026-10-30T07:52:25+01:00", kind: "state_transition", eventId: "kitchen-on", label: "entity.active", details: { value: true, subjectId: "service_kitchen" } }),
    event({ at: "2026-10-30T07:52:30+01:00", kind: "state_transition", eventId: "stove-on", label: "entity.active", details: { value: true, subjectId: "stove" } }),
    event({ at: "2026-10-30T07:53:00+01:00", kind: "state_transition", eventId: "carry", label: "resident.carrying.moka_coffee_maker", actorId: "resident_mario_rossi", details: { value: true } }),
    event({ at: "2026-10-30T08:15:00+01:00", kind: "state_transition", eventId: "sit-a", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: "sitting", previousValue: "standing" } }),
    event({ at: "2026-10-30T08:15:00+01:00", kind: "state_transition", eventId: "sit-b", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: "sitting", previousValue: "standing" } }),
  ]), home);

  it("says what happened, in the words a viewer can read", () => {
    expect(script.beats.map((beat) => beat.text)).toEqual([
      "Mario Rossi walks to the kitchen",
      "Mario Rossi wants to prepare weekend breakfast",
      "The refrigerator opens",
      "The refrigerator closes",
      "The stove switches on",
      "Mario Rossi picks up the moka coffee maker",
      "Mario Rossi sits down",
    ]);
  });

  it("leaves out the entity the home generated to stand for a capability", () => {
    // Nobody switches on "the kitchen service": it turns active because the room is in use, and
    // a sentence about it would sit between two that name real things.
    expect(script.beats.some((beat) => beat.text.includes("service"))).toBe(false);
  });

  it("tells a viewer once that somebody sat down, however many sources recorded it", () => {
    expect(script.beats.filter((beat) => beat.text === "Mario Rossi sits down")).toHaveLength(1);
  });

  it("keeps every transition for the world to fold, including the ones it does not narrate", () => {
    expect(script.transitions).toHaveLength(7);
    expect(script.movements).toHaveLength(1);
  });

  it("finds the activity covering an instant, and the beats already spoken", () => {
    const during = Date.parse("2026-10-30T08:00:00+01:00");
    expect(activityAt(script, during)?.intent).toBe("prepare_weekend_breakfast");
    expect(activityAt(script, Date.parse("2026-10-30T09:00:00+01:00"))).toBeUndefined();
    expect(beatsUpTo(script, during, 2).map((beat) => beat.text)).toEqual([
      "The stove switches on",
      "Mario Rossi picks up the moka coffee maker",
    ]);
  });

  it("keeps two residents' days apart when it is asked which one is doing what", () => {
    const shared = buildScript(windowOf([
      event({ at: "2026-10-30T09:00:00+01:00", end: "2026-10-30T10:00:00+01:00", kind: "activity", eventId: "his", label: "rest_and_read", actorId: "resident_mario_rossi" }),
      event({ at: "2026-10-30T09:00:00+01:00", end: "2026-10-30T10:00:00+01:00", kind: "activity", eventId: "hers", label: "clean_kitchen", actorId: "resident_luisa_bianchi" }),
    ]), home);
    const during = Date.parse("2026-10-30T09:30:00+01:00");

    expect(activityAt(shared, during, "resident_luisa_bianchi")?.intent).toBe("clean_kitchen");
    expect(activityAt(shared, during, "resident_mario_rossi")?.intent).toBe("rest_and_read");
    expect(activityAt(shared, during, "resident_nobody")).toBeUndefined();
    expect(shared.beats[1]?.text).toBe("Luisa Bianchi wants to clean kitchen");
  });

  it("reports a day it could not be given whole", () => {
    expect(script.truncated).toBe(false);
    expect(buildScript(windowOf([], 9_000), home).truncated).toBe(true);
    expect(buildScript(undefined, home).beats).toEqual([]);
  });

  it("does not announce a walk that ends in the room it started in", () => {
    const shuffle = buildScript(windowOf([event({
      at: "2026-10-30T07:42:00+01:00", kind: "movement", eventId: "shuffle", actorId: "resident_mario_rossi",
      waypoints: [
        { at: "2026-10-30T07:42:00+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 0, y: 0 } },
        { at: "2026-10-30T07:42:10+01:00", regionId: "kitchen", traversalMode: "walking", position: { x: 1, y: 0 } },
      ],
    })]), home);

    expect(shuffle.beats).toEqual([]);
    expect(shuffle.movements).toHaveLength(1);
  });

  it("says getting up and lying down apart from standing up", () => {
    const postures = buildScript(windowOf([
      event({ at: "2026-10-30T07:15:00+01:00", kind: "state_transition", eventId: "up", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: "standing", previousValue: "lying" } }),
      event({ at: "2026-10-30T22:00:00+01:00", kind: "state_transition", eventId: "down", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: "lying", previousValue: "standing" } }),
      event({ at: "2026-10-30T22:05:00+01:00", kind: "state_transition", eventId: "drop", label: "resident.carrying.drinking_glass", actorId: "resident_mario_rossi", details: { value: false } }),
    ]), home);

    expect(postures.beats.map((beat) => beat.text)).toEqual([
      "Mario Rossi gets up",
      "Mario Rossi lies down",
      "Mario Rossi puts down the drinking glass",
    ]);
  });

  it("reads a posture it has no phrase for rather than staying silent about it", () => {
    const odd = buildScript(windowOf([
      event({ at: "2026-10-30T07:15:00+01:00", kind: "state_transition", eventId: "crouch", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: "crouching", previousValue: "standing" } }),
      event({ at: "2026-10-30T07:16:00+01:00", kind: "state_transition", eventId: "void", label: "resident.posture", actorId: "resident_mario_rossi", details: { value: null } }),
      event({ at: "2026-10-30T07:17:00+01:00", kind: "state_transition", eventId: "nameless", label: "entity.open", details: { value: true } }),
      event({ at: "2026-10-30T07:18:00+01:00", kind: "state_transition", eventId: "counter", label: "entity.stock.consumed", details: { value: 2, subjectId: "refrigerator" } }),
      event({ at: "2026-10-30T07:19:00+01:00", kind: "action", eventId: "action", label: "prepare_food" }),
      event({ at: "not a time", kind: "activity", eventId: "undated", label: "sleep" }),
    ]), home);

    expect(odd.beats.map((beat) => beat.text)).toEqual(["Mario Rossi is crouching"]);
    // A transition with no subject, or about a fact nothing on screen shows, is still folded.
    expect(odd.transitions).toHaveLength(4);
    expect(odd.activities).toEqual([]);
  });
});
