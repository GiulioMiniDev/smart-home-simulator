import { describe, expect, it } from "vitest";
import { addMonths, clockLabel, dayPieces, describeCadence, describeWeekdays, groupBands, minutesOfDay, monthTicks, readOutline, readOutlineFile, windowClock } from "../horizon/reading";
import type { RawOutline } from "../horizon/types";

function outline(overrides: Partial<RawOutline> = {}): RawOutline {
  return {
    documentType: "horizon_outline",
    outlineId: "case-1",
    title: "Eight months on Long Island",
    residentId: "meredith",
    timeZone: "America/New_York",
    startDate: "2026-08-03",
    months: 8,
    world: {
      locations: [
        { locationId: "bedroom", kind: "room" },
        { locationId: "kitchen", kind: "room" },
        { locationId: "supermarket", kind: "external" },
      ],
      externalPeople: [{ externalPersonId: "sister", displayName: "Anna" }],
      startLocationId: "bedroom",
    },
    profile: {
      recurringActivities: [
        { recurringActivityId: "sleep", label: "Sleep", kind: "anchor", cadence: { period: "day", timesPerPeriod: 1, windowStart: "22:30", windowEnd: "06:30", jitterMinutes: 25 } },
        { recurringActivityId: "run", label: "Morning run", kind: "optional", cadence: { period: "week", timesPerPeriod: 3, weekdays: ["monday", "wednesday", "friday"], windowStart: "07:00", windowEnd: "09:00" } },
      ],
    },
    rhythm: { age: 45, health: [], chronotypeBedtime: "22:30" },
    habits: [
      { habitId: "night", label: "Night", windowStart: "22:30", windowEnd: "06:00", recurringActivityIds: ["sleep"] },
      { habitId: "morning", label: "Morning", windowStart: "06:00", windowEnd: "09:00", recurringActivityIds: ["run"] },
    ],
    fixedCommitments: [
      { commitmentId: "salon", label: "Hair salon", weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"], startTime: "09:00", endTime: "17:00" },
    ],
    phases: [
      { phaseId: "heat", label: "Late-summer heat", startDate: "2026-08-03", endDate: "2026-09-06", activityOverrides: [{ recurringActivityId: "run", cadence: { period: "week", timesPerPeriod: 2, windowStart: "06:00", windowEnd: "07:30" } }] },
    ],
    events: [
      { eventId: "dentist", label: "Dentist", earliestDate: "2026-10-05", latestDate: "2026-10-30", occurrences: 1, windowStart: "09:00", windowEnd: "12:00", displaces: [{ recurringActivityId: "run", policy: "skip" }] },
    ],
    provenance: { authorType: "external_llm", modelName: "GPT-5.6 Thinking", generatedAt: "2026-08-03T10:00:00Z", humanReviewed: true },
    ...overrides,
  };
}

function read(document: RawOutline | unknown) {
  const result = readOutline(document);
  if (result.kind !== "outline") throw new Error(`expected an outline, got: ${result.message}`);
  return result.reading;
}

describe("clock arithmetic", () => {
  it("reads the times an outline is allowed to write", () => {
    expect(minutesOfDay("22:30")).toBe(1350);
    expect(minutesOfDay("6:05")).toBe(365);
    expect(minutesOfDay("00:00")).toBe(0);
    expect(minutesOfDay("24:00")).toBe(1440);
  });

  it("refuses anything it cannot place, rather than guessing", () => {
    for (const value of ["9am", "half past six", "25:00", "07:75", "", null, 700]) {
      expect(minutesOfDay(value)).toBeUndefined();
    }
  });

  it("cuts a window that crosses midnight into the two pieces it really is", () => {
    expect(dayPieces("22:30", "06:00")).toEqual([
      { fromMinutes: 1350, toMinutes: 1440 },
      { fromMinutes: 0, toMinutes: 360 },
    ]);
  });

  it("draws an ordinary window as one piece and an empty one as the whole day", () => {
    expect(dayPieces("07:00", "09:00")).toEqual([{ fromMinutes: 420, toMinutes: 540 }]);
    expect(dayPieces("07:00", "07:00")).toEqual([{ fromMinutes: 0, toMinutes: 1440 }]);
  });

  it("places nothing when either end is unreadable", () => {
    expect(dayPieces("07:00", "noon")).toEqual([]);
    expect(windowClock("07:00", "noon")).toBe("no usable times");
    expect(clockLabel(1350)).toBe("22:30");
  });
});

describe("phrasing", () => {
  it("names the shapes of the week people actually mean", () => {
    expect(describeWeekdays([])).toBe("every day");
    expect(describeWeekdays(["monday", "tuesday", "wednesday", "thursday", "friday"])).toBe("on weekdays");
    expect(describeWeekdays(["saturday", "sunday"])).toBe("at the weekend");
    expect(describeWeekdays(["monday", "wednesday", "friday"])).toBe("on Mon, Wed and Fri");
  });

  it("counts occurrences inside a day but days inside a week, as the expander does", () => {
    expect(describeCadence({ period: "day", timesPerPeriod: 4, windowStart: "09:00", windowEnd: "17:00" }))
      .toBe("4 times a day, between 09:00 – 17:00");
    expect(describeCadence({ period: "week", timesPerPeriod: 3, windowStart: "07:00", windowEnd: "09:00" }))
      .toBe("3 days a week, between 07:00 – 09:00");
  });

  it("says every day when a weekly cadence covers the whole week", () => {
    expect(describeCadence({ period: "week", timesPerPeriod: 7, windowStart: "07:00", windowEnd: "09:00" })).toMatch(/^Every day/);
  });

  it("carries the fortnight and the weekdays into the sentence", () => {
    expect(describeCadence({ period: "week", timesPerPeriod: 1, everyNPeriods: 2, weekdays: ["saturday"], windowStart: "10:00", windowEnd: "12:00" }))
      .toBe("Once a week, every other week on Sat, between 10:00 – 12:00");
    expect(describeCadence({ period: "week", timesPerPeriod: 2, everyNPeriods: 2, weekdays: ["saturday", "sunday"], windowStart: "10:00", windowEnd: "12:00" }))
      .toBe("2 days a week, every other week at the weekend, between 10:00 – 12:00");
  });

  it("does not invent a cadence it was not given", () => {
    expect(describeCadence(undefined)).toBe("on an unreadable cadence");
  });
});

describe("calendar arithmetic", () => {
  it("adds months the way the expander does, clamping short months", () => {
    expect(addMonths("2026-08-03", 8)).toBe("2027-04-03");
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
  });

  it("puts a tick on every month boundary and the year only where it changes", () => {
    const ticks = monthTicks("2026-11-01", "2027-02-01");
    expect(ticks.map((tick) => tick.label)).toEqual(["Nov", "Dec", "Jan"]);
    expect(ticks.map((tick) => tick.year)).toEqual(["2026", undefined, "2027"]);
    expect(ticks[0].fraction).toBe(0);
  });
});

describe("reading a whole outline", () => {
  it("reports the horizon the import will actually produce", () => {
    const reading = read(outline());
    expect(reading.dayCount).toBe(243);
    expect(reading.lastDate).toBe("2027-04-02");
    expect(reading.spanPhrase).toBe("3 Aug 2026 → 2 Apr 2027");
    expect(reading.gaps).toEqual([]);
  });

  it("shows the night band as two pieces and marks it as wrapping", () => {
    const night = read(outline()).bands.find((band) => band.id === "night");
    expect(night?.wraps).toBe(true);
    expect(night?.pieces).toHaveLength(2);
    expect(night?.activityLabels).toEqual(["Sleep"]);
  });

  it("splits the spine once bands belong to different days", () => {
    const scoped = outline({
      habits: [
        { habitId: "night", label: "Night", windowStart: "22:30", windowEnd: "06:00" },
        { habitId: "wfh", label: "Working from home", windowStart: "09:00", windowEnd: "18:00", weekdays: ["wednesday"] },
        { habitId: "weekend", label: "A slow weekend", windowStart: "09:00", windowEnd: "18:30", weekdays: ["saturday", "sunday"] },
      ],
    });
    const rows = read(scoped).bandRows;
    expect(rows.map((row) => row.label)).toEqual(["Every day", "on Wed", "at the weekend"]);
    expect(rows.map((row) => row.bands.length)).toEqual([1, 1, 1]);
  });

  it("keeps bands scoped to the same days on one spine, and drops what it cannot place", () => {
    const rows = groupBands(read(outline({
      habits: [
        { habitId: "morning", label: "Morning", windowStart: "06:00", windowEnd: "09:00", weekdays: ["saturday", "sunday"] },
        { habitId: "afternoon", label: "Afternoon", windowStart: "14:00", windowEnd: "18:00", weekdays: ["saturday", "sunday"] },
        { habitId: "broken", label: "Broken", windowStart: "half six", windowEnd: "09:00" },
      ],
    })).bands);
    expect(rows).toHaveLength(1);
    expect(rows[0].bands.map((band) => band.label)).toEqual(["Morning", "Afternoon"]);
  });

  it("orders the day by when each window opens", () => {
    expect(read(outline()).activities.map((activity) => activity.label)).toEqual(["Morning run", "Sleep"]);
  });

  it("collects only what is tied to particular weekdays", () => {
    const reading = read(outline());
    expect(reading.weekVaries).toBe(true);
    const monday = reading.week[0];
    const sunday = reading.week[6];
    expect(monday.entries.map((entry) => entry.label).sort()).toEqual(["Hair salon", "Morning run"]);
    expect(sunday.entries).toEqual([]);
  });

  it("says so when nothing distinguishes one day of the week from another", () => {
    const flat = outline({ fixedCommitments: [], profile: { recurringActivities: [{ recurringActivityId: "sleep", label: "Sleep", kind: "anchor", cadence: { period: "day", timesPerPeriod: 1, windowStart: "22:30", windowEnd: "06:30" } }] } });
    expect(read(flat).weekVaries).toBe(false);
  });

  it("places stretches and one-offs as fractions of the horizon", () => {
    const reading = read(outline());
    expect(reading.phases[0].fromFraction).toBe(0);
    expect(reading.phases[0].toFraction).toBeCloseTo(35 / 243, 5);
    expect(reading.phases[0].changes[0]).toContain("Morning run changes to:");
    expect(reading.events[0].sentence).toBe("Once between 5 Oct 2026 and 30 Oct 2026, on any day, between 09:00 – 12:00");
    expect(reading.events[0].displaces).toEqual(["Morning run is skipped that day"]);
  });

  it("stacks overlapping stretches into separate lanes", () => {
    const overlapping = outline({
      phases: [
        { phaseId: "a", label: "A", startDate: "2026-08-03", endDate: "2026-10-03" },
        { phaseId: "b", label: "B", startDate: "2026-09-03", endDate: "2026-11-03" },
        { phaseId: "c", label: "C", startDate: "2026-12-03", endDate: "2026-12-20" },
      ],
    });
    expect(read(overlapping).phases.map((phase) => phase.lane)).toEqual([0, 1, 0]);
  });

  it("names what it could not place instead of dropping it", () => {
    const broken = outline({
      habits: [{ habitId: "night", label: "Night", windowStart: "22h30", windowEnd: "06:00" }],
      phases: [{ phaseId: "heat", label: "Late-summer heat", startDate: "next August", endDate: "2026-09-06" }],
    });
    const reading = read(broken);
    expect(reading.bands[0].pieces).toEqual([]);
    expect(reading.phases).toEqual([]);
    expect(reading.gaps).toHaveLength(2);
    expect(reading.gaps[0]).toContain("“Night”");
    expect(reading.gaps[1]).toContain("not drawn on the calendar");
  });

  it("warns when a stretch falls outside the horizon it belongs to", () => {
    const stray = outline({ phases: [{ phaseId: "old", label: "Last winter", startDate: "2025-01-01", endDate: "2025-02-01" }] });
    expect(read(stray).gaps.join(" ")).toContain("falls outside the horizon");
  });

  it("separates the rooms of the flat from the places the resident travels to", () => {
    const reading = read(outline());
    expect(reading.rooms).toEqual(["bedroom", "kitchen"]);
    expect(reading.elsewhere).toEqual(["supermarket"]);
    expect(reading.people).toEqual(["Anna"]);
  });

  it("reports who wrote the file and whether anybody has read it", () => {
    const reading = read(outline());
    expect(reading.authorPhrase).toBe("Written by GPT-5.6 Thinking on 3 Aug 2026");
    expect(reading.humanReviewed).toBe(true);
    expect(read(outline({ provenance: { authorType: "external_llm" } })).humanReviewed).toBe(false);
  });

  it("survives an outline that is missing nearly everything", () => {
    const reading = read({ documentType: "horizon_outline" });
    expect(reading.title).toBe("Untitled horizon");
    expect(reading.activities).toEqual([]);
    expect(reading.dayCount).toBeGreaterThan(27);
    expect(reading.gaps[0]).toContain("no readable start date");
  });
});

describe("an outline the model half-filled in", () => {
  // Everything optional is missing at once: no ids, no labels, no cadences, no dates. This is the
  // shape a truncated or hurried response actually has, and it must still draw something.
  const bare = outline({
    profile: { recurringActivities: [{}] },
    habits: [{}],
    fixedCommitments: [{}],
    phases: [{}],
    events: [{}],
    rhythm: {},
    world: { locations: [{ kind: "room" }, { kind: "external" }], externalPeople: [{ externalPersonId: "neighbour" }], startLocationId: "bedroom" },
    provenance: { authorType: "human" },
  });

  it("falls back to positions where the model gave no identity", () => {
    const reading = read(bare);
    expect(reading.bands[0].id).toBe("band-0");
    expect(reading.commitments[0].label).toBe("commitment-0");
    expect(reading.activities[0].label).toBe("activity-0");
    expect(reading.activities[0].kind).toBe("contextual");
  });

  it("still says what it could not read, one line per thing", () => {
    // The band, the commitment, the activity, the stretch and the one-off: five things, five lines.
    expect(read(bare).gaps).toHaveLength(5);
  });

  it("names the places and people that arrived without names", () => {
    const reading = read(bare);
    expect(reading.rooms).toEqual(["?"]);
    expect(reading.elsewhere).toEqual(["?"]);
    expect(reading.people).toEqual(["neighbour"]);
    expect(reading.age).toBeUndefined();
    expect(reading.bedtime).toBeUndefined();
  });

  it("credits the author it was told about rather than assuming a model", () => {
    expect(read(bare).authorPhrase).toBe("Written by hand");
    expect(read(outline({ provenance: { authorType: "external_llm" } })).authorPhrase).toBe("Written by a language model");
  });

  it("keeps the outline in date order when nothing can be placed on the clock", () => {
    const unplaceable = outline({ profile: { recurringActivities: [
      { recurringActivityId: "b", label: "Second", kind: "rare" },
      { recurringActivityId: "a", label: "First", kind: "rare" },
    ] } });
    expect(read(unplaceable).activities.map((activity) => activity.label)).toEqual(["First", "Second"]);
  });
});

describe("the parts an outline may say more precisely", () => {
  it("carries a suspension, a rescheduling and a dated commitment into words", () => {
    const detailed = outline({
      fixedCommitments: [{ commitmentId: "course", label: "Evening course", weekdays: ["tuesday"], startTime: "18:00", endTime: "20:00", startDate: "2026-09-01", endDate: "2026-12-15" }],
      phases: [{ phaseId: "winter", label: "Winter", startDate: "2026-12-01", endDate: "2027-02-28", activityOverrides: [{ recurringActivityId: "run", suspended: true }] }],
      events: [{ eventId: "flu", label: "A week of flu", earliestDate: "2027-01-11", latestDate: "2027-01-17", occurrences: 5, displaces: [{ recurringActivityId: "run", policy: "reschedule" }, { policy: "skip" }] }],
    });
    const reading = read(detailed);
    expect(reading.commitments[0].sentence).toBe("18:00 – 20:00 on Tue, only from 1 Sep 2026 to 15 Dec 2026");
    expect(reading.phases[0].changes).toEqual(["Morning run stops"]);
    expect(reading.events[0].sentence).toContain("5 times between 11 Jan 2027 and 17 Jan 2027");
    expect(reading.events[0].displaces).toEqual(["Morning run moves to another day", "an activity is skipped that day"]);
  });

  it("keeps quiet about dates that only restate the horizon", () => {
    // Outlines generated for a fixed period routinely stamp that period onto the job as well.
    // Reporting it as a restriction would announce one nobody imposed.
    const stamped = outline({
      fixedCommitments: [{ commitmentId: "office", label: "Office", weekdays: ["monday"], startTime: "09:00", endTime: "17:00", startDate: "2026-08-03", endDate: "2027-04-02" }],
    });
    expect(read(stamped).commitments[0].sentence).toBe("09:00 – 17:00 on Mon");
  });

  it("reports an open-ended restriction from whichever side it has", () => {
    const opensLate = outline({ fixedCommitments: [{ commitmentId: "a", label: "A", weekdays: ["monday"], startTime: "09:00", endTime: "17:00", startDate: "2026-10-01" }] });
    const endsEarly = outline({ fixedCommitments: [{ commitmentId: "b", label: "B", weekdays: ["monday"], startTime: "09:00", endTime: "17:00", endDate: "2026-10-01" }] });
    expect(read(opensLate).commitments[0].sentence).toContain("only from 1 Oct 2026");
    expect(read(endsEarly).commitments[0].sentence).toContain("only until 1 Oct 2026");
  });

  it("folds a cadence into a longer sentence without lowercasing the days inside it", () => {
    const phased = outline({
      phases: [{ phaseId: "summer", label: "Summer", startDate: "2027-01-01", endDate: "2027-02-01", activityOverrides: [{ recurringActivityId: "run", cadence: { period: "week", timesPerPeriod: 2, weekdays: ["wednesday", "sunday"], windowStart: "20:15", windowEnd: "22:15" } }] }],
    });
    expect(read(phased).phases[0].changes[0]).toBe("Morning run changes to: 2 days a week on Wed and Sun, between 20:15 – 22:15");
  });

  it("says how far a start time may drift, and when it may not", () => {
    const reading = read(outline());
    expect(reading.activities.find((activity) => activity.id === "sleep")?.spread).toContain("give or take 25 minutes");
    expect(reading.activities.find((activity) => activity.id === "run")?.spread).toContain("the same point in the window");
  });
});

describe("reading the chosen file", () => {
  function chosen(text: string, size = text.length): File {
    const file = new File([text], "outline.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve(text) });
    Object.defineProperty(file, "size", { value: size });
    return file;
  }

  it("reads an outline straight off the file", async () => {
    const result = await readOutlineFile(chosen(JSON.stringify(outline())));
    expect(result.kind).toBe("outline");
    if (result.kind === "outline") expect(result.reading.dayCount).toBe(243);
  });

  it("explains a Markdown fence rather than reporting a parse failure", async () => {
    const result = await readOutlineFile(chosen("```json\n{}\n```"));
    expect(result.kind).toBe("other");
    if (result.kind === "other") expect(result.message).toContain("no Markdown fence");
  });

  it("declines to read a file no outline could plausibly be", async () => {
    const result = await readOutlineFile(chosen("{}", 60 * 1024 * 1024));
    expect(result.kind).toBe("other");
    if (result.kind === "other") expect(result.message).toContain("larger than 50 MiB");
  });
});

describe("the envelope the outline prompt actually returns", () => {
  // The prompt embeds the Horizon Authoring Bundle schema, so this — not the bare outline — is
  // the ordinary shape of the file a researcher saves and chooses under "Horizon outline and processes".
  function bundle(pack: Record<string, unknown> = {}) {
    return {
      documentType: "horizon_authoring_bundle",
      schemaVersion: "1.0.0",
      outline: outline(),
      personalProcessPackage: {
        documentType: "personal_process_package",
        processModels: [{ processModelId: "pm_sleep" }, { processModelId: "pm_run" }],
        bindings: [{ intent: "sleep", processModelId: "pm_sleep" }, { intent: "go_for_a_run", processModelId: "pm_run" }],
        ...pack,
      },
    };
  }

  it("reads the outline inside the envelope rather than refusing the file", () => {
    const reading = read(bundle());
    expect(reading.title).toBe("Eight months on Long Island");
    expect(reading.dayCount).toBe(243);
  });

  it("counts the processes that say how the intents are performed", () => {
    expect(read(bundle()).behaviour).toEqual({ processCount: 2, namedIntents: 0, unimplemented: [] });
  });

  it("names an intent the outline asks for that no process implements", () => {
    const wrapped = bundle();
    wrapped.outline = outline({
      profile: { recurringActivities: [{ recurringActivityId: "sleep", label: "Sleep", kind: "anchor", intent: "sleep", cadence: { period: "day", timesPerPeriod: 1, windowStart: "22:30", windowEnd: "06:30" } }] },
      fixedCommitments: [{ commitmentId: "salon", label: "Hair salon", weekdays: ["monday"], startTime: "09:00", endTime: "17:00", intent: "work_shift" }],
      events: [{ eventId: "dentist", label: "Dentist", earliestDate: "2026-10-05", latestDate: "2026-10-30", intent: "visit_dentist" }],
    });
    const behaviour = read(wrapped).behaviour;
    expect(behaviour?.namedIntents).toBe(3);
    expect(behaviour?.unimplemented).toEqual(["visit_dentist", "work_shift"]);
  });

  it("reads a bare outline too, and then says nothing about behaviour it was not given", () => {
    expect(read(outline()).behaviour).toBeUndefined();
  });
});

describe("refusing what is not an outline", () => {
  it("names the authoring bundle and points at its own picker", () => {
    const result = readOutline({ documentType: "simulation_authoring_bundle", scenario: {} });
    expect(result.kind).toBe("other");
    if (result.kind === "other") expect(result.message).toContain("Simulation authoring bundle");
  });

  it("refuses documents with no sign of being an outline at all", () => {
    expect(readOutline({ hello: "world" }).kind).toBe("other");
    expect(readOutline([1, 2, 3]).kind).toBe("other");
    expect(readOutline(null).kind).toBe("other");
  });
});
