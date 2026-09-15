import { describe, expect, it } from "vitest";
import { activitiesOf, beatsFor, castOf, houseBeats, RESIDENT_TONES, skipTarget } from "../replay/replay-cast";
import type { SceneActivity, SceneScript } from "../replay/replay-script";

function activity(eventId: string, actorId: string | undefined, startMs: number, endMs: number): SceneActivity {
  return { eventId, actorId, startMs, endMs, intent: eventId, title: eventId, wish: `wants to ${eventId}`, deviated: false };
}

const script: SceneScript = {
  activities: [activity("lunch", "giulia", 100, 200), activity("breakfast", "paolo", 150, 170), activity("guest", "chiara", 300, 400)],
  beats: [
    { atMs: 110, actorId: "giulia", kind: "activity", text: "Giulia wants to lunch" },
    { atMs: 120, kind: "device", text: "The fridge opens" },
    { atMs: 160, actorId: "paolo", kind: "posture", text: "Paolo sits down" },
    { atMs: 500, actorId: "giulia", kind: "posture", text: "Giulia lies down" },
  ],
  movements: [],
  transitions: [],
  truncated: false,
};

describe("the cast of a replay", () => {
  it("keeps the plan's order and tones, and adds whoever the day names but the plan does not draw", () => {
    const cast = castOf([{ residentId: "giulia", name: "Giulia" }, { residentId: "paolo", name: "Paolo" }], script.activities);
    expect(cast).toEqual([
      { residentId: "giulia", name: "Giulia", tone: 0 },
      { residentId: "paolo", name: "Paolo", tone: 1 },
      { residentId: "chiara", name: "Chiara", tone: 2 },
    ]);
    const crowd = castOf(Array.from({ length: RESIDENT_TONES + 1 }, (_, index) => ({ residentId: `r${String(index)}`, name: `R${String(index)}` })), []);
    expect(crowd.at(-1)?.tone).toBe(0);
    expect(castOf([], [activity("anon", undefined, 0, 1)])).toEqual([]);
  });

  it("gives each resident their own beats, and the flat the ones that name nobody", () => {
    expect(beatsFor(script, 200, "giulia", 4).map((beat) => beat.text)).toEqual(["Giulia wants to lunch"]);
    expect(beatsFor(script, 600, "giulia", 1).map((beat) => beat.text)).toEqual(["Giulia lies down"]);
    expect(houseBeats(script, 200, 3).map((beat) => beat.text)).toEqual(["The fridge opens"]);
    expect(activitiesOf(script, "paolo").map((item) => item.eventId)).toEqual(["breakfast"]);
  });

  it("skips past what is under way, on to what is next, or an hour on", () => {
    const giulia = activitiesOf(script, "giulia");
    expect(skipTarget(giulia, 120)).toBe(200);
    expect(skipTarget(giulia, 50)).toBe(100);
    expect(skipTarget(giulia, 250)).toBe(250 + 60 * 60 * 1000);
  });
});
