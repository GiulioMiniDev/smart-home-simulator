import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HorizonPreview } from "../horizon/HorizonPreview";
import { readOutline } from "../horizon/reading";
import type { HorizonReading, RawOutline } from "../horizon/types";
import { intentFromProposal, reviewItems, type ReviewActions } from "../horizon/review";
import type { VocabularyEntityType, VocabularyIntent } from "../vocabulary/types";
import { fixturePack } from "./vocabulary-fixture";

// A couple's month: a yoga mat the vocabulary does not have, a fridge it does, an aquarium it has
// without saying what for, and a dinner guest proposed as an activity with the package's steps.
const outline: RawOutline = {
  documentType: "horizon_outline",
  schemaVersion: "2.0.0",
  title: "Giulia and Paolo",
  startDate: "2026-10-01",
  months: 1,
  world: {
    locations: [{ locationId: "kitchen", kind: "room" }, { locationId: "living_room", kind: "room" }, { locationId: "garden", kind: "external" }],
    resources: [
      { resourceId: "mat_1", resourceType: "exercise_mat", locationId: "living_room" },
      { resourceId: "fridge_1", resourceType: "refrigerator", locationId: "kitchen" },
      { resourceId: "tank_1", resourceType: "aquarium", locationId: "living_room" },
    ],
  },
  residents: [{
    residentId: "paolo",
    events: [
      { eventId: "chiara", label: "Chiara for dinner", earliestDate: "2026-10-14", latestDate: "2026-10-17", intent: "host_guest" },
      { eventId: "odd", label: "Something new", earliestDate: "2026-10-20", latestDate: "2026-10-21", intent: "juggle" },
    ],
  }],
  vocabularyProposals: {
    furniture: [{ entityType: "exercise_mat", displayName: "Yoga mat", capabilities: ["openable", "exercise_support"], rationale: "Nothing offers exercise_support." }],
    activities: [{ intentId: "host_guest", label: "Host a guest", category: "social", defaultLocation: "garden", description: "Dinner with a visitor.", rationale: "A guest is not a phone call." }],
  },
};

const model = {
  processModelId: "pm_paolo_guest",
  processModelVersion: "1.0.0",
  residentId: "paolo",
  title: "Guest",
  implementedComponents: ["authored__host_guest"],
  nodes: [
    { nodeId: "start", kind: "start", actionType: null },
    { nodeId: "a1", kind: "action", actionType: "move_to" },
    { nodeId: "a2", kind: "action", actionType: "wait" },
    { nodeId: "end", kind: "end", actionType: null },
  ],
  edges: [],
};

function reading(): HorizonReading {
  const result = readOutline({
    documentType: "horizon_authoring_bundle",
    outline,
    personalProcessPackage: { processModels: [model], bindings: [{ intent: "host_guest", processModelId: "pm_paolo_guest", residentId: "paolo" }] },
  });
  if (result.kind !== "outline") throw new Error(result.message);
  return result.reading;
}

function actions(overrides: Partial<ReviewActions> = {}): ReviewActions {
  return { substitutions: {}, onSubstitute: vi.fn(), onAddFurniture: vi.fn(async () => undefined), onAddActivity: vi.fn(async () => undefined), ...overrides };
}

