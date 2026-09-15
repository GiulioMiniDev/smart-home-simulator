/**
 * Turning a horizon outline into something a person can read at a glance.
 *
 * The outline is the one authoring document that is *deliberately* not a list of days: it says
 * how the day is carved into bands, what recurs and how often, what is pinned by an employer, and
 * which stretches of the horizon behave differently. That structure is what makes eight months
 * affordable — and it is also what makes the file unreadable to anyone who is not holding the
 * schema. Six hundred lines of JSON hide a very simple picture: a clock, a week and a calendar.
 *
 * Everything here is pure and total. A field the model omitted, a time it wrote as "9am" or a
 * phase whose dates fall outside the horizon must all survive as a gap in the picture and a line
 * in `gaps`, because this reading happens before the server has validated anything: it is
 * precisely the malformed outlines that most need looking at.
 */

import type {
  ActivityKind,
  ActivityView,
  BandRow,
  BandView,
  BehaviourView,
  CommitmentView,
  DayPiece,
  EventView,
  HouseholdView,
  MonthTick,
  OutlineReadResult,
  PhaseView,
  ProposalsView,
  RawActivity,
  RawBundle,
  RawCadence,
  RawCommitment,
  RawEvent,
  RawHabit,
  RawHousehold,
  RawOutline,
  RawPackage,
  RawVocabularyProposals,
  RawPhase,
  RawProcessModel,
  RawResident,
  RelationKind,
  ResidentReading,
  SharingMode,
  WeekColumn,
  Weekday,
} from "./types";

export const WEEKDAYS: Weekday[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const SHORT_WEEKDAY: Record<Weekday, string> = {
  monday: "Mon", tuesday: "Tue", wednesday: "Wed", thursday: "Thu", friday: "Fri", saturday: "Sat", sunday: "Sun",
};

const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const MINUTES_PER_DAY = 1440;
const MILLISECONDS_PER_DAY = 86_400_000;

const KIND_ORDER: Record<ActivityKind, number> = { anchor: 0, contextual: 1, optional: 2, rare: 3 };

export const KIND_PHRASE: Record<ActivityKind, string> = {
  anchor: "Anchor — the day is built around it",
  contextual: "Contextual — it happens when the day allows",
  optional: "Optional — it may or may not happen",
  rare: "Rare — a few times over the whole horizon",
};

/** Minutes past midnight for `HH:MM`, or `undefined` for anything this reading cannot place. */
export function minutesOfDay(value: unknown): number | undefined {
  if (typeof value !== "string") return undefined;
  const match = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(value.trim());
  if (!match) return undefined;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 24 || minutes > 59) return undefined;
  const total = hours * 60 + minutes;
  return total > MINUTES_PER_DAY ? undefined : total;
}

