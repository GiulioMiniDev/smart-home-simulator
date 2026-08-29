import type { HomeModel, ReplayEvent, ReplayEventWindow } from "../types";

/**
 * The day, read as a script.
 *
 * Everything here is the execution trace said in ordinary words: an activity's own `intent`
 * becomes what the resident wants, a posture transition becomes them sitting down, an entity's
 * `open` or `active` becomes a door or an appliance. Nothing is inferred beyond the wording.
 */

export interface SceneActivity {
  eventId: string;
  actorId?: string;
  startMs: number;
  endMs: number;
  intent: string;
  /** "eating breakfast and listening to the radio" */
  title: string;
  /** "wants to eat breakfast and listen to the radio" */
  wish: string;
  deviated: boolean;
}

export type SceneBeatKind = "activity" | "arrive" | "posture" | "device" | "carry";

export interface SceneBeat {
  atMs: number;
  actorId?: string;
  text: string;
  kind: SceneBeatKind;
}

export interface SceneScript {
  activities: SceneActivity[];
  beats: SceneBeat[];
  movements: ReplayEvent[];
  /** State changes, in order, so the world can be folded up to any instant. */
  transitions: ReplayEvent[];
  truncated: boolean;
}

/** Verbs the generated activity vocabulary actually uses, in the form a caption needs. */
const PROGRESSIVE: Record<string, string> = {
  wake: "waking", get: "getting", prepare: "preparing", eat: "eating", drink: "drinking",
  take: "taking", check: "checking", travel: "travelling", buy: "buying", put: "putting",
  rest: "resting", read: "reading", clean: "cleaning", tidy: "tidying", call: "calling",
  watch: "watching", sleep: "sleeping", start: "starting", work: "working", use: "using",
  portion: "portioning", listen: "listening", manage: "managing", organize: "organising",
  inspect: "checking", wash: "washing", shower: "showering", cook: "cooking",
  water: "watering", write: "writing", visit: "visiting", tend: "tending", store: "storing",
  go: "going", walk: "walking", make: "making", phone: "phoning", hang: "hanging", nap: "napping",
};

/** Whole labels that open on no verb at all and read badly without one. */
const PHRASES: Record<string, string> = { "batch cook": "batch cooking" };

function words(value: string): string {
  return value.replaceAll("_", " ").trim();
}

// Two spellings arrive here and both have to work. The replay now sends the catalogue label —
// "Walk outdoors", because the id `evening_walk` announced a seven-in-the-morning run as an
// evening one — while everything written before it sends the id. Normalising to lower-case
// words up front makes "eat_breakfast" and "Eat breakfast" the same sentence, so nothing has to
// know which spelling it was handed.
function spoken(value: string): string {
  return words(value).toLowerCase();
}

function clauses(intent: string): string[] {
  return spoken(intent).split(" and ").filter(Boolean);
}

function verb(clause: string): string | undefined {
  return PROGRESSIVE[clause.split(" ")[0] ?? ""];
}

/** An activity's title, with every clause that opens on a known verb put into the present. */
export function activityTitle(intent: string): string {
  const parts = clauses(intent);
  const said = parts.map((clause) => {
    const phrase = PHRASES[clause];
    if (phrase) return phrase;
    const [head, ...rest] = clause.split(" ");
    const progressive = head ? PROGRESSIVE[head] : undefined;
    return progressive ? [progressive, ...rest].join(" ") : clause;
  });
  const named = parts.some((clause) => verb(clause) !== undefined || PHRASES[clause] !== undefined);
  return named ? said.join(" and ") : `busy with ${said.join(" and ")}`;
}

/** The same activity as a wish, which is what the trace calls it: an intent. */
export function activityWish(intent: string): string {
  const named = clauses(intent).some((clause) => verb(clause) !== undefined);
  return named ? `wants to ${spoken(intent)}` : `is about to start ${spoken(intent)}`;
}

