import type { SceneActivity, SceneBeat, SceneScript } from "./replay-script";
import { residentName } from "./replay-script";

/**
 * The people in the flat, in one order and one colour each, for every part of the page at once.
 *
 * A household of two on one plan was two identical red figures, one caption that named whoever
 * came first, a list of what happened that interleaved both of them, and one day ribbon holding
 * both people's activities on top of each other. Each of those needs to say *whose*, and the
 * cheapest way to say it everywhere is the same colour and the same order everywhere.
 */

/** How many distinct tones the scene defines. A fifth resident shares the first one's. */
export const RESIDENT_TONES = 4;

export interface CastMember {
  residentId: string;
  name: string;
  /** Index into the scene's resident tones, `scene-tone-N`. */
  tone: number;
}

/**
 * Everyone the day is about: the residents the scene can draw, in the order it draws them, and
 * anyone the day's activities name who is not on the plan at this instant.
 *
 * The plan's order comes first because the stage assigns tones by it, so the figure and the card
 * agree without either having to be told. Someone away all day is still in the household.
 */
export function castOf(
  drawn: ReadonlyArray<{ residentId: string; name: string }>,
  activities: readonly SceneActivity[],
): CastMember[] {
  const cast: CastMember[] = drawn.map((resident, index) => ({
    residentId: resident.residentId,
    name: resident.name,
    tone: index % RESIDENT_TONES,
  }));
  for (const activity of activities) {
    if (!activity.actorId || cast.some((member) => member.residentId === activity.actorId)) continue;
    cast.push({ residentId: activity.actorId, name: residentName(activity.actorId), tone: cast.length % RESIDENT_TONES });
  }
  return cast;
}

/** What one resident was last seen doing, most recent last. */
export function beatsFor(script: SceneScript, atMs: number, residentId: string, count: number): SceneBeat[] {
  const passed = script.beats.filter((beat) => beat.atMs <= atMs && beat.actorId === residentId);
  return passed.slice(Math.max(0, passed.length - count));
}

/**
 * What happened to the flat rather than to a person: a door, an appliance.
 *
 * The trace records the fridge opening without saying who opened it, and guessing from who stood
 * nearest would put a name on something the evidence does not name.
 */
export function houseBeats(script: SceneScript, atMs: number, count: number): SceneBeat[] {
  const passed = script.beats.filter((beat) => beat.atMs <= atMs && beat.actorId === undefined);
  return passed.slice(Math.max(0, passed.length - count));
}

/** One resident's activities, in order. */
export function activitiesOf(script: SceneScript, residentId: string): SceneActivity[] {
  return script.activities.filter((activity) => activity.actorId === residentId);
}

/**
 * Where "skip ahead" lands for a set of activities: past the one under way, or on to the next one,
 * or an hour on when nothing else happens today.
 *
 * Kept apart from the controller so one resident's skip and the household's use the same rule.
 */
export function skipTarget(activities: readonly SceneActivity[], atMs: number): number {
  const running = activities.find((activity) => activity.startMs <= atMs && atMs < activity.endMs);
  if (running) return running.endMs;
  const upcoming = activities.find((activity) => activity.startMs > atMs);
  return upcoming ? upcoming.startMs : atMs + 60 * 60 * 1000;
}