export function clockLabel(minutes: number): string {
  const wrapped = ((minutes % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  return `${String(Math.floor(wrapped / 60)).padStart(2, "0")}:${String(wrapped % 60).padStart(2, "0")}`;
}

/**
 * The stretches of the clock a window covers.
 *
 * A window whose end is earlier than its start crosses midnight, which the night band does by
 * design. Drawing that as one bar from 22:30 to 06:00 would run backwards, so it becomes the two
 * pieces it really is — the evening and the small hours — and the caller draws both.
 */
export function dayPieces(start: unknown, end: unknown): DayPiece[] {
  const from = minutesOfDay(start);
  const to = minutesOfDay(end);
  if (from === undefined || to === undefined) return [];
  if (from === to) return [{ fromMinutes: 0, toMinutes: MINUTES_PER_DAY }];
  if (from < to) return [{ fromMinutes: from, toMinutes: to }];
  return [
    { fromMinutes: from, toMinutes: MINUTES_PER_DAY },
    { fromMinutes: 0, toMinutes: to },
  ];
}

export function windowClock(start: unknown, end: unknown): string {
  const from = minutesOfDay(start);
  const to = minutesOfDay(end);
  if (from === undefined || to === undefined) return "no usable times";
  return `${clockLabel(from)} – ${clockLabel(to)}`;
}

function knownWeekdays(value: unknown): Weekday[] {
  if (!Array.isArray(value)) return [];
  const found = value.filter((item): item is Weekday => typeof item === "string" && (WEEKDAYS as string[]).includes(item));
  return WEEKDAYS.filter((day) => found.includes(day));
}

/** Folds a standalone sentence into a longer one without lowercasing the names inside it. */
function lowerFirst(sentence: string): string {
  return sentence.charAt(0).toLowerCase() + sentence.slice(1);
}

function joinWords(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "every day", "on weekdays", "at the weekend", or the days themselves. */
export function describeWeekdays(days: Weekday[]): string {
  if (!days.length || days.length === 7) return "every day";
  const set = new Set(days);
  const weekdaysOnly = days.length === 5 && ["monday", "tuesday", "wednesday", "thursday", "friday"].every((day) => set.has(day as Weekday));
  if (weekdaysOnly) return "on weekdays";
  if (days.length === 2 && set.has("saturday") && set.has("sunday")) return "at the weekend";
  return `on ${joinWords(days.map((day) => SHORT_WEEKDAY[day]))}`;
}

/**
 * How often something recurs, in a sentence.
 *
 * `timesPerPeriod` counts days over a week or a month and occurrences *inside* the day over a
 * day, which is the reading the expander uses — a working day split into four blocks and a pill
 * taken twice are both the daily one. Saying "4 days a day" would be nonsense, so the phrasing
 * follows the period.
 */
export function describeCadence(cadence: RawCadence | undefined): string {
  if (!cadence?.period) return "on an unreadable cadence";
  const times = Math.max(1, Math.trunc(cadence.timesPerPeriod ?? 1));
  const every = Math.max(1, Math.trunc(cadence.everyNPeriods ?? 1));
  const period = cadence.period;
  let head: string;
  if (period === "day") head = times === 1 ? "Once a day" : `${times} times a day`;
  else if (times >= 7 && period === "week") head = "Every day";
  else head = times === 1 ? `Once a ${period}` : `${times} days a ${period}`;
  if (every > 1) head += every === 2 ? `, every other ${period}` : `, every ${every} ${period}s`;
  const days = knownWeekdays(cadence.weekdays);
  if (days.length && days.length < 7) head += ` ${describeWeekdays(days)}`;
  const window = windowClock(cadence.windowStart, cadence.windowEnd);
  return window === "no usable times" ? head : `${head}, between ${window}`;
}

function isoDate(value: unknown): string | undefined {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) return undefined;
  const stamp = Date.parse(`${value.trim()}T00:00:00Z`);
  return Number.isNaN(stamp) ? undefined : value.trim();
}

/** `[year, month, day]` from an ISO date already known to be well formed. */
function dateParts(value: string): [number, number, number] {
  const parts = value.split("-").map(Number);
  return [parts[0] ?? 1970, parts[1] ?? 1, parts[2] ?? 1];
}

function dayNumber(value: string): number {
  return Math.round(Date.parse(`${value}T00:00:00Z`) / MILLISECONDS_PER_DAY);
}

function fromDayNumber(day: number): string {
  return new Date(day * MILLISECONDS_PER_DAY).toISOString().slice(0, 10);
}

/**
 * Calendar-month arithmetic, clamped the way the expander clamps it.
 *
 * The Python side computes the end of the horizon as `add_months`, which keeps the day of the
 * month and falls back to the last day where that month is shorter. Anything else here and the
 * preview would promise a different number of days from the one the import produces.
 */
export function addMonths(start: string, months: number): string {
  const [year, month, day] = dateParts(start);
  const total = year * 12 + (month - 1) + months;
  const endYear = Math.floor(total / 12);
  const endMonth = total - endYear * 12;
  const lastDay = new Date(Date.UTC(endYear, endMonth + 1, 0)).getUTCDate();
  const clamped = Math.min(day, lastDay);
  return `${String(endYear).padStart(4, "0")}-${String(endMonth + 1).padStart(2, "0")}-${String(clamped).padStart(2, "0")}`;
}

export function formatDate(value: string): string {
  const [year, month, day] = dateParts(value);
  return `${day} ${SHORT_MONTHS[month - 1] ?? "?"} ${year}`;
}

/** Month boundaries across the horizon, as fractions of its width. */
export function monthTicks(start: string, endExclusive: string): MonthTick[] {
  const first = dayNumber(start);
  const last = dayNumber(endExclusive);
  const span = last - first;
  if (span <= 0) return [];
  const ticks: MonthTick[] = [];
  let [year, month] = dateParts(start);
  let cursor = start;
  while (dayNumber(cursor) < last) {
    const fraction = (dayNumber(cursor) - first) / span;
    ticks.push({
      fraction,
      label: SHORT_MONTHS[month - 1] ?? "?",
      year: ticks.length === 0 || month === 1 ? String(year) : undefined,
    });
    month += 1;
    if (month > 12) { month = 1; year += 1; }
    cursor = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-01`;
  }
  return ticks;
}

/** Rows for bars that must not overlap, filled greedily so the tallest stack stays shortest. */
function assignLanes<T extends { fromFraction: number; toFraction: number }>(items: T[]): Array<T & { lane: number }> {
  const ends: number[] = [];
  return items.map((item) => {
    let lane = ends.findIndex((end) => end <= item.fromFraction);
    if (lane === -1) { lane = ends.length; ends.push(0); }
    ends[lane] = item.toFraction;
    return { ...item, lane };
  });
}

function labelOf(id: string | undefined, labels: Map<string, string>): string {
  if (!id) return "an activity";
  return labels.get(id) ?? id;
}

function readBands(raw: RawHabit[], labels: Map<string, string>, gaps: string[]): BandView[] {
  return raw.map((habit, index) => {
    const pieces = dayPieces(habit.windowStart, habit.windowEnd);
    const id = habit.habitId ?? `band-${index}`;
    if (!pieces.length) gaps.push(`The band “${habit.label ?? id}” has no readable start and end time, so it is not drawn on the day.`);
    const weekdays = knownWeekdays(habit.weekdays);
    return {
      id,
      label: habit.label ?? id,
      pieces,
      clock: windowClock(habit.windowStart, habit.windowEnd),
      weekdays,
      weekdayPhrase: describeWeekdays(weekdays),
      activityLabels: (habit.recurringActivityIds ?? []).map((activityId) => labelOf(activityId, labels)),
      note: habit.note ?? "",
      wraps: pieces.length > 1,
    };
  });
}

/**
 * A commitment's own dates matter only where they are narrower than the horizon.
 *
 * An outline generated for a fixed period routinely stamps that same period onto the job and the
 * evening class, and saying "only from 1 Sep 2026 to 31 Aug 2027" about a horizon that runs from
 * 1 Sep 2026 to 31 Aug 2027 announces a restriction nobody imposed. Only a genuinely shorter
 * stretch — the course that ends in December — is worth a clause.
 */
function datedClause(commitment: RawCommitment, start: string, endExclusive: string): string {
  const from = isoDate(commitment.startDate);
  const to = isoDate(commitment.endDate);
  const opensLate = from !== undefined && dayNumber(from) > dayNumber(start);
  const endsEarly = to !== undefined && dayNumber(to) < dayNumber(endExclusive) - 1;
  if (!opensLate && !endsEarly) return "";
  if (opensLate && endsEarly) return `, only from ${formatDate(from)} to ${formatDate(to)}`;
  return opensLate ? `, only from ${formatDate(from)}` : `, only until ${formatDate(to as string)}`;
}

/**
 * One spine per shape of day, rather than one spine with the shapes painted over each other.
 *
 * A band scoped to Wednesday and a band scoped to the weekend can both claim 09:00–18:00 without
 * contradicting anything: they are the same hours of two different days. On one track the second
 * simply covers the first, and a whole work-from-home day disappears behind a Saturday.
 *
 * The unscoped bands come first, because they are the day the others are variations of.
 */
export function groupBands(bands: BandView[]): BandRow[] {
  const rows = new Map<string, BandRow>();
  for (const band of bands) {
    if (!band.pieces.length) continue;
    const key = band.weekdays.join(",");
    const existing = rows.get(key);
    if (existing) existing.bands.push(band);
    else rows.set(key, { key, label: band.weekdays.length ? band.weekdayPhrase : "Every day", bands: [band] });
  }
  return [...rows.values()].sort((left, right) => {
    if (!left.key) return -1;
    if (!right.key) return 1;
    return WEEKDAYS.indexOf(left.bands[0]!.weekdays[0]!) - WEEKDAYS.indexOf(right.bands[0]!.weekdays[0]!);
  });
}

function readCommitments(raw: RawCommitment[], start: string, endExclusive: string, gaps: string[]): CommitmentView[] {
  return raw.map((commitment, index) => {
    const pieces = dayPieces(commitment.startTime, commitment.endTime);
    const id = commitment.commitmentId ?? `commitment-${index}`;
    if (!pieces.length) gaps.push(`The commitment “${commitment.label ?? id}” has no readable hours, so it is not drawn on the day.`);
    const weekdays = knownWeekdays(commitment.weekdays);
    const clock = windowClock(commitment.startTime, commitment.endTime);
    const dated = datedClause(commitment, start, endExclusive);
    return {
      id,
      label: commitment.label ?? id,
      pieces,
      clock,
      weekdays,
      weekdayPhrase: describeWeekdays(weekdays),
      sentence: `${clock} ${describeWeekdays(weekdays)}${dated}`,
      note: commitment.note ?? "",
    };
  });
}

function readActivity(activity: RawActivity, fallbackId: string, gaps: string[]): ActivityView {
  const id = activity.recurringActivityId ?? fallbackId;
  const cadence = activity.cadence;
  const pieces = dayPieces(cadence?.windowStart, cadence?.windowEnd);
  if (!pieces.length) gaps.push(`“${activity.label ?? id}” has no readable window, so it is not drawn on the day.`);
  const jitter = cadence?.jitterMinutes;
  const kind: ActivityKind = activity.kind ?? "contextual";
  return {
    id,
    label: activity.label ?? id,
    kind,
    pieces,
    clock: windowClock(cadence?.windowStart, cadence?.windowEnd),
    weekdays: knownWeekdays(cadence?.weekdays),
    sentence: describeCadence(cadence),
    spread: typeof jitter === "number" && jitter > 0 ? `starts anywhere in the window, give or take ${jitter} minutes` : "starts at the same point in the window each time",
    note: activity.note ?? "",
    order: pieces[0]?.fromMinutes ?? MINUTES_PER_DAY + KIND_ORDER[kind],
  };
}

function byWindow<T extends ActivityView>(views: T[]): T[] {
  return views.sort((left, right) => left.order - right.order || left.label.localeCompare(right.label));
}

function readActivities(raw: RawActivity[], gaps: string[]): ActivityView[] {
  return byWindow(raw.map((activity, index) => readActivity(activity, `activity-${index}`, gaps)));
}

function readPhases(raw: RawPhase[], start: string, endExclusive: string, labels: Map<string, string>, gaps: string[]): PhaseView[] {
  const first = dayNumber(start);
  const span = dayNumber(endExclusive) - first;
  const placed = raw.flatMap((phase, index) => {
    const id = phase.phaseId ?? `phase-${index}`;
    const from = isoDate(phase.startDate);
    const to = isoDate(phase.endDate);
    if (!from || !to || span <= 0) {
      gaps.push(`The stretch “${phase.label ?? id}” has no readable dates, so it is not drawn on the calendar.`);
      return [];
    }
    const outside = dayNumber(to) < first || dayNumber(from) >= first + span;
    if (outside) gaps.push(`The stretch “${phase.label ?? id}” falls outside the horizon and will change nothing.`);
    const changes = (phase.activityOverrides ?? []).map((override) => override.suspended
      ? `${labelOf(override.recurringActivityId, labels)} stops`
      : `${labelOf(override.recurringActivityId, labels)} changes to: ${lowerFirst(describeCadence(override.cadence ?? undefined))}`);
    return [{
      id,
      label: phase.label ?? id,
      fromFraction: Math.max(0, Math.min(1, (dayNumber(from) - first) / span)),
      toFraction: Math.max(0, Math.min(1, (dayNumber(to) + 1 - first) / span)),
      sentence: `${formatDate(from)} → ${formatDate(to)}`,
      changes,
      note: phase.note ?? "",
    }];
  });
  return assignLanes(placed.sort((left, right) => left.fromFraction - right.fromFraction));
}

function readEvents(raw: RawEvent[], start: string, endExclusive: string, labels: Map<string, string>, gaps: string[]): EventView[] {
  const first = dayNumber(start);
  const span = dayNumber(endExclusive) - first;
  const placed = raw.flatMap((event, index) => {
    const id = event.eventId ?? `event-${index}`;
    const from = isoDate(event.earliestDate);
    const to = isoDate(event.latestDate);
    if (!from || !to || span <= 0) {
      gaps.push(`The one-off “${event.label ?? id}” has no readable dates, so it is not drawn on the calendar.`);
      return [];
    }
    const times = Math.max(1, Math.trunc(event.occurrences ?? 1));
    const window = windowClock(event.windowStart, event.windowEnd);
    const weekdays = knownWeekdays(event.weekdays);
    const dayPhrase = describeWeekdays(weekdays) === "every day" ? "on any day" : describeWeekdays(weekdays);
    const clock = window === "no usable times" ? "" : `, between ${window}`;
    return [{
      id,
      label: event.label ?? id,
      fromFraction: Math.max(0, Math.min(1, (dayNumber(from) - first) / span)),
      toFraction: Math.max(0, Math.min(1, (dayNumber(to) + 1 - first) / span)),
      sentence: `${times === 1 ? "Once" : `${times} times`} between ${formatDate(from)} and ${formatDate(to)}, ${dayPhrase}${clock}`,
      displaces: (event.displaces ?? []).map((item) => item.policy === "reschedule"
        ? `${labelOf(item.recurringActivityId, labels)} moves to another day`
        : `${labelOf(item.recurringActivityId, labels)} is skipped that day`),
      note: event.note ?? "",
    }];
  });
  return assignLanes(placed.sort((left, right) => left.fromFraction - right.fromFraction));
}

/**
 * What actually differs between a Monday and a Sunday.
 *
 * Only things scoped to some days but not all: a band or a habit that runs every day tells you
 * nothing about the shape of the week, and listing it under all seven columns would bury the two
 * entries that do.
 */
function readWeek(bands: BandView[], commitments: CommitmentView[], activities: ActivityView[]): WeekColumn[] {
  const columns: WeekColumn[] = WEEKDAYS.map((weekday) => ({ weekday, short: SHORT_WEEKDAY[weekday], entries: [] }));
  const add = (days: Weekday[], label: string, kind: WeekColumn["entries"][number]["kind"]) => {
    if (!days.length || days.length === 7) return;
    for (const day of days) columns[WEEKDAYS.indexOf(day)]?.entries.push({ label, kind });
  };
  for (const commitment of commitments) add(commitment.weekdays, commitment.label, "commitment");
  for (const activity of activities) add(activity.weekdays, activity.label, "activity");
  for (const band of bands) add(band.weekdays, band.label, "band");
  return columns;
}

function describeAuthor(provenance: RawOutline["provenance"]): string {
  const model = provenance?.modelName;
  const written = model ? `Written by ${model}` : provenance?.authorType === "human" ? "Written by hand" : "Written by a language model";
  const when = provenance?.generatedAt && !Number.isNaN(Date.parse(provenance.generatedAt))
    ? ` on ${formatDate(new Date(provenance.generatedAt).toISOString().slice(0, 10))}`
    : "";
  return `${written}${when}`;
}

/**
 * Every intent the outline names, and whether the package beside it says how to perform one.
 *
 * The server reaches the same conclusion, but only after expanding the horizon into days and
 * compiling every one of them — minutes of work to learn that one activity has no process behind
 * it. The check costs nothing here and is exactly what the reader is being asked to confirm.
 *
 * It is one-directional on purpose. A package must also implement the intents the resident's own
 * rhythm emits — sleeping and waking among them — which the outline never mentions, so a clean
 * result here is not a promise that the server will accept the file.
 */
function readBehaviour(residents: RawResident[], household: RawHousehold, pack: RawPackage): BehaviourView {
  const bound = new Set((pack.bindings ?? []).map((binding) => binding.intent).filter((intent): intent is string => !!intent));
  const named = new Set<string>();
  for (const resident of residents) {
    for (const activity of resident.profile?.recurringActivities ?? []) if (activity.intent) named.add(activity.intent);
    for (const commitment of resident.fixedCommitments ?? []) if (commitment.intent) named.add(commitment.intent);
    for (const event of resident.events ?? []) if (event.intent) named.add(event.intent);
  }
  for (const joint of household.jointActivities ?? []) if (joint.activity?.intent) named.add(joint.activity.intent);
  return {
    processCount: (pack.processModels ?? []).length,
    namedIntents: named.size,
    unimplemented: [...named].filter((intent) => !bound.has(intent)).sort(),
  };
}

/**
 * Read one parsed JSON document as the horizon the outline prompt produces.
 *
 * That prompt returns an envelope — the outline, and the process package saying how its intents
 * are performed — so `horizon_authoring_bundle` is the ordinary shape of this file and the bare
 * `horizon_outline` inside it is the other one. Both are read here. A document that is plainly
 * neither is refused by name rather than drawn as an empty horizon.
 */
export function readOutline(value: unknown): OutlineReadResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { kind: "other", message: "This file does not contain a single JSON object, so there is nothing to read." };
  }
  const envelope = value as RawBundle;
  const wrapped = envelope.outline && typeof envelope.outline === "object" && !Array.isArray(envelope.outline);
  const raw = (wrapped ? envelope.outline : value) as RawOutline;
  const pack = wrapped ? envelope.personalProcessPackage : undefined;
  const documentType = wrapped ? envelope.documentType : raw.documentType;

  if (documentType && documentType !== "horizon_outline" && documentType !== "horizon_authoring_bundle") {
    const named = documentType === "simulation_authoring_bundle"
      ? " It is a complete authoring bundle: choose it under “Simulation authoring bundle” instead."
      : "";
    return { kind: "other", message: `This file says it is “${documentType}”, which is neither a horizon outline nor the bundle that carries one.${named}` };
  }
  if (!documentType && !raw.profile && !raw.habits && !Array.isArray(raw.residents)) {
    return { kind: "other", message: "This file does not look like a horizon outline: it has no document type, no residents, no behavioural profile and no habit bands." };
  }

  const gaps: string[] = [];
  const { residents: rawResidents, household } = rosterOf(raw, gaps);
  const labels = new Map<string, string>();
  const remember = (activity: RawActivity | undefined) => {
    if (activity?.recurringActivityId) labels.set(activity.recurringActivityId, activity.label ?? activity.recurringActivityId);
  };
  // Activity identifiers are unique across the whole document, so a phase of one resident may
  // name an activity the household does together, and one map serves every lookup.
  for (const resident of rawResidents) for (const activity of resident.profile?.recurringActivities ?? []) remember(activity);
  for (const joint of household.jointActivities ?? []) remember(joint.activity);

  const start = isoDate(raw.startDate);
  const months = typeof raw.months === "number" && raw.months >= 1 ? Math.trunc(raw.months) : 1;
  if (!start) gaps.push("The outline has no readable start date, so the calendar below starts from today.");
  const startDate = start ?? new Date().toISOString().slice(0, 10);
  const endExclusive = addMonths(startDate, months);
  const dayCount = dayNumber(endExclusive) - dayNumber(startDate);
  const lastDate = fromDayNumber(dayNumber(endExclusive) - 1);

  const residents = rawResidents.map((resident, index) => {
    const own: string[] = [];
    const reading = readResident(resident, index, rawResidents.length, startDate, endExclusive, labels, own);
    // With one person every line is about them; with several, a line has to say whose it is.
    gaps.push(...own.map((gap) => rawResidents.length > 1 ? `${reading.name}: ${gap}` : gap));
    return reading;
  });
  const locations = raw.world?.locations ?? [];

  return {
    kind: "outline",
    reading: {
      title: raw.title ?? "Untitled horizon",
      behaviour: pack ? readBehaviour(rawResidents, household, pack) : undefined,
      residents,
      household: readHousehold(household, residents, gaps),
      timeZone: raw.timeZone ?? "an unstated time zone",
      startDate,
      lastDate,
      spanPhrase: `${formatDate(startDate)} → ${formatDate(lastDate)}`,
      dayCount,
      months,
      authorPhrase: describeAuthor(raw.provenance),
      humanReviewed: raw.provenance?.humanReviewed === true,
      monthTicks: monthTicks(startDate, endExclusive),
      rooms: locations.filter((item) => item.kind === "room").map((item) => item.locationId ?? "?"),
      // A composite is a grouping of rooms — `home` — and neither a room nor somewhere to travel to.
      elsewhere: locations.filter((item) => item.kind && item.kind !== "room" && item.kind !== "composite").map((item) => item.locationId ?? "?"),
      usedIntents: usedIntents(rawResidents, household),
      proposals: readProposals(raw.vocabularyProposals, pack),
      furniture: (raw.world?.resources ?? []).flatMap((item) => item.resourceType
        ? [{ resourceId: item.resourceId ?? item.resourceType, resourceType: item.resourceType, room: item.locationId ?? "?" }]
        : []),
      people: (raw.world?.externalPeople ?? []).map((person) => person.displayName ?? person.externalPersonId ?? "someone"),
      note: raw.note ?? "",
      gaps,
    },
  };
}

function usedIntents(residents: RawResident[], household: RawHousehold): string[] {
  const used = new Set<string>();
  for (const resident of residents) {
    for (const activity of resident.profile?.recurringActivities ?? []) if (activity.intent) used.add(activity.intent);
    for (const commitment of resident.fixedCommitments ?? []) if (commitment.intent) used.add(commitment.intent);
    for (const event of resident.events ?? []) if (event.intent) used.add(event.intent);
  }
  for (const joint of household.jointActivities ?? []) if (joint.activity?.intent) used.add(joint.activity.intent);
  return [...used].sort();
}

function countSteps(model: RawProcessModel | undefined): number {
  return (model?.nodes ?? []).filter((node) => node.kind === "action").length;
}

/**
 * What the author asks to add, with what the package already says about it.
 *
 * An activity proposal is only half written in the outline: how it is performed is in the process
 * package, bound to the proposed intent like any other. The first model bound to it is kept, so
 * accepting the proposal starts the vocabulary entry from the author's own steps rather than from
 * a blank activity the researcher has to rebuild.
 */
function readProposals(raw: RawVocabularyProposals | undefined, pack: RawPackage | undefined): ProposalsView {
  const models = new Map((pack?.processModels ?? []).flatMap((model) => model.processModelId ? [[model.processModelId, model] as const] : []));
  const modelsByIntent: Record<string, RawProcessModel> = {};
  for (const binding of pack?.bindings ?? []) {
    const model = binding.processModelId ? models.get(binding.processModelId) : undefined;
    if (binding.intent && model && !modelsByIntent[binding.intent]) modelsByIntent[binding.intent] = model;
  }
  const text = (value: unknown, fallback: string) => typeof value === "string" && value.trim() ? value : fallback;
  return {
    furniture: (raw?.furniture ?? []).flatMap((item) => item.entityType ? [{
      entityType: item.entityType,
      displayName: text(item.displayName, item.entityType.replace(/_/g, " ")),
      capabilities: (item.capabilities ?? []).filter((value): value is string => typeof value === "string"),
      contactInstrumented: item.contactInstrumented === true,
      rationale: text(item.rationale, ""),
    }] : []),
    activities: (raw?.activities ?? []).flatMap((item) => item.intentId ? [{
      intentId: item.intentId,
      label: text(item.label, item.intentId.replace(/_/g, " ")),
      category: text(item.category, "leisure"),
      defaultLocation: text(item.defaultLocation, "living_room"),
      description: text(item.description, ""),
      rationale: text(item.rationale, ""),
      processModel: modelsByIntent[item.intentId],
      steps: countSteps(modelsByIntent[item.intentId]),
    }] : []),
    modelsByIntent,
  };
}

/**
 * The people of the outline, whichever version wrote them down.
 *
 * A 2.0.0 document lists them; a 1.x one kept its single person at the top level, and is lifted
 * into a roster of one exactly as the server lifts it before expanding, so the picture never
 * disagrees with the import about who lives here.
 */
function rosterOf(raw: RawOutline, gaps: string[]): { residents: RawResident[]; household: RawHousehold } {
  if (Array.isArray(raw.residents)) {
    const residents = raw.residents.filter((item): item is RawResident => !!item && typeof item === "object" && !Array.isArray(item));
    if (residents.length) return { residents, household: raw.household ?? {} };
    gaps.push("The outline declares no resident, so there is nobody whose days could be expanded.");
    return { residents: [{}], household: raw.household ?? {} };
  }
  return {
    residents: [{
      residentId: raw.residentId,
      displayName: raw.displayName,
      profile: raw.profile,
      rhythm: raw.rhythm,
      habits: raw.habits,
      fixedCommitments: raw.fixedCommitments,
      phases: raw.phases,
      events: raw.events,
    }],
    household: {},
  };
}

function readResident(raw: RawResident, index: number, count: number, startDate: string, endExclusive: string, labels: Map<string, string>, gaps: string[]): ResidentReading {
  const residentId = raw.residentId ?? (count === 1 ? "unnamed resident" : `resident ${index + 1}`);
  const bands = readBands(raw.habits ?? [], labels, gaps);
  const commitments = readCommitments(raw.fixedCommitments ?? [], startDate, endExclusive, gaps);
  const activities = readActivities(raw.profile?.recurringActivities ?? [], gaps);
  const week = readWeek(bands, commitments, activities);
  return {
    residentId,
    name: raw.displayName?.trim() || residentId,
    age: typeof raw.rhythm?.age === "number" ? raw.rhythm.age : undefined,
    health: (raw.rhythm?.health ?? []).filter((item): item is string => typeof item === "string"),
    bedtime: minutesOfDay(raw.rhythm?.chronotypeBedtime) === undefined ? undefined : raw.rhythm?.chronotypeBedtime,
    bands,
    bandRows: groupBands(bands),
    commitments,
    activities,
    week,
    weekVaries: week.some((column) => column.entries.length > 0),
    phases: readPhases(raw.phases ?? [], startDate, endExclusive, labels, gaps),
    events: readEvents(raw.events ?? [], startDate, endExclusive, labels, gaps),
    note: raw.note ?? "",
  };
}

const RELATION_PHRASE: Record<RelationKind, (first: string, second: string) => string> = {
  couple: (first, second) => `${first} and ${second} are a couple`,
  housemates: (first, second) => `${first} and ${second} share the home as housemates`,
  // The only asymmetric kind: the schema reads the first of `between` as the parent.
  parent_child: (first, second) => `${first} is ${second}’s parent`,
  siblings: (first, second) => `${first} and ${second} are siblings`,
  other: (first, second) => `${first} and ${second} live together`,
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/**
 * How often a shared activity is really shared, in the words of the class of day it depends on.
 *
 * The weekday and weekend figures exist because one average fabricates a pattern — shared evenings
 * scattered through a working week that only ever had them on Saturday — so the sentence keeps
 * the two apart whenever the outline did.
 */
function describeTogether(sharing: SharingMode | undefined, propensity: { default?: number; weekday?: number | null; weekend?: number | null } | null | undefined): string {
  if (sharing !== "optional_joint") return "Always together";
  const base = typeof propensity?.default === "number" ? propensity.default : undefined;
  const weekday = typeof propensity?.weekday === "number" ? propensity.weekday : base;
  const weekend = typeof propensity?.weekend === "number" ? propensity.weekend : base;
  if (weekday === undefined || weekend === undefined) return "Sometimes together, in a proportion the outline does not state";
  if (weekday === weekend) return `Together on ${percent(weekday)} of days`;
  return `Together on ${percent(weekday)} of weekdays and ${percent(weekend)} of weekend days`;
}

function readHousehold(raw: RawHousehold, residents: ResidentReading[], gaps: string[]): HouseholdView {
  const names = new Map(residents.map((resident) => [resident.residentId, resident.name]));
  // A name the roster does not hold is written as the model wrote it and reported, because the
  // server refuses exactly this, and a sentence about somebody who does not live here would
  // otherwise read as perfectly sensible.
  const nameOf = (id: string | undefined, where: string): string => {
    if (!id) {
      gaps.push(`${where} names a resident without an identifier.`);
      return "someone";
    }
    if (!names.has(id)) gaps.push(`${where} names “${id}”, who is not among the residents.`);
    return names.get(id) ?? id;
  };
  const pair = (between: string[] | undefined, where: string): [string, string] => {
    const [first, second] = between ?? [];
    return [nameOf(first, where), nameOf(second, where)];
  };

  const relations = (raw.relations ?? []).map((relation, index) => {
    const [first, second] = pair(relation.between, `Relation ${index + 1}`);
    const phrase = (relation.kind && RELATION_PHRASE[relation.kind]) || RELATION_PHRASE.other;
    return `${phrase(first, second)}${relation.note ? ` — ${relation.note}` : ""}`;
  });

  const joint = byWindow((raw.jointActivities ?? []).map((item, index) => {
    const view = readActivity(item.activity ?? {}, `joint-activity-${index}`, gaps);
    const participants = (item.participantIds ?? []).map((id) => nameOf(id, `The shared “${view.label}”`));
    if (participants.length < 2) gaps.push(`The shared “${view.label}” names fewer than two participants, so nothing about it is shared.`);
    const minimum = typeof item.minimumSharedMinutes === "number" && item.minimumSharedMinutes > 0
      ? ` if they overlap for at least ${item.minimumSharedMinutes} minutes`
      : "";
    return {
      ...view,
      participants,
      together: `${describeTogether(item.sharing, item.propensity)}${minimum}`,
      fallback: item.degradeToIndependent === false
        ? "Never done apart: on a day it does not fit, the day has to make room for it"
        : "Done separately on a day the shared version does not fit",
      note: item.note || view.note,
    };
  }));

  const policies = (raw.sharingPolicies ?? []).map((policy, index) => {
    const [first, second] = pair(policy.between, `Sharing rule ${index + 1}`);
    const intent = policy.intent ?? "an unnamed intent";
    const rule = policy.sharing === "exclusive"
      ? `When ${first} or ${second} does ${intent}, the other leaves the room`
      : `${first} and ${second} each do ${intent} on their own, and only contend for what they both use`;
    return `${rule}${policy.note ? ` — ${policy.note}` : ""}`;
  });

  const privacy = (raw.locationPrivacy ?? []).map((rule, index) => {
    const room = rule.locationId ? `the ${rule.locationId.replace(/_/g, " ")}` : "an unnamed room";
    const where = `Privacy rule ${index + 1}`;
    const subject = nameOf(rule.subjectId, where);
    const excluded = (rule.excludedResidentIds ?? []).map((id) => nameOf(id, where));
    const who = excluded.length ? `${joinWords(excluded)} may not` : "Nobody else may";
    const doing = rule.intents?.length ? ` for ${joinWords(rule.intents)}` : "";
    const reverse = rule.symmetric === false ? "" : ", and the other way round";
    return `${who} be in ${room} while ${subject} uses it${doing}${reverse}${rule.note ? ` — ${rule.note}` : ""}`;
  });

  return {
    relations,
    joint,
    policies,
    privacy,
    sharedRooms: (raw.sharedLocationIds ?? []).map((id) => id.replace(/_/g, " ")),
  };
}

/**
 * Read a chosen file as a horizon outline, without ever rejecting the user's choice loudly.
 *
 * The preview is an offer, not a gate: whatever comes back, the import button stays exactly as
 * usable as it was, and the server remains the thing that decides whether the outline is valid.
 */
export async function readOutlineFile(file: File): Promise<OutlineReadResult> {
  if (file.size > 50 * 1024 * 1024) {
    return { kind: "other", message: "This file is larger than 50 MiB, which is far larger than any outline; it is not previewed here." };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(await file.text()) as unknown;
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : String(reason);
    return { kind: "other", message: `This file is not valid JSON: ${detail}. Save only the model's response, with no Markdown fence around it.` };
  }
  return readOutline(parsed);
}
