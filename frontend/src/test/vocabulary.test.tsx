import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { VocabularyPage } from "../vocabulary/VocabularyPage";
import * as draft from "../vocabulary/draft";
import {
  actionSummary,
  stepBinding,
  stepCall,
  stepEvidence,
  roleNoun,
  stepPhrase,
  stepTiming,
  typesForRole,
} from "../vocabulary/phrasing";
import type { VocabularyGapsReport, VocabularyPack } from "../vocabulary/types";
import { CustomFurnitureSymbols } from "../vocabulary/CustomFurnitureSymbols";
import { customSymbolId, setCustomSymbols, useCustomSymbols } from "../vocabulary/symbol-registry";
import { furnitureSymbol } from "../furniture";
import { fixturePack } from "./vocabulary-fixture";

function actionOf(pack: VocabularyPack, type: string) {
  return pack.actions.find((item) => item.definition.actionType === type);
}

function stepsOf(pack: VocabularyPack, intentId: string) {
  const intent = pack.intents.find((item) => item.intentId === intentId);
  return draft.actionNodes(intent!.processModel);
}

describe("reading a step in English", () => {
  const pack = fixturePack();

  it("says what the resident does, not which function is called", () => {
    const [walk, open, take] = stepsOf(pack, "eat_breakfast");
    expect(stepPhrase(walk!)).toBe("Walks to where the activity happens");
    expect(stepPhrase(open!)).toBe("Opens the fridge");
    expect(stepPhrase(take!)).toBe("Picks up the ingredients");
  });

  it("keeps the call underneath, because that is what is being edited", () => {
    expect(stepCall(stepsOf(pack, "eat_breakfast")[1]!)).toBe("open(target: food_storage)");
    // An argument decided per activity names its source rather than pretending to a value.
    expect(stepCall(stepsOf(pack, "sleep")[0]!)).toBe("move_to(destination: activity_location)");
  });

  it("falls back to the identifier for an action it has no reading for", () => {
    const invented = { ...stepsOf(pack, "sleep")[1]!, actionType: "water_plants" };
    expect(stepPhrase(invented)).toBe("Performs water plants");
    expect(actionSummary("water_plants")).toBe("Performs water plants");
  });

  it("summarises an action whose whole meaning is its argument", () => {
    // `change_posture` reads as "Sits down" in a step and as nothing at all in a list.
    expect(actionSummary("change_posture")).toBe("Sits, stands or lies down");
    expect(actionSummary("open")).toBe("Opens …");
  });
});

describe("what a step will actually touch", () => {
  const pack = fixturePack();

  it("resolves a role to the furniture that answers it", () => {
    expect(typesForRole(pack, "food_storage")).toEqual(["refrigerator"]);
    expect(stepBinding(pack, stepsOf(pack, "eat_breakfast")[1]!)).toEqual({
      role: "food_storage",
      types: ["refrigerator"],
    });
  });

  it("reports a role nothing answers rather than guessing one", () => {
    expect(typesForRole(pack, "drinking_glass")).toEqual([]);
    expect(stepBinding(pack, stepsOf(pack, "eat_breakfast")[4]!).types).toEqual([]);
  });

  it("ignores an argument that names a mode rather than an object", () => {
    // `wait(purpose: sleep)` must not report `sleep` as an unfurnished room.
    expect(stepBinding(pack, stepsOf(pack, "sleep")[1]!)).toEqual({ role: null, types: [] });
  });
});

describe("what the sensors get", () => {
  const pack = fixturePack();

  it("counts a walk as evidence even though no action table lists it", () => {
    expect(stepEvidence(pack, stepsOf(pack, "sleep")[0]!)).toEqual([
      { kind: "walk", label: "motion along the way" },
    ]);
  });

  it("adds a door event only for a container that carries a contact sensor", () => {
    const kinds = stepEvidence(pack, stepsOf(pack, "eat_breakfast")[1]!).map((item) => item.kind);
    expect(kinds).toEqual(["object", "contact"]);

    const uninstrumented = { ...stepsOf(pack, "eat_breakfast")[1]!, arguments: { target: draft.literal("cooking_appliance") } };
    expect(stepEvidence(pack, uninstrumented).map((item) => item.kind)).toEqual(["object"]);
  });

  it("says plainly when a step leaves nothing behind", () => {
    expect(stepEvidence(pack, stepsOf(pack, "sleep")[1]!)).toEqual([
      { kind: "presence", label: "presence only" },
    ]);
  });
});