export function residentName(actorId: string | null | undefined): string {
  if (!actorId) return "The resident";
  return words(actorId.replace(/^resident_/, "")).replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function instant(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function detail(event: ReplayEvent, key: string): unknown {
  return event.details[key];
}

/**
 * Entities the home generated to stand for a capability rather than for a thing.
 *
 * A resident never opens or switches on "the kitchen service"; it turns active because they are
 * using the room. Narrating it would put a sentence with no referent between two that have one.
 */
function narratableEntities(home: HomeModel | undefined): Set<string> {
  return new Set((home?.entities ?? [])
    .filter((entity) => entity.entityType !== "generated_environment_service")
    .map((entity) => entity.entityId));
}

function postureBeat(name: string, from: unknown, to: unknown): string | undefined {
  if (typeof to !== "string") return undefined;
  if (to === "sitting") return `${name} sits down`;
  if (to === "lying") return `${name} lies down`;
  if (to === "standing") return from === "lying" ? `${name} gets up` : `${name} stands up`;
  return `${name} is ${words(to)}`;
}

/** Fold one day of evidence into the things a viewer can be told, in the order they happen. */
export function buildScript(window: ReplayEventWindow | undefined, home: HomeModel | undefined): SceneScript {
  const items = window?.items ?? [];
  const narratable = narratableEntities(home);
  const activities: SceneActivity[] = [];
  const beats: SceneBeat[] = [];
  const movements: ReplayEvent[] = [];
  const transitions: ReplayEvent[] = [];
  // The trace can record the same posture change from two sources at the same instant, and a
  // viewer must not be told twice that somebody sat down.
  const spoken = new Set<string>();

  for (const event of items) {
    const atMs = instant(event.at);
    if (atMs === undefined) continue;
    const name = residentName(event.actorId);

    if (event.kind === "activity") {
      const endMs = instant(event.end) ?? atMs;
      activities.push({
        eventId: event.eventId, actorId: event.actorId ?? undefined,
        startMs: atMs, endMs, intent: event.label,
        title: activityTitle(event.label), wish: activityWish(event.label),
        deviated: event.status === "deviated",
      });
      beats.push({ atMs, actorId: event.actorId ?? undefined, kind: "activity", text: `${name} ${activityWish(event.label)}` });
      continue;
    }

    if (event.kind === "movement") {
      movements.push(event);
      const destination = event.waypoints.at(-1)?.regionId;
      const origin = event.waypoints[0]?.regionId;
      if (destination && destination !== origin) {
        beats.push({ atMs, actorId: event.actorId ?? undefined, kind: "arrive", text: `${name} walks to the ${words(destination)}` });
      }
      continue;
    }

    if (event.kind !== "state_transition") continue;
    transitions.push(event);
    const value = detail(event, "value");
    const previous = detail(event, "previousValue");
    const key = `${String(atMs)}:${event.label}:${String(value)}`;
    if (spoken.has(key)) continue;

    if (event.label === "resident.posture") {
      const text = postureBeat(name, previous, value);
      if (text) { spoken.add(key); beats.push({ atMs, actorId: event.actorId ?? undefined, kind: "posture", text }); }
      continue;
    }

    if (event.label.startsWith("resident.carrying.")) {
      const item = words(event.label.slice("resident.carrying.".length));
      spoken.add(key);
      beats.push({
        atMs, actorId: event.actorId ?? undefined, kind: "carry",
        text: value === true ? `${name} picks up the ${item}` : `${name} puts down the ${item}`,
      });
      continue;
    }

    const subjectId = detail(event, "subjectId");
    if (typeof subjectId !== "string" || !narratable.has(subjectId)) continue;
    const thing = words(subjectId);
    if (event.label === "entity.open") {
      spoken.add(key);
      beats.push({ atMs, kind: "device", text: value === true ? `The ${thing} opens` : `The ${thing} closes` });
    } else if (event.label === "entity.active") {
      spoken.add(key);
      beats.push({ atMs, kind: "device", text: value === true ? `The ${thing} switches on` : `The ${thing} switches off` });
    }
  }

  beats.sort((left, right) => left.atMs - right.atMs);
  activities.sort((left, right) => left.startMs - right.startMs);
  return {
    activities, beats, movements, transitions,
    truncated: Boolean(window && window.total > window.items.length),
  };
}

/** The activity covering an instant, which is what the resident is doing rather than doing next. */
export function activityAt(script: SceneScript, atMs: number, actorId?: string): SceneActivity | undefined {
  return script.activities.find((activity) => activity.startMs <= atMs && atMs < activity.endMs
    && (actorId === undefined || activity.actorId === actorId));
}

/** The last thing the viewer was told, and the few before it. */
export function beatsUpTo(script: SceneScript, atMs: number, count: number): SceneBeat[] {
  const passed = script.beats.filter((beat) => beat.atMs <= atMs);
  return passed.slice(Math.max(0, passed.length - count));
}
