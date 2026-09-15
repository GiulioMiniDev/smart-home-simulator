import { describe, expect, it } from "vitest";
import { describeRefusal, readablePath } from "../authoring-refusal";

// The shape of the file that motivated this: two residents, and a night shift written across midnight.
const document_ = {
  documentType: "horizon_authoring_bundle",
  outline: {
    residents: [
      { residentId: "giulia_ferri", fixedCommitments: [{ commitmentId: "giu_morning" }, { commitmentId: "giu_evening" }, { commitmentId: "giu_night_shift" }] },
      { residentId: "paolo_ferri", profile: { recurringActivities: [{ recurringActivityId: "pao_late_read" }] } },
    ],
    household: { jointActivities: [{ activity: { recurringActivityId: "hh_dinner" } }] },
  },
};

describe("where a schema error sits", () => {
  it("names entries by the identifiers the author wrote, not by their position", () => {
    expect(readablePath(["outline", "residents", 0, "fixedCommitments", 2], document_)).toBe("outline › residents › giulia_ferri › fixedCommitments › giu_night_shift");
    expect(readablePath(["outline", "household", "jointActivities", 0, "sharing"], document_)).toBe("outline › household › jointActivities › hh_dinner › sharing");
  });

  it("counts from one where an entry has no name, and keeps steps the document does not contain", () => {
    expect(readablePath(["outline", "residents", 5, "habits", 0], document_)).toBe("outline › residents › #6 › habits › #1");
    expect(readablePath(["outline", "function-after[check()]"], null)).toBe("outline › function-after[check()]");
  });
});

describe("a refused import, in words", () => {
  it("lists every schema error of an outline at its place in the file", () => {
    const view = describeRefusal({
      valid: false,
      stage: "outline",
      message: "The document is not a valid horizon authoring bundle.",
      details: [
        { loc: ["outline", "residents", 0, "fixedCommitments", 2], msg: "Value error, commitment 'giu_night_shift' start must be before end", type: "value_error" },
        { loc: ["outline", "residents", 1, "profile", "recurringActivities", 0, "cadence"], msg: "Value error, cadence window start must be before end", type: "value_error" },
        { loc: [], type: "missing" },
      ],
    }, document_);
    expect(view.text).toBe("The document is not a valid horizon authoring bundle. 3 problems:");
    expect(view.items).toEqual([
      "outline › residents › giulia_ferri › fixedCommitments › giu_night_shift: commitment 'giu_night_shift' start must be before end",
      "outline › residents › paolo_ferri › profile › recurringActivities › pao_late_read › cadence: cadence window start must be before end",
      "missing",
    ]);
  });

  it("splits an expansion failure into the problems it joined", () => {
    const view = describeRefusal({ valid: false, stage: "expansion", message: "yoga needs exercise_support | dinner has one participant" }, document_);
    expect(view.text).toMatch(/could not be expanded into days\. 2 problems:$/);
    expect(view.items).toEqual(["yoga needs exercise_support", "dinner has one participant"]);
  });

  it("lists the errors that refused a bundle ahead of the warnings beside them", () => {
    const view = describeRefusal({
      valid: false,
      issues: [
        { severity: "warning", code: "HABIT_BAND_IS_MOSTLY_UNACCOUNTED", message: "Band is thin" },
        { severity: "error", code: "UNIMPLEMENTED_INTENT", path: "$.personalProcessPackage", message: "No process for sleep" },
        { severity: "error", code: "UNIMPLEMENTED_INTENT", path: "$.personalProcessPackage", message: "No process for sleep" },
      ],
    }, document_);
    expect(view).toEqual({ text: "The bundle was refused. 1 error:", items: ["No process for sleep (UNIMPLEMENTED_INTENT · $.personalProcessPackage)"] });
    expect(describeRefusal({ valid: false, issues: [{ message: "Geometry overlaps" }] }, {}).items).toEqual(["Geometry overlaps"]);
  });

  it("falls back to the sentence, or says there was none", () => {
    expect(describeRefusal({ valid: false, message: "the outline declares a band nothing inhabits" }, {})).toEqual({ text: "the outline declares a band nothing inhabits", items: [] });
    expect(describeRefusal({ valid: false }, {}).text).toBe("The import was refused without a reason.");
  });
});