describe("how long a step lasts", () => {
  const pack = fixturePack();

  it("does not report a travel action as taking no time", () => {
    expect(stepTiming(actionOf(pack, "move_to"), stepsOf(pack, "sleep")[0]!)).toBe("as long as the walk");
  });

  it("distinguishes a fixed gesture from one that fills the activity", () => {
    expect(stepTiming(actionOf(pack, "open"), stepsOf(pack, "eat_breakfast")[1]!)).toBe("3s, fixed");
    expect(stepTiming(actionOf(pack, "wait"), stepsOf(pack, "sleep")[1]!)).toBe(
      "fills the activity · weight 1.0",
    );
  });
});

describe("editing an activity's steps", () => {
  it("keeps the graph a valid chain after a reorder", () => {
    const pack = draft.moveStep(fixturePack(), "eat_breakfast", 0, 1);
    const model = pack.intents.find((item) => item.intentId === "eat_breakfast")!.processModel;
    expect(model.nodes.map((node) => node.actionType)).toEqual([
      null, "open", "move_to", "take_item", "close", "take_item", null,
    ]);
    // Renumbered from position, so an insert never leaves a hole in the ids.
    expect(model.nodes.map((node) => node.nodeId)).toEqual([
      "start", "step_1", "step_2", "step_3", "step_4", "step_5", "end",
    ]);
    expect(model.edges).toEqual([
      { sourceNodeId: "start", targetNodeId: "step_1", condition: null, isDefault: false },
      { sourceNodeId: "step_1", targetNodeId: "step_2", condition: null, isDefault: false },
      { sourceNodeId: "step_2", targetNodeId: "step_3", condition: null, isDefault: false },
      { sourceNodeId: "step_3", targetNodeId: "step_4", condition: null, isDefault: false },
      { sourceNodeId: "step_4", targetNodeId: "step_5", condition: null, isDefault: false },
      { sourceNodeId: "step_5", targetNodeId: "end", condition: null, isDefault: false },
    ]);
  });

  it("refuses to move a step off either end", () => {
    const pack = fixturePack();
    expect(draft.moveStep(pack, "eat_breakfast", 0, -1)).toBe(pack);
    expect(draft.moveStep(pack, "eat_breakfast", 4, 1)).toBe(pack);
  });

  it("inserts a step with its required arguments already present", () => {
    const pack = draft.insertStep(fixturePack(), "sleep", 1, actionOf(fixturePack(), "open")!);
    const steps = stepsOf(pack, "sleep");
    expect(steps.map((node) => node.actionType)).toEqual(["move_to", "open", "wait"]);
    expect(steps[1]!.arguments.target).toBeDefined();
  });

  it("keeps the last step, because an activity with no steps is not an activity", () => {
    let pack = draft.removeStep(fixturePack(), "sleep", 0);
    expect(stepsOf(pack, "sleep")).toHaveLength(1);
    pack = draft.removeStep(pack, "sleep", 0);
    expect(stepsOf(pack, "sleep")).toHaveLength(1);
  });

  it("edits an argument and a weight in place", () => {
    let pack = draft.setStepArgument(fixturePack(), "eat_breakfast", 1, "target", "cooking_appliance");
    expect(stepsOf(pack, "eat_breakfast")[1]!.arguments.target!.value).toBe("cooking_appliance");
    pack = draft.setStepWeight(pack, "sleep", 1, 4.5);
    expect(stepsOf(pack, "sleep")[1]!.durationWeight).toBe(4.5);
  });

  it("leaves an unknown activity alone rather than inventing one", () => {
    const pack = fixturePack();
    expect(draft.moveStep(pack, "nope", 0, 1)).toBe(pack);
    expect(draft.removeStep(pack, "nope", 0)).toBe(pack);
    expect(draft.setStepWeight(pack, "nope", 0, 2)).toBe(pack);
    expect(draft.setStepArgument(pack, "nope", 0, "x", "y")).toBe(pack);
    expect(draft.updateIntentMeta(pack, "nope", { label: "x" })).toBe(pack);
    expect(draft.insertStep(pack, "nope", 0, pack.actions[0]!)).toBe(pack);
  });

  it("recognises a branching model, which must not be flattened into a list", () => {
    const pack = fixturePack();
    const linear = pack.intents.find((item) => item.intentId === "sleep")!.processModel;
    const branching = pack.intents.find((item) => item.intentId === "night_toilet_visit")!.processModel;
    expect(draft.isLinear(linear)).toBe(true);
    expect(draft.isLinear(branching)).toBe(false);
  });
});

