import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HorizonPreview } from "../horizon/HorizonPreview";
import { readOutline } from "../horizon/reading";
import type { HorizonReading, RawOutline } from "../horizon/types";

const document_: RawOutline = {
  documentType: "horizon_outline",
  title: "Eight months on Long Island",
  residentId: "meredith",
  timeZone: "America/New_York",
  startDate: "2026-08-03",
  months: 8,
  world: { locations: [{ locationId: "bedroom", kind: "room" }, { locationId: "supermarket", kind: "external" }], startLocationId: "bedroom" },
  profile: {
    recurringActivities: [
      { recurringActivityId: "sleep", label: "Sleep", kind: "anchor", cadence: { period: "day", timesPerPeriod: 1, windowStart: "22:30", windowEnd: "06:30" } },
      { recurringActivityId: "run", label: "Morning run", kind: "optional", cadence: { period: "week", timesPerPeriod: 3, weekdays: ["monday", "wednesday", "friday"], windowStart: "07:00", windowEnd: "09:00" } },
    ],
  },
  habits: [{ habitId: "night", label: "Night", windowStart: "22:30", windowEnd: "06:00", recurringActivityIds: ["sleep"] }],
  fixedCommitments: [{ commitmentId: "salon", label: "Hair salon", weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"], startTime: "09:00", endTime: "17:00" }],
  phases: [{ phaseId: "heat", label: "Late-summer heat", startDate: "2026-08-03", endDate: "2026-09-06" }],
  events: [{ eventId: "dentist", label: "Dentist", earliestDate: "2026-10-05", latestDate: "2026-10-30", occurrences: 1, windowStart: "09:00", windowEnd: "12:00" }],
  provenance: { authorType: "external_llm", modelName: "GPT-5.6 Thinking", humanReviewed: false },
};

function reading(overrides: Partial<RawOutline> = {}): HorizonReading {
  const result = readOutline({ ...document_, ...overrides });
  if (result.kind !== "outline") throw new Error(result.message);
  return result.reading;
}

function show(value: HorizonReading = reading(), onImport = vi.fn()) {
  render(<HorizonPreview reading={value} fileName="meredith.horizon-outline.json" busy={false} onImport={onImport} />);
  return onImport;
}

/** jsdom's Blob predates `text()`, so the bytes come back the way the platform used to give them. */
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the horizon preview", () => {
  it("leads with the horizon the import will produce, not with the file", () => {
    show();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Eight months on Long Island");
    expect(screen.getByText(/243 days for/)).toHaveTextContent("3 Aug 2026 → 2 Apr 2027");
    expect(screen.getByText(/meredith\.horizon-outline\.json/)).toBeInTheDocument();
  });

  it("says plainly that nobody has checked the model's file yet", () => {
    show();
    expect(screen.getByText("The file says nobody has read it yet")).toBeInTheDocument();
    expect(screen.getByText("Written by GPT-5.6 Thinking")).toBeInTheDocument();
  });

  it("draws every bar with a sentence a screen reader can read instead", () => {
    show();
    expect(screen.getByRole("img", { name: /Every day, in 1 band: Night, 22:30 – 06:00/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Morning run: 3 days a week on Mon, Wed and Fri, between 07:00 – 09:00" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Hair salon: 09:00 – 17:00 on weekdays/ })).toBeInTheDocument();
  });

  it("shows the week only where the days actually differ", () => {
    show();
    const week = screen.getByText("Mon").closest("div");
    expect(within(week as HTMLElement).getByText("Hair salon")).toBeInTheDocument();
    const sunday = screen.getByText("Sun").closest("div");
    expect(within(sunday as HTMLElement).getByText("nothing tied to this day")).toBeInTheDocument();
  });

  it("says when the week is flat rather than drawing seven identical columns", () => {
    show(reading({ fixedCommitments: [], profile: { recurringActivities: [{ recurringActivityId: "sleep", label: "Sleep", kind: "anchor", cadence: { period: "day", timesPerPeriod: 1, windowStart: "22:30", windowEnd: "06:30" } }] } }));
    expect(screen.getByText(/every day of the week has the same shape/)).toBeInTheDocument();
  });

  it("writes each stretch and one-off out in words beside the calendar", () => {
    show();
    expect(screen.getByRole("heading", { name: "The whole horizon, 243 days of it" })).toBeInTheDocument();
    expect(screen.getByText("3 Aug 2026 → 6 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText("Once between 5 Oct 2026 and 30 Oct 2026, on any day, between 09:00 – 12:00")).toBeInTheDocument();
    expect(screen.getByText(/changes no habit/)).toBeInTheDocument();
  });

  it("lists what it could not read instead of quietly leaving it out", () => {
    show(reading({ events: [{ eventId: "dentist", label: "Dentist", earliestDate: "sometime in October", latestDate: "2026-10-30" }] }));
    expect(screen.getByText("What could not be read")).toBeInTheDocument();
    expect(screen.getByText(/The one-off “Dentist” has no readable dates/)).toBeInTheDocument();
  });

  it("hides the detail without hiding the summary or the import", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Hide the detail" }));
    expect(screen.queryByRole("heading", { name: /One day, from midnight to midnight/ })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Eight months on Long Island");
    expect(screen.getByRole("button", { name: /expand and import/i })).toBeEnabled();
  });

  it("carries every remark the model wrote through to the reader", () => {
    show(reading({
      note: "Structure only: no day of this horizon is described here.",
      rhythm: { age: 68, health: ["mild arthritis"], chronotypeBedtime: "21:45" },
      world: { locations: [{ locationId: "bed_room", kind: "room" }], externalPeople: [{ externalPersonId: "sister", displayName: "Anna" }], startLocationId: "bed_room" },
      habits: [{ habitId: "night", label: "Night", windowStart: "22:30", windowEnd: "06:00", recurringActivityIds: ["sleep"], note: "Wraps past midnight." }],
      phases: [{ phaseId: "winter", label: "Winter", startDate: "2026-12-01", endDate: "2027-02-28", activityOverrides: [{ recurringActivityId: "run", suspended: true }], note: "The outdoor run stops." }],
      events: [{ eventId: "flu", label: "A week of flu", earliestDate: "2027-01-11", latestDate: "2027-01-17", displaces: [{ recurringActivityId: "run", policy: "skip" }], note: "A disruption a recogniser should survive." }],
      provenance: { authorType: "external_llm", modelName: "GPT-5.6 Thinking", humanReviewed: true },
    }));
    expect(screen.getByText(/Aged 68/)).toBeInTheDocument();
    expect(screen.getByText(/in bed around 21:45/)).toBeInTheDocument();
    expect(screen.getByText(/Health noted: mild arthritis/)).toBeInTheDocument();
    expect(screen.getByText("The file says a person has read it")).toBeInTheDocument();
    expect(screen.getByText("Structure only: no day of this horizon is described here.")).toBeInTheDocument();
    expect(screen.getByText("The outdoor run stops.")).toBeInTheDocument();
    expect(screen.getByText("Morning run is skipped that day")).toBeInTheDocument();
    expect(screen.getByText("A disruption a recogniser should survive.")).toBeInTheDocument();
    expect(screen.getByText("Wraps past midnight.")).toBeInTheDocument();
    // The underscored location ids are the simulator's; a reader should see the room.
    expect(screen.getByText("1 room")).toBeInTheDocument();
    expect(screen.getByText("bed room")).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
  });

  it("gives each shape of the day its own spine instead of painting them over each other", () => {
    // Two bands may claim the same hours without contradiction when they belong to different days.
    // Drawn on one track the second simply covers the first, and a whole workday disappears.
    show(reading({
      habits: [
        { habitId: "night", label: "Night", windowStart: "22:30", windowEnd: "06:00" },
        { habitId: "wfh", label: "Working from home", windowStart: "09:00", windowEnd: "18:00", weekdays: ["wednesday"] },
        { habitId: "weekend", label: "A slow weekend", windowStart: "09:00", windowEnd: "18:30", weekdays: ["saturday", "sunday"] },
      ],
    }));
    expect(screen.getByText("The shape of the day")).toBeInTheDocument();
    expect(screen.getByText("The day on Wed")).toBeInTheDocument();
    expect(screen.getByText("The day at the weekend")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /on Wed, in 1 band: Working from home, 09:00 – 18:00/ })).toBeInTheDocument();
    expect(screen.getByText(/the day has more than one shape/)).toBeInTheDocument();
  });

  it("says what is missing rather than drawing an empty clock", () => {
    show(reading({
      habits: [],
      profile: { recurringActivities: [] },
      fixedCommitments: [{ commitmentId: "shift", label: "A shift", weekdays: ["monday"], startTime: "nine", endTime: "five" }],
      world: { locations: [], startLocationId: "bedroom" },
      phases: [],
      events: [],
    }));
    expect(screen.getByText(/does not carve the day into bands/)).toBeInTheDocument();
    expect(screen.getByText(/No recurring activity is declared/)).toBeInTheDocument();
    expect(screen.getByText("not placed on the clock")).toBeInTheDocument();
    expect(screen.getByText("no stretch changes anything")).toBeInTheDocument();
    expect(screen.getByText("nothing one-off happens")).toBeInTheDocument();
    expect(screen.getByText("the resident never leaves the flat")).toBeInTheDocument();
    expect(screen.getByText("nobody else appears")).toBeInTheDocument();
  });

  it("checks the processes beside the outline before minutes are spent expanding it", () => {
    const withPackage = readOutline({
      documentType: "horizon_authoring_bundle",
      outline: { ...document_, fixedCommitments: [{ commitmentId: "salon", label: "Hair salon", weekdays: ["monday"], startTime: "09:00", endTime: "17:00", intent: "work_shift" }] },
      personalProcessPackage: { processModels: [{ processModelId: "pm_sleep" }], bindings: [{ intent: "sleep", processModelId: "pm_sleep" }] },
    });
    if (withPackage.kind !== "outline") throw new Error(withPackage.message);
    show(withPackage.reading);
    expect(screen.getByRole("heading", { name: "How the actions are performed" })).toBeInTheDocument();
    expect(screen.getByText("1 intent with nothing behind it")).toBeInTheDocument();
    expect(screen.getByText("work_shift")).toBeInTheDocument();
  });

  it("says nothing about behaviour when the file carried the outline alone", () => {
    show();
    expect(screen.queryByRole("heading", { name: "How the actions are performed" })).not.toBeInTheDocument();
  });

  it("hands the reader one file carrying the picture and the outline it was drawn from", async () => {
    const source = new File(['{"documentType":"horizon_outline"}'], "meredith.horizon-outline.json");
    Object.defineProperty(source, "text", { value: () => Promise.resolve('{"documentType":"horizon_outline"}') });
    render(<HorizonPreview reading={reading()} fileName="meredith.horizon-outline.json" sourceFile={source} busy={false} onImport={vi.fn()} />);
    const blobs: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((value: Blob | MediaSource) => { blobs.push(value as Blob); return "blob:test"; });
    fireEvent.click(screen.getByRole("button", { name: /Download this page/ }));
    await waitFor(() => expect(blobs).toHaveLength(1));
    const page = await readBlob(blobs[0]);
    expect(page).toContain("Eight months on Long Island");
    expect(page).toContain("One day, from midnight to midnight");
    expect(page).toContain('{"documentType":"horizon_outline"}');
    // Nothing in a file that can no longer talk to the application should look clickable.
    expect(page).not.toContain("<button");
    expect(page).not.toContain("<script");
  });

  it("exports the whole picture even from a section the reader had collapsed", async () => {
    show();
    const blobs: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((value: Blob | MediaSource) => { blobs.push(value as Blob); return "blob:test"; });
    fireEvent.click(screen.getByRole("button", { name: "Hide the detail" }));
    fireEvent.click(screen.getByRole("button", { name: /Download this page/ }));
    await waitFor(() => expect(blobs).toHaveLength(1));
    expect(await readBlob(blobs[0])).toContain("The whole horizon, 243 days of it");
  });

  it("imports from the preview, so reading and accepting are the same gesture", () => {
    const onImport = show();
    fireEvent.click(screen.getByRole("button", { name: /expand and import/i }));
    expect(onImport).toHaveBeenCalledOnce();
  });
});