function show(review?: ReviewActions) {
  render(<HorizonPreview reading={reading()} fileName="ferri.json" vocabulary={fixturePack()} review={review} busy={false} onImport={vi.fn()} />);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("what an outline asks to add to the vocabulary", () => {
  it("lists the unknown and the undeclared, and leaves out what the vocabulary already describes", () => {
    const { furniture, activities } = reviewItems(reading(), fixturePack());
    expect(furniture.map((item) => item.entityType)).toEqual(["exercise_mat", "aquarium"]);
    expect(furniture[1]!.declaredEmpty).toBe(true);
    expect(activities.map((item) => item.intentId)).toEqual(["host_guest", "juggle"]);
    expect(activities[0]!.model?.processModelId).toBe("pm_paolo_guest");
    expect(activities[1]!.model).toBeUndefined();
  });

  it("says nothing until the vocabulary has been read", () => {
    render(<HorizonPreview reading={reading()} fileName="ferri.json" busy={false} onImport={vi.fn()} />);
    expect(screen.queryByRole("heading", { name: /Additions to the vocabulary/ })).not.toBeInTheDocument();
  });

  it("lists everything read-only when there is nothing the reader can do from here", () => {
    show();
    expect(screen.getByRole("heading", { name: "Additions to the vocabulary — review before importing" })).toBeInTheDocument();
    expect(screen.getByText("Objects (types of furniture) · 2")).toBeInTheDocument();
    expect(screen.getByText("Activities (activity labels) · 2")).toBeInTheDocument();
    expect(screen.getByText("“A guest is not a phone call.”")).toBeInTheDocument();
    expect(screen.getByText(/the vocabulary has this type but says nothing it is for/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add to the vocabulary/ })).not.toBeInTheDocument();
  });

  it("adds a proposed object with what the author said it is for, and what the reader adds", async () => {
    const review = actions();
    show(review);
    fireEvent.click(screen.getAllByRole("button", { name: /Add to the vocabulary/ })[0]!);
    expect(screen.getByLabelText("Name")).toHaveValue("Yoga mat");
    // Proposed, and not something any action in this vocabulary asks for.
    expect(screen.getByText(/no action asks for this, so it binds nothing/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("It has a door or a lid a contact sensor would be fitted to."));
    fireEvent.change(screen.getByLabelText(/Drawing/), { target: { value: "<rect width=\"10\" height=\"10\" />" } });
    fireEvent.click(screen.getByRole("button", { name: "Add “Yoga mat”" }));
    await waitFor(() => expect(review.onAddFurniture).toHaveBeenCalledOnce());
    const entity = vi.mocked(review.onAddFurniture).mock.calls[0]![0] as VocabularyEntityType;
    expect(entity).toMatchObject({ entityType: "exercise_mat", displayName: "Yoga mat", contactInstrumented: true, symbolBody: "<rect width=\"10\" height=\"10\" />" });
    expect(entity.capabilities).toEqual(["openable", "exercise_support"]);
  });

  it("will not add an object that is for nothing, and says why a save failed", async () => {
    const review = actions({ onAddFurniture: vi.fn(async () => { throw new Error("The stored vocabulary changed since this editor loaded it."); }) });
    show(review);
    fireEvent.click(screen.getAllByRole("button", { name: /Add to the vocabulary/ })[1]!);
    const add = screen.getByRole("button", { name: "Add “aquarium”" });
    expect(add).toBeDisabled();
    fireEvent.click(screen.getByText("openable"));
    fireEvent.click(add);
    expect(await screen.findByRole("alert")).toHaveTextContent("changed since this editor loaded it");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Add “aquarium”" })).not.toBeInTheDocument();
  });

  it("imports an object as a type that exists, and takes it back", () => {
    const review = actions();
    const { rerender } = render(<HorizonPreview reading={reading()} fileName="ferri.json" vocabulary={fixturePack()} review={review} busy={false} onImport={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button", { name: /Use a known type/ })[0]!);
    const use = screen.getByRole("button", { name: "Use this type" });
    expect(use).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "refrigerator" } });
    fireEvent.click(use);
    expect(review.onSubstitute).toHaveBeenCalledWith("exercise_mat", "refrigerator");

    const decided = { ...review, substitutions: { exercise_mat: "refrigerator" } };
    rerender(<HorizonPreview reading={reading()} fileName="ferri.json" vocabulary={fixturePack()} review={decided} busy={false} onImport={vi.fn()} />);
    expect(screen.getByText(/Imported as/)).toHaveTextContent("Imported as refrigerator");
    fireEvent.click(screen.getByRole("button", { name: /Undo/ }));
    expect(review.onSubstitute).toHaveBeenCalledWith("exercise_mat", undefined);
    rerender(<HorizonPreview reading={reading()} fileName="ferri.json" vocabulary={fixturePack()} review={review} busy={false} onImport={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button", { name: /Use a known type/ })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Use this type" })).not.toBeInTheDocument();
  });

  it("says what each entry is, where it is, what it is for and what to do about it", () => {
    show(actions());
    expect(screen.getAllByText("Object")).toHaveLength(2);
    expect(screen.getAllByText("Activity")).toHaveLength(2);
    expect(screen.getByText("Yoga mat")).toBeInTheDocument();
    expect(screen.getByText("a new type of furniture the author proposes")).toBeInTheDocument();
    expect(screen.getByText("a type of furniture the author used without proposing it")).toBeInTheDocument();
    expect(screen.getByText("openable, exercise support")).toBeInTheDocument();
    expect(screen.getByText(/Check it before adding\. It claims to be for exercise support, which no action needs/)).toBeInTheDocument();
    expect(screen.getByText(/Say what it is for\. The vocabulary already has this type/)).toBeInTheDocument();
    expect(screen.getByText(/Add it, if the name is right/)).toBeInTheDocument();
    expect(screen.getByText(/add it on the Vocabulary page, or ask the author/)).toBeInTheDocument();
  });

  it("recommends removing furniture placed outside the home, and removes it from the import", () => {
    const outdoors = readOutline({
      ...outline,
      world: {
        locations: [{ locationId: "living_room", kind: "room" }, { locationId: "outdoors", kind: "external" }],
        resources: [{ resourceId: "out_1", resourceType: "exercise_surface", locationId: "outdoors" }],
      },
      residents: [{ residentId: "paolo" }],
      vocabularyProposals: { furniture: [{ entityType: "exercise_surface", displayName: "Outdoor exercise surface", capabilities: ["exercise_support"], rationale: "Walking needs exercise_support." }] },
    });
    if (outdoors.kind !== "outline") throw new Error(outdoors.message);
    const review = actions();
    const { rerender } = render(<HorizonPreview reading={outdoors.reading} fileName="ferri.json" vocabulary={fixturePack()} review={review} busy={false} onImport={vi.fn()} />);
    expect(screen.getByText("outdoors — outside the home")).toBeInTheDocument();
    expect(screen.getByText(/Remove it from this import\. It sits outside the home/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Remove from this import/ }));
    expect(review.onSubstitute).toHaveBeenCalledWith("exercise_surface", "");
    rerender(<HorizonPreview reading={outdoors.reading} fileName="ferri.json" vocabulary={fixturePack()} review={{ ...review, substitutions: { exercise_surface: "" } }} busy={false} onImport={vi.fn()} />);
    expect(screen.getByText("Removed from this import")).toBeInTheDocument();
    expect(screen.queryByText(/Remove it from this import/)).not.toBeInTheDocument();
  });

  it("has nothing to recommend for a proposed type no object uses", () => {
    const unused = readOutline({ ...outline, world: { locations: outline.world!.locations, resources: [] }, residents: [{ residentId: "paolo" }] });
    if (unused.kind !== "outline") throw new Error(unused.message);
    render(<HorizonPreview reading={unused.reading} fileName="ferri.json" vocabulary={fixturePack()} review={actions()} busy={false} onImport={vi.fn()} />);
    expect(screen.getByText("no object in the home has this type")).toBeInTheDocument();
    expect(screen.getByText(/Nothing to do for this import/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove from this import/ })).not.toBeInTheDocument();
  });

  it("adds a proposed activity from the author's own steps, in a room the vocabulary uses", async () => {
    const review = actions();
    show(review);
    // Only the proposal has a process to start from; the unproposed one says where it can be added.
    expect(screen.getByText("the file gives no process for it")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /Add to the vocabulary/ });
    fireEvent.click(buttons[buttons.length - 1]!);
    expect(screen.getByText(/proposed the garden, which no activity in the vocabulary uses/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Where it usually happens/), { target: { value: "kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: "Add “Host a guest”" }));
    await waitFor(() => expect(review.onAddActivity).toHaveBeenCalledOnce());
    const intent = vi.mocked(review.onAddActivity).mock.calls[0]![0] as VocabularyIntent;
    expect(intent).toMatchObject({ intentId: "host_guest", category: "social", defaultLocation: "kitchen", description: "Dinner with a visitor.", components: [] });
    expect(intent.processModel.residentId).toBe("reference_resident");
    expect(intent.processModel.processModelId).toBe("reference__host_guest");
    expect(intent.processModel.nodes).toHaveLength(4);
  });

  it("keeps the catalog components an older author's model declared, so its packages still validate", () => {
    const intent = intentFromProposal("host_guest", { label: "Host a guest", category: "social", room: "kitchen", description: "" }, { implementedComponents: ["communicate", "authored__host_guest"] });
    expect(intent.components).toEqual(["communicate"]);
    expect(intent.processModel.processModelVersion).toBe("1.0.0");
    expect(intent.processModel.nodes).toEqual([]);
  });

  it("says why an activity could not be added", async () => {
    const review = actions({ onAddActivity: vi.fn(async () => { throw "refused"; }) });
    show(review);
    const buttons = screen.getAllByRole("button", { name: /Add to the vocabulary/ });
    fireEvent.click(buttons[buttons.length - 1]!);
    fireEvent.change(screen.getByLabelText("Kind of activity"), { target: { value: "leisure" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Add “host_guest”" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("refused");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Kind of activity")).not.toBeInTheDocument();
  });

  it("stays out of the way when the outline asks for nothing", () => {
    const plain = readOutline({ ...outline, world: { locations: outline.world!.locations, resources: [] }, residents: [{ residentId: "paolo" }], vocabularyProposals: undefined });
    if (plain.kind !== "outline") throw new Error(plain.message);
    render(<HorizonPreview reading={plain.reading} fileName="plain.json" vocabulary={fixturePack()} review={actions()} busy={false} onImport={vi.fn()} />);
    expect(screen.queryByRole("heading", { name: /Additions to the vocabulary/ })).not.toBeInTheDocument();
  });
});