describe("adding and removing", () => {
  it("turns a title into an identifier and never collides", () => {
    expect(draft.slug("Water the Plants!")).toBe("water_the_plants");
    expect(draft.slug("  ")).toBe("");
    let pack = fixturePack();
    const first = draft.addIntent(pack, { label: "Eat breakfast", category: "meal", room: "kitchen" });
    expect(first.intentId).toBe("eat_breakfast_2");
    pack = first.pack;
    expect(pack.intents).toHaveLength(4);
    // A new activity is valid from the first save: it starts with the walk every activity has.
    expect(stepsOf(pack, "eat_breakfast_2").map((node) => node.actionType)).toEqual(["move_to"]);
  });

  it("removes an activity", () => {
    const pack = draft.removeIntent(fixturePack(), "sleep");
    expect(pack.intents.map((item) => item.intentId)).not.toContain("sleep");
  });

  it("creates an action with the shape every bundled action has", () => {
    const pack = draft.addAction(fixturePack(), {
      actionType: "Water plants",
      description: "Pour water into a planter.",
      capability: "plant_care",
      gestureSeconds: 12,
      motionAtObject: true,
    });
    const created = actionOf(pack, "water_plants")!;
    expect(created.definition.parameters.map((item) => item.parameterName)).toEqual(["targetRole"]);
    expect(created.definition.requiredCapabilities[0]!.capability).toBe("plant_care");
    expect(created.gestureSeconds).toBe(12);
    expect(created.isTravel).toBe(false);
  });

  it("creates an action with no target when it is done to nothing in particular", () => {
    const pack = draft.addAction(fixturePack(), {
      actionType: "hum",
      description: "",
      capability: "",
      gestureSeconds: null,
      motionAtObject: false,
    });
    const created = actionOf(pack, "hum")!;
    expect(created.definition.parameters).toEqual([]);
    expect(created.definition.description).toContain("hum");
  });

  it("refuses a duplicate or nameless action", () => {
    const pack = fixturePack();
    const base = { description: "", capability: "", gestureSeconds: null, motionAtObject: false };
    expect(draft.addAction(pack, { ...base, actionType: "open" })).toBe(pack);
    expect(draft.addAction(pack, { ...base, actionType: "  " })).toBe(pack);
  });

  it("will not delete an action an activity still calls", () => {
    const pack = fixturePack();
    expect(draft.actionUsers(pack, "open")).toEqual(["eat_breakfast"]);
    expect(draft.removeAction(pack, "open")).toBe(pack);
    expect(draft.removeAction(pack, "dress").actions.map((item) => item.definition.actionType)).not.toContain("dress");
  });

  it("adds and removes a kind of furniture", () => {
    const created = draft.addEntityType(fixturePack(), "Book case");
    expect(created.entityType).toBe("book_case");
    expect(created.pack.entityTypes.find((item) => item.entityType === "book_case")!.capabilities).toEqual([]);
    // Adding the same name twice must not produce two records.
    expect(draft.addEntityType(created.pack, "Book case").pack).toBe(created.pack);
    expect(draft.removeEntityType(created.pack, "book_case").entityTypes).toHaveLength(3);
  });

  it("suggests the capabilities and roles the vocabulary already uses", () => {
    const pack = fixturePack();
    expect(draft.knownCapabilities(pack)).toEqual(["food_preparation", "openable", "storage_support"]);
    expect(draft.knownRoles(pack)).toContain("food_storage");
    expect(draft.knownRoles(pack)).toContain("drinking_glass");
    // A mode is not a role.
    expect(draft.knownRoles(pack)).not.toContain("sleep");
  });
});

// --- the page ----------------------------------------------------------------------------------

const emptyReport: VocabularyGapsReport = { packId: "builtin", digest: "d", gaps: [] };

function report(): VocabularyGapsReport {
  return {
    packId: "builtin",
    digest: "d",
    gaps: [
      {
        code: "ROLE_WITHOUT_FURNITURE",
        severity: "warning",
        subject: "drinking_glass",
        message: "No furniture answers to 'drinking_glass'.",
        consequence: "The step binds to the room's service point instead of an object.",
        details: { usedBy: ["eat_breakfast"] },
      },
      {
        code: "ACTION_UNUSED",
        severity: "note",
        subject: "dress",
        message: "No activity uses 'dress'.",
        consequence: "It costs nothing.",
        details: {},
      },
    ],
  };
}

