/**
 * A horizon outline as it actually arrives: an unvalidated JSON object written by a model.
 *
 * `RawOutline` mirrors `horizon-outline-1.0.0.schema.json` with every field optional, because this
 * file is read *before* the server has judged it. Anything missing or malformed must degrade into
 * a gap in the picture, never into a blank page or a thrown error — the whole point of reading the
 * outline here is to see what the model wrote, including the parts it got wrong.
 *
 * The `*View` types are the opposite: everything is resolved, positioned and phrased, so the
 * component only places things and the arithmetic stays in `reading.ts`, where it is tested.
 */

export type Weekday = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
export type CadencePeriod = "day" | "week" | "month";
export type ActivityKind = "anchor" | "contextual" | "optional" | "rare";

export interface RawCadence {
  period?: CadencePeriod;
  timesPerPeriod?: number;
  everyNPeriods?: number;
  weekdays?: Weekday[];
  windowStart?: string;
  windowEnd?: string;
  jitterMinutes?: number;
}

export interface RawActivity {
  recurringActivityId?: string;
  label?: string;
  kind?: ActivityKind;
  cadence?: RawCadence;
  intent?: string | null;
  note?: string;
}

export interface RawHabit {
  habitId?: string;
  label?: string;
  windowStart?: string;
  windowEnd?: string;
  recurringActivityIds?: string[];
  weekdays?: Weekday[];
  note?: string;
}

export interface RawCommitment {
  commitmentId?: string;
  label?: string;
  weekdays?: Weekday[];
  startTime?: string;
  endTime?: string;
  intent?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  note?: string;
}

export interface RawOverride {
  recurringActivityId?: string;
  suspended?: boolean;
  cadence?: RawCadence | null;
}

export interface RawPhase {
  phaseId?: string;
  label?: string;
  startDate?: string;
  endDate?: string;
  activityOverrides?: RawOverride[];
  note?: string;
}

export interface RawEvent {
  eventId?: string;
  label?: string;
  earliestDate?: string;
  latestDate?: string;
  occurrences?: number;
  windowStart?: string;
  windowEnd?: string;
  minimumMinutes?: number;
  maximumMinutes?: number;
  weekdays?: Weekday[];
  intent?: string | null;
  displaces?: Array<{ recurringActivityId?: string; policy?: "skip" | "reschedule" }>;
  note?: string;
}

export interface RawOutline {
  documentType?: string;
  outlineId?: string;
  title?: string;
  residentId?: string;
  timeZone?: string;
  startDate?: string;
  months?: number;
  world?: {
    locations?: Array<{ locationId?: string; kind?: string }>;
    resources?: Array<{ resourceId?: string; resourceType?: string; locationId?: string }>;
    externalPeople?: Array<{ externalPersonId?: string; displayName?: string | null }>;
    startLocationId?: string;
  };
  profile?: { recurringActivities?: RawActivity[] };
  rhythm?: { age?: number; health?: string[]; chronotypeBedtime?: string };
  habits?: RawHabit[];
  fixedCommitments?: RawCommitment[];
  phases?: RawPhase[];
  events?: RawEvent[];
  provenance?: {
    authorType?: string;
    modelName?: string | null;
    generatedAt?: string | null;
    humanReviewed?: boolean;
    promptTemplateVersion?: string | null;
  };
  note?: string;
}

export interface RawPackage {
  processModels?: Array<{ processModelId?: string; title?: string }>;
  bindings?: Array<{ intent?: string; processModelId?: string }>;
  language?: string;
}

/**
 * What the outline prompt actually asks the model to return.
 *
 * The response is the envelope, not the outline on its own: the arc of the period, and beside it
 * the process package saying how each of its intents is performed. The picker is named after both
 * halves for that reason: labelled "Horizon outline" alone, it read as a refusal of the very file
 * it wanted, since that file's `documentType` is `horizon_authoring_bundle`.
 */
export interface RawBundle {
  documentType?: string;
  outline?: RawOutline;
  personalProcessPackage?: RawPackage;
}

/** A stretch of the 24-hour clock. A window that wraps past midnight becomes two of these. */
export interface DayPiece {
  fromMinutes: number;
  toMinutes: number;
}

export interface BandView {
  id: string;
  label: string;
  pieces: DayPiece[];
  clock: string;
  weekdays: Weekday[];
  weekdayPhrase: string;
  activityLabels: string[];
  note: string;
  wraps: boolean;
}

/**
 * One spine of the day, and the days it is the spine of.
 *
 * Bands may be scoped to weekdays, so a Wednesday spent working from home and a Saturday are
 * genuinely different carvings of the same 24 hours. Drawing them on one track hides whichever
 * was painted first — which on a real outline was the whole work-from-home day.
 */
export interface BandRow {
  key: string;
  label: string;
  bands: BandView[];
}

export interface CommitmentView {
  id: string;
  label: string;
  pieces: DayPiece[];
  clock: string;
  weekdays: Weekday[];
  weekdayPhrase: string;
  sentence: string;
  note: string;
}

export interface ActivityView {
  id: string;
  label: string;
  kind: ActivityKind;
  pieces: DayPiece[];
  clock: string;
  weekdays: Weekday[];
  sentence: string;
  spread: string;
  note: string;
  /** Sorts the day rows: where the window opens, in minutes past midnight. */
  order: number;
}

export interface PhaseView {
  id: string;
  label: string;
  fromFraction: number;
  toFraction: number;
  lane: number;
  sentence: string;
  changes: string[];
  note: string;
}

export interface EventView {
  id: string;
  label: string;
  fromFraction: number;
  toFraction: number;
  lane: number;
  sentence: string;
  displaces: string[];
  note: string;
}

export interface MonthTick {
  fraction: number;
  label: string;
  /** January and the first tick carry the year; the rest would only add noise. */
  year?: string;
}

export interface WeekColumn {
  weekday: Weekday;
  short: string;
  /** What is pinned to this weekday and nothing else — the reason the days differ at all. */
  entries: Array<{ label: string; kind: "commitment" | "activity" | "band" }>;
}

export interface BehaviourView {
  processCount: number;
  /** Intents the outline names that no binding in the package implements. */
  unimplemented: string[];
  namedIntents: number;
}

export interface HorizonReading {
  title: string;
  /** Absent when the file carried the outline alone, with no process package beside it. */
  behaviour?: BehaviourView;
  residentId: string;
  timeZone: string;
  startDate: string;
  /** The last day that is simulated — the schema's half-open end date, minus one. */
  lastDate: string;
  spanPhrase: string;
  dayCount: number;
  months: number;
  age?: number;
  health: string[];
  bedtime?: string;
  authorPhrase: string;
  humanReviewed: boolean;
  bands: BandView[];
  bandRows: BandRow[];
  commitments: CommitmentView[];
  activities: ActivityView[];
  week: WeekColumn[];
  weekVaries: boolean;
  phases: PhaseView[];
  events: EventView[];
  monthTicks: MonthTick[];
  rooms: string[];
  elsewhere: string[];
  people: string[];
  note: string;
  /** Everything the outline says that this reading could not place on a clock or a calendar. */
  gaps: string[];
}

export type OutlineReadResult =
  | { kind: "outline"; reading: HorizonReading }
  | { kind: "other"; message: string };
