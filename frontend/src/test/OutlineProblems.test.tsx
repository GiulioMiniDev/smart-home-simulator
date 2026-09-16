import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OutlineProblems, type ProblemActions } from "../horizon/OutlineProblems";
import { applyAmendments, newResourceId, recordResearcherChanges, researcherChanges, resourceIds, type OutlineAmendment } from "../horizon/review";
import type { OutlineCheck, OutlineFinding } from "../horizon/types";

// The Verdi case: Filiberto tidies a living room holding a sofa and a television, and `organize`
// needs somewhere to put things away.
const tidy: OutlineFinding = {
  code: "ROOM_LACKS_CAPABILITY",
  severity: "error",
  path: "$.outline.residents[1].profile.recurringActivities[9].location",
  message: "recurring activity 'fil_tidy' happens in 'living_room', which holds nothing offering storage_support",
  details: {
    recurringActivityId: "fil_tidy",
    label: "Riordino del soggiorno e ingresso",
    intent: "tidy_living_room_and_hallway",
    residentIds: ["filiberto_verdi"],
    room: "living_room",
    missingCapabilities: ["storage_support"],
    furnitureTypes: { storage_support: ["bookshelf", "sideboard", "wardrobe"] },
    roomsThatCanHostIt: ["bedroom", "kitchen"],
  },
};

const bundle = () => ({
  documentType: "horizon_authoring_bundle",
  outline: {
    world: {
      locations: [{ locationId: "living_room", kind: "room" }, { locationId: "bedroom", kind: "room" }],
      resources: [{ resourceId: "liv_sofa", resourceType: "sofa", locationId: "living_room" }],
    },
    residents: [{
      residentId: "filiberto_verdi",
      profile: { recurringActivities: [{ recurringActivityId: "fil_tidy", intent: "tidy_living_room_and_hallway", location: "living_room", cadence: { period: "month" } }] },
      phases: [{ phaseId: "p", activityOverrides: [{ recurringActivityId: "fil_tidy", suspended: true }] }],
    }],
    household: { jointActivities: [{ activity: { recurringActivityId: "hh_dinner", location: "kitchen", cadence: { period: "day" } }, participantIds: [] }] },
  },
  personalProcessPackage: {},
});