function mockApi(options: { gaps?: VocabularyGapsReport; onSave?: (body: unknown) => Response } = {}) {
  const saved: unknown[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/session")) return json({ token: "t" });
    if (url.endsWith("/api/vocabulary/review")) {
      return json({ digest: "d", labelSpaceDigest: "l", report: options.gaps ?? emptyReport });
    }
    if (url.endsWith("/api/vocabulary")) {
      if (init?.method === "PUT") {
        saved.push(JSON.parse(String(init.body)));
        if (options.onSave) return options.onSave(JSON.parse(String(init.body)));
        return json({ pack: fixturePack(), customised: true, digest: "d2", labelSpaceDigest: "l" });
      }
      if (init?.method === "DELETE") {
        return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
      }
      return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
    }
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return { saved };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <VocabularyPage />
    </MemoryRouter>,
  );
}

describe("the vocabulary page", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows every activity as a list of things a person does", async () => {
    mockApi();
    renderPage();
    await screen.findByText("Eat breakfast");
    expect(screen.getByText("As shipped")).toBeInTheDocument();
    expect(screen.getByText(/28 activities|3 activities/)).toBeInTheDocument();
    expect(await screen.findByText("Opens the fridge")).toBeInTheDocument();
    expect(screen.getByText("open(target: food_storage)")).toBeInTheDocument();
    // The furniture the step will really touch, and the door it will swing. Two steps open the
    // fridge, so both chips are present.
    expect(screen.getAllByText("refrigerator").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fridge door").length).toBeGreaterThan(0);
  });

  it("says which role nothing answers, on the step itself", async () => {
    mockApi();
    renderPage();
    expect(await screen.findByText(/nothing answers .drinking_glass./)).toBeInTheDocument();
  });

  it("saves a reorder on its own, without a save button", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack; expected_digest: string };
    expect(body.expected_digest).toBe("d");
    expect(draft.actionNodes(body.pack.intents[0]!.processModel).map((node) => node.actionType)).toEqual([
      "open", "move_to", "take_item", "close", "take_item",
    ]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("undoes the last change", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    expect(screen.getByTitle("Undo the last change")).toBeDisabled();
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await waitFor(() => expect(screen.getByTitle("Undo the last change")).toBeEnabled());
    fireEvent.click(screen.getByTitle("Undo the last change"));
    await vi.advanceTimersByTimeAsync(900);
    const first = screen.getAllByRole("listitem")[0]!;
    expect(within(first).getByText("Walks to where the activity happens")).toBeInTheDocument();
  });

  it("refuses to overwrite work another window saved", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({
      onSave: () =>
        json({ detail: { code: "VOCABULARY_CHANGED_ELSEWHERE", message: "The stored vocabulary changed." } }, 409),
    });
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    expect(await screen.findByText(/Changed in another window/)).toBeInTheDocument();
  });

  it("warns once the ground-truth labels have moved, and not before", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({
      onSave: () => json({ pack: fixturePack(), customised: true, digest: "d2", labelSpaceDigest: "MOVED" }),
    });
    renderPage();
    await screen.findByText("Opens the fridge");
    expect(screen.queryByText(/ground-truth labels have changed/)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    expect(await screen.findByText(/ground-truth labels have changed/)).toBeInTheDocument();
  });

  it("shows a branching activity but does not offer to reorder it", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByText("Night toilet visit"));
    expect(await screen.findByText(/branches, so its steps are shown but cannot be reordered/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Move later")).not.toBeInTheDocument();
  });

  it("resets to the vocabulary the simulator ships with", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({ onSave: () => json({ pack: fixturePack(), customised: true, digest: "d2", labelSpaceDigest: "l" }) });
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    await screen.findByText("Edited");
    fireEvent.click(screen.getByRole("button", { name: /Reset the vocabulary/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Reset the vocabulary/ }));
    expect(await screen.findByText("As shipped")).toBeInTheDocument();
  });

  it("creates an activity and says what that costs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /New activity/ }));
    expect(screen.getByText(/A new activity is a new ground-truth label/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Water the plants"), { target: { value: "Water the plants" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.intents.map((item) => item.intentId)).toContain("water_the_plants");
  });

  it("adds a step from the list of actions that exist", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.change(screen.getByLabelText("Action to add"), { target: { value: "close" } });
    fireEvent.click(screen.getByRole("button", { name: /Add to the end/ }));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(draft.actionNodes(body.pack.intents[0]!.processModel)).toHaveLength(6);
  });

  it("opens a step to edit what it is done to", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByText("Opens the fridge"));
    const field = screen.getByLabelText("target");
    fireEvent.change(field, { target: { value: "cooking_appliance" } });
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(await screen.findByText("Opens the hob")).toBeInTheDocument();
  });
});

