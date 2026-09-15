/**
 * A horizon outline as it actually arrives: an unvalidated JSON object written by a model.
 *
 * `RawOutline` mirrors `horizon-outline-2.0.0.schema.json` with every field optional, because this
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

/** What is individual to one person: who they are, what recurs for them, how their day divides. */
export interface RawResident {
  residentId?: string;
  displayName?: string;
  profile?: { recurringActivities?: RawActivity[] };
  rhythm?: { age?: number; health?: string[]; chronotypeBedtime?: string };
  habits?: RawHabit[];
  fixedCommitments?: RawCommitment[];
  phases?: RawPhase[];
  events?: RawEvent[];
  startLocationId?: string | null;
  note?: string;
}

export type RelationKind = "couple" | "housemates" | "parent_child" | "siblings" | "other";
export type SharingMode = "joint" | "optional_joint" | "independent" | "exclusive";

/** What is true of the house rather than of any one person in it (ADR-026). */
export interface RawHousehold {
  relations?: Array<{ between?: string[]; kind?: RelationKind; note?: string }>;
  jointActivities?: Array<{
    activity?: RawActivity;
    participantIds?: string[];
    sharing?: SharingMode;
    propensity?: { default?: number; weekday?: number | null; weekend?: number | null } | null;
    minimumSharedMinutes?: number;
    degradeToIndependent?: boolean;
    note?: string;
  }>;
  sharingPolicies?: Array<{ between?: string[]; intent?: string; sharing?: SharingMode; note?: string }>;
  locationPrivacy?: Array<{
    locationId?: string;
    subjectId?: string;
    excludedResidentIds?: string[];
    intents?: string[];
    symmetric?: boolean;
    note?: string;
  }>;
  sharedLocationIds?: string[];
}

/**
 * Both shapes an outline has had. 2.0.0 keeps the person under `residents` and adds `household`;
 * 1.x kept the one person at the top level, and `readOutline` lifts that into a roster of one the
 * same way the server's `upgrade_outline_payload` does, so everything downstream reads one shape.
 */
export interface RawOutline extends RawResident {
  documentType?: string;
  schemaVersion?: string;
  outlineId?: string;
  title?: string;
  timeZone?: string;
  startDate?: string;
  months?: number;
  world?: {
    locations?: Array<{ locationId?: string; kind?: string }>;
    resources?: Array<{ resourceId?: string; resourceType?: string; locationId?: string }>;
    externalPeople?: Array<{ externalPersonId?: string; displayName?: string | null }>;
    startLocationId?: string;
  };
  residents?: RawResident[];
  household?: RawHousehold;
  vocabularyProposals?: RawVocabularyProposals;
  provenance?: {
    authorType?: string;
    modelName?: string | null;
    generatedAt?: string | null;
    humanReviewed?: boolean;
    promptTemplateVersion?: string | null;
  };
  note?: string;
}

/** What the author asks to add to the vocabulary, for the researcher to accept or refuse. */
export interface RawVocabularyProposals {
  furniture?: Array<{ entityType?: string; displayName?: string; capabilities?: string[]; contactInstrumented?: boolean; rationale?: string }>;
  activities?: Array<{ intentId?: string; label?: string; category?: string; defaultLocation?: string; description?: string; rationale?: string }>;
}

/** A process model as the file carries it: passed through untouched to the vocabulary, never drawn. */
export interface RawProcessModel {
  processModelId?: string;
  title?: string;
  residentId?: string;
  implementedComponents?: string[];
  nodes?: Array<{ nodeId?: string; kind?: string; actionType?: string | null }>;
  edges?: unknown[];
  [field: string]: unknown;
}

export interface RawPackage {
  processModels?: RawProcessModel[];
  bindings?: Array<{ intent?: string; processModelId?: string; residentId?: string }>;
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

/** One person of the household, read on their own: their day, their week, their stretches. */
export interface ResidentReading {
  residentId: string;
  /** The display name when the model wrote one, the identifier otherwise. */
  name: string;
  age?: number;
  health: string[];
  bedtime?: string;
  bands: BandView[];
  bandRows: BandRow[];
  commitments: CommitmentView[];
  activities: ActivityView[];
  week: WeekColumn[];
  weekVaries: boolean;
  phases: PhaseView[];
  events: EventView[];
  note: string;
}

/** A shared activity: declared once, with one window, and the people who take part named. */
export interface JointActivityView extends ActivityView {
  participants: string[];
  /** How often it is actually shared — always, or a proportion that may differ at the weekend. */
  together: string;
  /** What happens on a day the shared version does not fit. */
  fallback: string;
}

export interface HouseholdView {
  relations: string[];
  joint: JointActivityView[];
  policies: string[];
  privacy: string[];
  sharedRooms: string[];
}

export interface HorizonReading {
  title: string;
  /** Absent when the file carried the outline alone, with no process package beside it. */
  behaviour?: BehaviourView;
  /** Never empty: a 1.x outline, or one whose roster is unreadable, is read as a household of one. */
  residents: ResidentReading[];
  household: HouseholdView;
  timeZone: string;
  startDate: string;
  /** The last day that is simulated — the schema's half-open end date, minus one. */
  lastDate: string;
  spanPhrase: string;
  dayCount: number;
  months: number;
  authorPhrase: string;
  humanReviewed: boolean;
  monthTicks: MonthTick[];
  rooms: string[];
  elsewhere: string[];
  /** Every declared object, so the preview can say which of them the vocabulary does not know. */
  furniture: Array<{ resourceId: string; resourceType: string; room: string }>;
  /** Every intent the outline uses anywhere, so the preview can say which the vocabulary lacks. */
  usedIntents: string[];
  proposals: ProposalsView;
  people: string[];
  note: string;
  /** Everything the outline says that this reading could not place on a clock or a calendar. */
  gaps: string[];
}

export interface FurnitureProposalView {
  entityType: string;
  displayName: string;
  capabilities: string[];
  contactInstrumented: boolean;
  rationale: string;
}

export interface ActivityProposalView {
  intentId: string;
  label: string;
  category: string;
  defaultLocation: string;
  description: string;
  rationale: string;
  /** The first process model the package binds to this intent, to start the vocabulary entry from. */
  processModel?: RawProcessModel;
  /** How many steps that model takes, for the sentence beside the button. */
  steps: number;
}

export interface ProposalsView {
  furniture: FurnitureProposalView[];
  activities: ActivityProposalView[];
  /** Process models by the intent they are bound to, for activities used without a proposal. */
  modelsByIntent: Record<string, RawProcessModel>;
}

export type OutlineReadResult =
  | { kind: "outline"; reading: HorizonReading }
  | { kind: "other"; message: string };