function actions(overrides: Partial<ProblemActions> = {}): ProblemActions {
  const check: OutlineCheck = { valid: false, stage: "expansion", findings: [tidy] };
  return {
    check,
    checking: false,
    amendments: [],
    resourceIds: new Set(["liv_sofa", "living_room_bookshelf"]),
    onAmend: vi.fn(),
    onUndo: vi.fn(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the imported copy, as the repairs change it", () => {
  it("adds furniture to the world and leaves the file's other resources alone", () => {
    const amended = applyAmendments(bundle(), [
      { kind: "add_furniture", key: "a", resourceId: "living_room_bookshelf", resourceType: "bookshelf", room: "living_room", reason: tidy.message },
    ]) as ReturnType<typeof bundle>;

    expect(amended.outline.world.resources).toEqual([
      { resourceId: "liv_sofa", resourceType: "sofa", locationId: "living_room" },
      { resourceId: "living_room_bookshelf", resourceType: "bookshelf", locationId: "living_room" },
    ]);
    expect(bundle().outline.world.resources).toHaveLength(1);
  });

  it("moves the recurring activity and not the phase override that names it", () => {
    const amended = applyAmendments(bundle(), [
      { kind: "move_activity", key: "m", recurringActivityId: "fil_tidy", from: "living_room", room: "bedroom", reason: tidy.message },
    ]) as ReturnType<typeof bundle>;
    const resident = amended.outline.residents[0];

    expect(resident.profile.recurringActivities[0].location).toBe("bedroom");
    expect(resident.phases[0].activityOverrides[0]).toEqual({ recurringActivityId: "fil_tidy", suspended: true });
    expect(amended.outline.household.jointActivities[0].activity.location).toBe("kitchen");
  });

  it("reaches a shared activity too, and a bare outline without the envelope", () => {
    const bare = bundle().outline;
    const amended = applyAmendments(bare, [
      { kind: "move_activity", key: "m", recurringActivityId: "hh_dinner", from: "kitchen", room: "living_room", reason: "" },
    ]) as typeof bare;

    expect(amended.household.jointActivities[0].activity.location).toBe("living_room");
  });

  it("is the same document when nothing was changed", () => {
    const document = bundle();
    expect(applyAmendments(document, [])).toBe(document);
  });

  it("names new furniture after its room and type, and never reuses an identifier", () => {
    const taken = resourceIds(bundle());
    expect(newResourceId("living_room", "bookshelf", taken)).toBe("living_room_bookshelf");
    taken.add("living_room_bookshelf");
    expect(newResourceId("living_room", "bookshelf", taken)).toBe("living_room_bookshelf_2");
  });
});

describe("what the researcher changed, in the imported copy's own provenance", () => {
  const furnish: OutlineAmendment = { kind: "add_furniture", key: "add_furniture:living_room_bookshelf", resourceId: "living_room_bookshelf", resourceType: "bookshelf", room: "living_room", reason: tidy.message };

  it("lists substitutions, removals and amendments in the order they changed the document, without the page's keys", () => {
    expect(researcherChanges({ tv_stand: "sideboard", treadmill: "" }, [furnish])).toEqual([
      { kind: "substitute_type", from: "tv_stand", to: "sideboard" },
      { kind: "remove_type", resourceType: "treadmill" },
      { kind: "add_furniture", resourceId: "living_room_bookshelf", resourceType: "bookshelf", room: "living_room", reason: tidy.message },
    ]);
  });

  it("appends to what the outline already records, in the envelope and in a bare outline", () => {
    const earlier = { kind: "move_activity", recurringActivityId: "fil_tidy", from: "kitchen", room: "living_room", reason: "" };
    const withProvenance = { ...bundle(), outline: { ...bundle().outline, provenance: { authorType: "external_llm", parameters: { seed: 1, researcherChanges: [earlier] } } } };
    const changes = researcherChanges({}, [furnish]);

    const recorded = recordResearcherChanges(withProvenance, changes) as typeof withProvenance;
    expect(recorded.outline.provenance).toEqual({ authorType: "external_llm", parameters: { seed: 1, researcherChanges: [earlier, changes[0]] } });
    expect(withProvenance.outline.provenance.parameters.researcherChanges).toHaveLength(1);

    const bare = recordResearcherChanges({ provenance: { authorType: "human" } }, changes);
    expect(bare).toEqual({ provenance: { authorType: "human", parameters: { researcherChanges: changes } } });
  });

  it("leaves the document alone when nothing changed or there is no provenance to say it in", () => {
    const document = bundle();
    expect(recordResearcherChanges(document, [])).toBe(document);
    expect(recordResearcherChanges(document, researcherChanges({}, [furnish]))).toBe(document);
  });
});

describe("what the outline cannot do, in the preview", () => {
  it("says nothing when the check found nothing and nothing was changed", () => {
    const { container } = render(<OutlineProblems actions={actions({ check: { valid: true, stage: "expansion", findings: [] } })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("describes a room that cannot host an activity, with what it lacks", () => {
    render(<OutlineProblems actions={actions()} />);
    const card = screen.getByText("Riordino del soggiorno e ingresso").closest("li");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("storage support")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("filiberto_verdi")).toBeInTheDocument();
  });

  it("furnishes the room with a type that provides what is missing, under an identifier nothing uses", () => {
    const onAmend = vi.fn();
    render(<OutlineProblems actions={actions({ onAmend })} />);

    fireEvent.click(screen.getByRole("button", { name: /Add furniture here/ }));
    const choice = screen.getByRole("combobox", { name: /storage support/ });
    expect(within(choice).getAllByRole("option").map((option) => option.textContent)).toEqual(["bookshelf", "sideboard", "wardrobe"]);
    fireEvent.click(screen.getByRole("button", { name: "Add to the living room" }));

    expect(onAmend).toHaveBeenCalledWith([
      expect.objectContaining({ kind: "add_furniture", resourceId: "living_room_bookshelf_2", resourceType: "bookshelf", room: "living_room" }),
    ]);
  });

  it("moves the activity only to a room that can already host it", () => {
    const onAmend = vi.fn();
    render(<OutlineProblems actions={actions({ onAmend })} />);

    fireEvent.click(screen.getByRole("button", { name: /Move the activity/ }));
    const choice = screen.getByRole("combobox");
    expect(within(choice).getAllByRole("option").map((option) => option.textContent)).toEqual(["bedroom", "kitchen"]);
    fireEvent.change(choice, { target: { value: "kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: "Move it" }));

    expect(onAmend).toHaveBeenCalledWith([
      expect.objectContaining({ kind: "move_activity", recurringActivityId: "fil_tidy", from: "living_room", room: "kitchen" }),
    ]);
  });

  it("lists every change with an undo, and says when nothing stops the import any more", () => {
    const onUndo = vi.fn();
    const amendments: OutlineAmendment[] = [
      { kind: "add_furniture", key: "add_furniture:living_room_bookshelf", resourceId: "living_room_bookshelf", resourceType: "bookshelf", room: "living_room", reason: tidy.message },
    ];
    render(<OutlineProblems actions={actions({ amendments, onUndo, check: { valid: true, stage: "expansion", findings: [] } })} />);

    expect(screen.getByText(/check finds nothing that stops the import/)).toBeInTheDocument();
    expect(screen.getByText(/Added a bookshelf \(living_room_bookshelf\) to the living room/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Undo/ }));
    expect(onUndo).toHaveBeenCalledWith("add_furniture:living_room_bookshelf");
  });

  it("says so while the check is running, and when it could not run", () => {
    render(<OutlineProblems actions={actions({ check: undefined, checking: true })} />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking the outline");
    cleanup();
    render(<OutlineProblems actions={actions({ check: undefined, failure: "server down" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("server down");
  });
});