describe("the actions tab", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("explains a gesture, an elastic action and one nothing sees", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Actions" }));
    const rows = await screen.findAllByRole("row");
    const wait = rows.find((row) => within(row).queryByText("wait"))!;
    expect(within(wait).getByText("fills the activity")).toBeInTheDocument();
    expect(within(wait).getByText("nothing — only that she is in the room")).toBeInTheDocument();
    const move = rows.find((row) => within(row).queryByText("move_to"))!;
    expect(within(move).getByText("as long as the walk")).toBeInTheDocument();
  });

  it("will not let a travel action be given a fixed length", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Actions" }));
    fireEvent.click(screen.getByLabelText("Edit move_to"));
    expect(await screen.findByText(/its length is the path the planner lays out/)).toBeInTheDocument();
  });

  it("creates an action from a plain description", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Actions" }));
    fireEvent.click(screen.getByRole("button", { name: /New action/ }));
    fireEvent.change(screen.getByPlaceholderText("water plants"), { target: { value: "water plants" } });
    fireEvent.click(screen.getByRole("button", { name: /Create the action/ }));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.actions.map((item) => item.definition.actionType)).toContain("water_plants");
  });
});

describe("the furniture tab", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("says what an object is for, what activities call it, and whether anything uses it", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Furniture" }));
    fireEvent.click(await screen.findByText("Fridge"));
    // Twice: once as one of the fridge's roles, once inside the sentence explaining what a
    // role is. Both are meant to be there.
    expect((await screen.findAllByText("food_storage")).length).toBeGreaterThan(0);
    // The activity list under "which activities use it" names the one that binds to the fridge.
    expect(screen.getAllByText("Eat breakfast").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByText("Aquarium")[0]!);
    expect(await screen.findByText(/Nothing binds to it/)).toBeInTheDocument();
    expect(screen.getByText(/it appears on the plan and in the replay as a dashed box/)).toBeInTheDocument();
  });

  it("takes a drawing for a kind of furniture that has none", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Furniture" }));
    fireEvent.click((await screen.findAllByText("Aquarium"))[0]!);
    fireEvent.change(screen.getByLabelText(/^Shape/), {
      target: { value: '<ellipse cx="0" cy="0" rx="18" ry="11" fill="none" stroke="currentColor" />' },
    });
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.entityTypes.find((item) => item.entityType === "aquarium")!.symbolBody).toContain("ellipse");
    expect(await screen.findByText("Drawn with the shape below.")).toBeInTheDocument();
  });

  it("adds a capability and takes it away again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Furniture" }));
    fireEvent.click((await screen.findAllByText("Aquarium"))[0]!);
    const entry = screen.getByPlaceholderText("food_preparation");
    fireEvent.change(entry, { target: { value: "personal_care_support" } });
    fireEvent.keyDown(entry, { key: "Enter" });
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved.length).toBeGreaterThan(0));
    const body = saved[saved.length - 1] as { pack: VocabularyPack };
    expect(body.pack.entityTypes.find((item) => item.entityType === "aquarium")!.capabilities).toEqual([
      "personal_care_support",
    ]);
  });
});

describe("what is missing", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("groups findings by what they cost and names who is affected", async () => {
    mockApi({ gaps: report() });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText("Will quietly make the dataset worse")).toBeInTheDocument();
    expect(screen.getByText("Worth knowing")).toBeInTheDocument();
    expect(screen.getByText("Used by: eat_breakfast")).toBeInTheDocument();
  });

  it("says so when nothing is missing", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText("Nothing is missing")).toBeInTheDocument();
  });
});

describe("when things go wrong", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("offers to try again when the vocabulary cannot be loaded", async () => {
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        attempts += 1;
        if (attempts === 1) return json({ error: { code: "BROKEN", message: "The pack is unreadable." } }, 500);
        return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
      }),
    );
    renderPage();
    expect(await screen.findByText("The pack is unreadable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Eat breakfast")).toBeInTheDocument();
  });

  it("reports a save that failed for any other reason, without losing the edit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({ onSave: () => json({ detail: { code: "DISK_FULL", message: "No space left." } }, 507) });
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getAllByLabelText("Move later")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    expect(await screen.findByText("No space left.")).toBeInTheDocument();
    // The edit is still on screen: a failed save must not silently revert what was typed.
    const first = screen.getAllByRole("listitem")[0]!;
    expect(within(first).getByText("Opens the fridge")).toBeInTheDocument();
  });

  it("reports a reset that failed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        if (url.endsWith("/api/vocabulary/review")) return json({ digest: "d", labelSpaceDigest: "l", report: emptyReport });
        if (init?.method === "DELETE") return json({ error: { message: "Could not delete the pack." } }, 500);
        return json({ pack: fixturePack(), customised: true, digest: "d", labelSpaceDigest: "l" });
      }),
    );
    renderPage();
    await screen.findByText("Edited");
    fireEvent.click(screen.getByRole("button", { name: /Reset the vocabulary/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Reset the vocabulary/ }));
    expect(await screen.findByText("Could not delete the pack.")).toBeInTheDocument();
  });

  it("carries on when the review cannot be fetched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        if (url.endsWith("/api/vocabulary/review")) return json({ error: { message: "no" } }, 500);
        return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
      }),
    );
    renderPage();
    // The findings are advisory; losing them must not stop the editor from working.
    expect(await screen.findByText("Opens the fridge")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText("Checking the vocabulary…")).toBeInTheDocument();
  });
});

describe("readings that have no dictionary entry", () => {
  it("falls back through role, value and finally the identifier itself", () => {
    expect(roleNoun("food_storage")).toBe("the fridge");
    expect(roleNoun("wash_face")).toBe("Washes her face");
    expect(roleNoun("book_storage")).toBe("book storage");
  });

  it("names an argument decided at run time without pretending to know it", () => {
    const pack = fixturePack();
    const node = {
      ...stepsOf(pack, "eat_breakfast")[1]!,
      arguments: { target: { source: "activity_intent" as const, value: null, variableId: null, index: null } },
    };
    expect(stepPhrase(node)).toBe("Opens what this activity calls for");
  });

  it("says 'it' when an action that wants an argument was given none", () => {
    const pack = fixturePack();
    expect(stepPhrase({ ...stepsOf(pack, "eat_breakfast")[1]!, arguments: {} })).toBe("Opens it");
  });

  it("treats a step calling an action the pack does not have as leaving nothing behind", () => {
    const pack = fixturePack();
    const orphan = { ...stepsOf(pack, "sleep")[0]!, actionType: "teleport" };
    expect(stepEvidence(pack, orphan)).toEqual([{ kind: "presence", label: "presence only" }]);
    expect(stepTiming(undefined, orphan)).toBe("unknown");
  });
});

describe("changing an action in place", () => {
  it("patches only the action named", () => {
    const pack = draft.updateAction(fixturePack(), "open", { gestureSeconds: 9 });
    expect(actionOf(pack, "open")!.gestureSeconds).toBe(9);
    expect(actionOf(pack, "close")!.gestureSeconds).toBe(3);
  });
});

describe("editing the parts of a step that are not a role", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows an argument decided per activity as read-only rather than as a blank field", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByText("Walks to where the activity happens"));
    expect(await screen.findByDisplayValue("decided per activity (activity_location)")).toHaveAttribute("readonly");
  });

  it("offers a share of the time only for a step that fills the activity", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByText("Sleep"));
    // A three-second gesture has no share to set; an elastic step does.
    fireEvent.click(await screen.findByText("Waits — asleep"));
    const weight = screen.getByLabelText(/Share of the activity/);
    fireEvent.change(weight, { target: { value: "6" } });
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    const sleep = body.pack.intents.find((item) => item.intentId === "sleep")!;
    expect(draft.actionNodes(sleep.processModel)[1]!.durationWeight).toBe(6);
  });

  it("removes a step", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getAllByLabelText("Remove this step")[0]!);
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(draft.actionNodes(body.pack.intents[0]!.processModel)).toHaveLength(4);
  });

  it("removes an activity and selects another", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.click(screen.getByRole("button", { name: /Remove the activity/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Remove the activity/ }));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.intents.map((item) => item.intentId)).not.toContain("eat_breakfast");
  });

  it("filters the activity list and says when nothing matches", async () => {
    mockApi();
    renderPage();
    const filter = await screen.findByLabelText("Filter activities");
    fireEvent.change(filter, { target: { value: "toilet" } });
    expect(await screen.findByText("Night toilet visit")).toBeInTheDocument();
    expect(screen.queryByText("Eat breakfast")).not.toBeInTheDocument();
    fireEvent.change(filter, { target: { value: "zzzz" } });
    expect(await screen.findByText("Nothing matches that.")).toBeInTheDocument();
  });

  it("changes the room an activity happens in", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    await screen.findByText("Opens the fridge");
    fireEvent.change(screen.getByLabelText("Activity name"), { target: { value: "Eat something" } });
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.intents[0]!.label).toBe("Eat something");
  });

  it("cancels creating an activity and creating an action", async () => {
    mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /New activity/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByPlaceholderText("Water the plants")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Actions" }));
    fireEvent.click(await screen.findByRole("button", { name: /New action/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByPlaceholderText("water plants")).not.toBeInTheDocument();
  });

  it("switches an action between a gesture and one that fills the activity", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Actions" }));
    fireEvent.click(screen.getByLabelText("Edit open"));
    fireEvent.click(await screen.findByText(/It fills the activity/));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved.length).toBeGreaterThan(0));
    let body = saved[saved.length - 1] as { pack: VocabularyPack };
    expect(actionOf(body.pack, "open")!.gestureSeconds).toBeNull();

    fireEvent.click(screen.getByText(/It is a quick gesture/));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved.length).toBeGreaterThan(1));
    body = saved[saved.length - 1] as { pack: VocabularyPack };
    expect(actionOf(body.pack, "open")!.gestureSeconds).toBe(3);
  });

  it("turns off the motion a still action should not produce", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Actions" }));
    fireEvent.click(screen.getByLabelText("Edit open"));
    fireEvent.click(await screen.findByText(/The motion detector watching the object sees this/));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved.length).toBeGreaterThan(0));
    const body = saved[saved.length - 1] as { pack: VocabularyPack };
    expect(actionOf(body.pack, "open")!.observability.motionAtObject).toBe(false);
  });

  it("adds a kind of furniture from the rail", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { saved } = mockApi();
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Furniture" }));
    fireEvent.change(await screen.findByLabelText("New furniture name"), { target: { value: "Book case" } });
    fireEvent.click(screen.getByRole("button", { name: "Add this kind of furniture" }));
    await vi.advanceTimersByTimeAsync(900);
    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as { pack: VocabularyPack };
    expect(body.pack.entityTypes.map((item) => item.entityType)).toContain("book_case");
  });
});

describe("a drawing the researcher authored", () => {
  afterEach(() => {
    setCustomSymbols({});
    cleanup();
    vi.unstubAllGlobals();
  });

  it("wins over the bundled glyph, so the plan and the replay draw it too", () => {
    // Without a pack drawing, a known type uses the glyph that ships with the app and an unknown
    // one gets nothing — which is what makes it a dashed box.
    expect(furnitureSymbol("refrigerator")).toBe("refrigerator");
    // `bookcase` is a spelling of a type the app *does* draw, so the interesting case is one it
    // has never heard of.
    expect(furnitureSymbol("aquarium")).toBeUndefined();
    expect(furnitureSymbol(undefined)).toBeUndefined();

    setCustomSymbols({ aquarium: "<rect />", refrigerator: "<circle />" });
    expect(furnitureSymbol("aquarium")).toBe("custom-aquarium");
    expect(furnitureSymbol("refrigerator")).toBe("custom-refrigerator");
    expect(customSymbolId("sofa")).toBeUndefined();
  });

  it("is published as a symbol the canvases can reference by id", () => {
    setCustomSymbols({ bookcase: '<rect x="-10" y="-10" width="20" height="20" />' });
    const { container } = render(
      <svg>
        <CustomFurnitureSymbols />
      </svg>,
    );
    const symbol = container.querySelector("#furn-custom-bookcase");
    expect(symbol).not.toBeNull();
    expect(symbol!.getAttribute("viewBox")).toBe("-24 -24 48 48");
    expect(symbol!.querySelector("rect")).not.toBeNull();
  });

  it("reaches a canvas that was already on screen when the pack loaded", async () => {
    const { container } = render(
      <svg>
        <CustomFurnitureSymbols />
      </svg>,
    );
    expect(container.querySelector("#furn-custom-bookcase")).toBeNull();
    await act(async () => setCustomSymbols({ bookcase: "<rect />" }));
    expect(container.querySelector("#furn-custom-bookcase")).not.toBeNull();
  });

  it("is loaded once at startup, and a failure leaves the bundled glyphs in charge", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        if (url.endsWith("/api/vocabulary")) {
          return json({
            pack: {
              ...fixturePack(),
              entityTypes: [
                { entityType: "bookcase", displayName: "Bookcase", capabilities: [], roleAliases: [], contactInstrumented: false, symbolId: null, symbolBody: "<rect />" },
                { entityType: "sofa", displayName: "Sofa", capabilities: [], roleAliases: [], contactInstrumented: false, symbolId: null, symbolBody: null },
              ],
            },
            customised: true,
            digest: "d",
            labelSpaceDigest: "l",
          });
        }
        return json({});
      }),
    );
    function Probe() {
      useCustomSymbols();
      return <span>probe</span>;
    }
    render(<Probe />);
    await waitFor(() => expect(furnitureSymbol("bookcase")).toBe("custom-bookcase"));
    // A type with no drawing of its own is left to the bundled glyph.
    expect(furnitureSymbol("sofa")).toBe("sofa");
  });

  it("keeps what it has when the pack cannot be fetched", async () => {
    setCustomSymbols({ bookcase: "<rect />" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/session")) return json({ token: "t" });
        return json({ error: { message: "gone" } }, 500);
      }),
    );
    function Probe() {
      useCustomSymbols();
      return <span>probe</span>;
    }
    render(<Probe />);
    await waitFor(() => expect(screen.getByText("probe")).toBeInTheDocument());
    expect(furnitureSymbol("bookcase")).toBe("custom-bookcase");
  });
});

describe("how often the findings are recomputed", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("reviews on a pause, not on a keystroke", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let reviews = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        if (url.endsWith("/api/vocabulary/review")) {
          reviews += 1;
          return json({ digest: "d", labelSpaceDigest: "l", report: emptyReport });
        }
        return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
      }),
    );
    renderPage();
    await screen.findByText("Opens the fridge");
    await vi.advanceTimersByTimeAsync(500);
    const afterLoad = reviews;

    // Ten characters into the name field. Undebounced this posted the whole pack ten times.
    const field = screen.getByLabelText("Activity name");
    for (const value of ["S", "Sv", "Sve", "Sveg", "Svegl", "Sveglia", "Svegliar", "Svegliars", "Svegliarsi"]) {
      fireEvent.change(field, { target: { value } });
      await vi.advanceTimersByTimeAsync(60);
    }
    expect(reviews).toBe(afterLoad);

    await vi.advanceTimersByTimeAsync(500);
    expect(reviews).toBe(afterLoad + 1);
  });

  it("updates the findings in both directions as the vocabulary changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let broken = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/session")) return json({ token: "t" });
        if (url.endsWith("/api/vocabulary/review")) {
          const sent = JSON.parse(String(init!.body)) as { pack: VocabularyPack };
          // The server's own answer, mimicked: a role no furniture answers is a finding.
          broken = sent.pack.intents.some((intent) =>
            intent.processModel.nodes.some((node) =>
              Object.values(node.arguments).some((argument) => argument.value === "invented_fridge"),
            ),
          );
          return json({ digest: "d", labelSpaceDigest: "l", report: broken ? report() : emptyReport });
        }
        return json({ pack: fixturePack(), customised: false, digest: "d", labelSpaceDigest: "l" });
      }),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText("Nothing is missing")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Activities" }));
    fireEvent.click(await screen.findByText("Opens the fridge"));
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "invented_fridge" } });
    await vi.advanceTimersByTimeAsync(1000);

    fireEvent.click(screen.getByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText(/No furniture answers to 'drinking_glass'/)).toBeInTheDocument();

    // And back again once it is put right — a finding that is fixed disappears.
    fireEvent.click(screen.getByRole("tab", { name: "Activities" }));
    fireEvent.click(await screen.findByText(/Opens/));
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "food_storage" } });
    await vi.advanceTimersByTimeAsync(1000);
    fireEvent.click(screen.getByRole("tab", { name: /What is missing/ }));
    expect(await screen.findByText("Nothing is missing")).toBeInTheDocument();
  });
});
