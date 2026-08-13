import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { HomeModel, JobRecord, SensorModel } from "../types";

const now = "2026-07-22T10:00:00Z";
const job: JobRecord = { jobId: "run_1", homeId: "home_1", kind: "materialization", status: "completed", progress: { phase: "completed", percent: 100, completedUnits: 1, totalUnits: 1, message: "Done" }, requestedAt: now, startedAt: now, finishedAt: now, seed: 7 };
const homeModel: HomeModel = { schemaVersion: "1.0.0", documentType: "home_model", homeId: "model_home", homeVersion: "1", coordinateSystem: {}, regions: [{ regionId: "room", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } }], connections: [], obstacles: [], interactionPoints: [{ interactionPointId: "point", regionId: "room", position: { x: 1, y: 1 }, approachRadiusMeters: 1 }], entities: [{ entityId: "door", entityType: "door", regionId: "room", interactionPointId: "point", capabilities: [{ capability: "access", roles: ["door"], supportedOperations: ["open"] }], initialState: { open: false } }], locationBindings: [], resourceBindings: [], kinematicDefaults: {} };
const sensorModel: SensorModel = { schemaVersion: "1.0.0", documentType: "sensor_model", sensorModelId: "s", sensorModelVersion: "1", sourceBundleId: "b", sourceBundleSha256: "a".repeat(64), seed: 7, regionIds: ["room"], entityIds: ["door"], sensors: [{ sensorId: "pir", sensorType: "pir", position: { x: 2, y: 2 }, regionIds: ["room"], coverage: homeModel.regions[0].boundary, timing: { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 }, errorModel: { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 }, failureWindows: [] }] };
const home = { homeId: "home_1", name: "Golden home", description: "Acceptance", residentCount: 1, runCount: 1, issueCount: 0, currentHomeArtifactId: "artifact_home", currentSensorArtifactId: "artifact_sensor", createdAt: now, updatedAt: now };
const resident = { residentId: "resident_1", homeId: "home_1", sourceResidentId: "mario", displayName: "Mario", scenarioArtifactId: "scenario", behaviorArtifactId: "behavior", createdAt: now };
const overview = { workspace: { workspaceId: "workspace", name: "Test lab", formatVersion: "1.0.0", createdAt: now, updatedAt: now, diagnosticMode: false, homeCount: 1, residentCount: 1, runCount: 1, activeJobCount: 0, artifactCount: 8 }, homes: [home], residents: [resident], jobs: [job] };

function response(value: unknown, init: ResponseInit = {}): Promise<Response> {
  return Promise.resolve(new Response(value === undefined ? null : JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" }, ...init }));
}

let overrides: Record<string, unknown> = {};

function installApi() {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^.*\/api/, "");
    if (url in overrides) {
      const override = overrides[url];
      if (typeof override === "function") return (override as (options?: RequestInit) => Promise<Response>)(init);
      if (override instanceof Response) return Promise.resolve(override);
      return response(override);
    }
    if (url === "/overview") return response(overview);
    if (url === "/homes") return init?.method === "POST" ? response(home, { status: 201 }) : response([home]);
    if (url === "/homes/home_1") return response({ home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job] });
    if (url === "/jobs?limit=500") return response([job]);
    if (url === "/jobs/run_1") return response({ job, events: [], artifacts: { home_model: { artifactId: "artifact_home", role: "home_model", sha256: "a".repeat(64), sizeBytes: 100 } } });
    if (url.startsWith("/runs/run_1/diary")) return response({ total: 1, items: [{ activityExecutionId: "activity_1", sourceActivityId: "source_1", actorId: "mario", intent: "prepare_meal", processModelId: "process", plannedStart: now, plannedEnd: now, actualStart: now, actualEnd: now, status: "completed", actions: [{ actionExecutionId: "action_1", nodeId: "node", actionType: "open_door", startedAt: now, endedAt: now, status: "completed", providerIds: ["door"] }], movementIds: ["move"], deviationIds: [], traceId: "trace", traceSemanticDigest: "b".repeat(64) }] });
    if (url.startsWith("/runs/run_1/observations")) return response({ total: 1, mode: url.includes("true") ? "oracle" : "observable", items: [{ observationId: "observation", sensorId: "pir", sensorType: "pir", observedAt: now, measurement: "motion", value: "ON", quality: "nominal", ...(url.includes("true") ? { oracleCause: { origin: "simulated_cause", causeType: "movement", causeIds: ["move"], residentIds: ["mario"], activityExecutionIds: ["activity_1"], actionExecutionIds: [] } } : {}) }] });
    if (url.startsWith("/runs/run_1/timeline")) return response([{ at: now, end: now, kind: "movement", id: "move", actorId: "mario", label: "walk", status: "completed", waypoints: [{ at: now, regionId: "room", position: { x: 1, y: 1 } }] }]);
    if (url === "/runs/run_1/models") return response({ homeModel, sensorModel });
    if (url === "/runs/run_1/replay/verify") return response({ matches: true, actualSemanticDigest: "b".repeat(64) });
    if (url === "/runs/run_1/exports") return response({ exportId: "export_1", runId: "run_1", sourceBundleSha256: "a".repeat(64), sourceTraceSemanticDigest: "b".repeat(64), seed: 7, createdAt: now, observableOracleSeparated: true, files: [{ role: "observable", format: "jsonl", relativePath: "export_1/observable.jsonl", mediaType: "application/x-ndjson", recordCount: 1, sizeBytes: 10, sha256: "c".repeat(64) }] }, { status: 201 });
    if (url.includes("/authoring")) return response({ valid: true, issues: [], scenarioArtifact: { artifactId: "scenario" } });
    if (url.includes("/runs") && init?.method === "POST") return response(job, { status: 202 });
    if (url.includes("/home-model") || url.includes("/sensor-model")) return response({ valid: true, issues: [] });
    return response([]);
  }));
}

function mount(path: string) { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }

describe("complete application routes", () => {
  beforeEach(() => { sessionStorage.setItem("habitat-lab-session", "token"); localStorage.clear(); overrides = {}; installApi(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it.each([
    ["/", "Good evidence starts"], ["/homes", "Workspace catalogue"], ["/residents", "People and provenance"],
    ["/simulations", "Execution centre"], ["/exports", "Portable datasets"], ["/help", "Generate one authoring bundle"],
    ["/generate", "Generate a home input from a brief"], ["/missing", "does not exist"],
  ])("renders %s", async (path, text) => {
    mount(path); expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
  });

  it("runs local generation and shows the review", async () => {
    const sources: FakeEventSource[] = [];
    class FakeEventSource {
      listeners: Record<string, () => void> = {};
      closed = false;
      constructor(public url: string) { sources.push(this); }
      addEventListener(type: string, cb: () => void) { this.listeners[type] = cb; }
      close() { this.closed = true; }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    let status = "running";
    const record = () => ({
      jobId: "gen_1", kind: "generation", status,
      progress: { phase: status === "completed" ? "horizon" : "persona", percent: status === "completed" ? 100 : 12, completedUnits: 0, message: "working" },
      requestedAt: now,
    });
    overrides["/generation"] = () => response(record(), { status: 202 });
    overrides["/jobs/gen_1"] = () => response({ job: record() });
    overrides["/generation/gen_1/artifact/persona.json"] = { name: "Elena", age: 72, city: "Bologna" };
    overrides["/generation/gen_1/artifact/behavioral-profile.json"] = { recurringActivities: [1, 2, 3] };
    overrides["/generation/gen_1/artifact/batch-manifest.json"] = { runs: [1, 2] };
    overrides["/generation/gen_1/artifact/planned-activity-trace.json"] = { entries: [1, 2, 3, 4] };
    mount("/generate");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "an elderly woman" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    await waitFor(() => expect(sources.length).toBeGreaterThan(0));
    status = "completed";
    sources[0].listeners.done();
    expect(await screen.findByText("Elena")).toBeInTheDocument();
    expect(sources[0].closed).toBe(true);
  });

  it("surfaces a generation start error", async () => {
    overrides["/generation"] = () => response({ error: { message: "endpoint down" } }, { status: 500 });
    mount("/generate");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "brief" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(await screen.findByText(/endpoint down/)).toBeInTheDocument();
  });

  it("expands a horizon outline in the application and reports what it produced", async () => {
    overrides["/homes/home_1"] = { home: { ...home, residentCount: 0 }, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1/horizon-outline?seed=1"] = { valid: true, issues: [], expansion: { dayCount: 243, activityCount: 2535, habitBandCount: 5 } };
    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    const outline = new File(["{}"], "outline.json", { type: "application/json" });
    Object.defineProperty(outline, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText("Horizon outline"), { target: { files: [outline] } });
    fireEvent.click(screen.getByRole("button", { name: "Expand and import outline" }));
    // The counts are the whole point of showing anything: a structure went in, days came out.
    expect(await screen.findAllByText(/243 days, 2535 activities and 5 habit bands/)).not.toHaveLength(0);
  });

  it("shows the single sentence when an outline is refused before any day exists", async () => {
    overrides["/homes/home_1"] = { home: { ...home, residentCount: 0 }, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1/horizon-outline?seed=1"] = { valid: false, message: "the rhythm emits these intents on its own and the process package must implement them too: sleep, wake_up" };
    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    const outline = new File(["{}"], "outline.json", { type: "application/json" });
    Object.defineProperty(outline, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText("Horizon outline"), { target: { files: [outline] } });
    fireEvent.click(screen.getByRole("button", { name: "Expand and import outline" }));
    expect(await screen.findAllByText(/the rhythm emits these intents on its own/)).not.toHaveLength(0);
  });

  it("reports an import the server is still working on, and then one it has lost", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    overrides["/homes/home_1"] = { home: { ...home, residentCount: 0 }, residents: [], models: {}, jobs: [] };
    // Never settles: the case the spinner could not tell apart from slow work.
    overrides["/homes/home_1/horizon-outline?seed=1"] = () => new Promise<Response>(() => {});
    let holding = true;
    vi.stubGlobal("fetch", ((original) => (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api/, "");
      if (url.startsWith("/health")) {
        return response({
          status: "ok",
          inFlight: holding ? 1 : 0,
          operation: holding
            ? { operationId: "op", method: "POST", path: "/horizon-outline", stage: "expanding 8 months into days", elapsedSeconds: 4 }
            : null,
        });
      }
      return original(input, init);
    })(globalThis.fetch as typeof fetch));

    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    const outline = new File(["{}"], "outline.json", { type: "application/json" });
    Object.defineProperty(outline, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText("Horizon outline"), { target: { files: [outline] } });
    fireEvent.click(screen.getByRole("button", { name: "Expand and import outline" }));

    await vi.advanceTimersByTimeAsync(3500);
    expect(await screen.findByText(/expanding 8 months into days/)).toBeInTheDocument();

    holding = false;
    await vi.advanceTimersByTimeAsync(12000);
    expect(await screen.findByText(/no longer working on this request/)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("offers the horizon outline prompt apart, since its output is expanded rather than imported", async () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- typed arg keeps mock.calls tuples
    const writeText = vi.fn(async (_text: string): Promise<void> => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    mount("/help");
    await screen.findByRole("heading", { name: "Horizons longer than a month" });
    fireEvent.change(screen.getByLabelText(/Person and case description/), { target: { value: "Nicoletta Palmi, 8 months" } });
    const copyButtons = screen.getAllByRole("button", { name: "Copy prompt" });
    fireEvent.click(copyButtons[2]);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const prompt = writeText.mock.calls[0]?.[0] ?? "";
    expect(prompt).toContain("Nicoletta Palmi, 8 months");
    expect(prompt).toContain("generate-horizon-outline-1.0.0");
    expect(prompt).toContain("Do not write the days of the horizon.");
    expect(prompt).not.toContain("{{PERSON_AND_CASE_DESCRIPTION}}");
    // The guide must say the response cannot be imported as it stands, or a reader will try.
    expect(screen.getByText(/Its response is expanded, not imported as it stands/)).toBeInTheDocument();
    expect(screen.getByText(/expand-outline/)).toBeInTheDocument();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  });

  it("provides personalized simplified and Advanced prompts in the integrated guide", async () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- typed arg keeps mock.calls tuples
    const writeText = vi.fn(async (_text: string): Promise<void> => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    mount("/help");
    await screen.findByRole("heading", { name: "Generate one authoring bundle" });
    fireEvent.change(screen.getByLabelText(/Person and case description/), { target: { value: "Lucia Rossi, August 2026" } });
    const copyButtons = screen.getAllByRole("button", { name: "Copy prompt" });
    fireEvent.click(copyButtons[0]);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0]?.[0]).toContain("Lucia Rossi, August 2026");
    expect(writeText.mock.calls[0]?.[0]).not.toContain("[PERSON_AND_CASE_DESCRIPTION]");
    fireEvent.click(copyButtons[1]);
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    expect(writeText.mock.calls[1]?.[0]).toContain("simulation_authoring_bundle");
    expect(writeText.mock.calls[1]?.[0]).toContain("generate-simulation-inputs-1.2.3-simplified");
    expect(writeText.mock.calls[1]?.[0]).not.toContain("[GENERATION_TIMESTAMP]");
    expect(writeText.mock.calls[1]?.[0]).toMatch(/20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d/);
    writeText.mockRejectedValueOnce(new Error("Clipboard denied"));
    fireEvent.click(copyButtons[0]);
    expect(await screen.findByRole("button", { name: "Copy failed" })).toBeInTheDocument();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    fireEvent.click(copyButtons[1]);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Copy failed" })).toHaveLength(2));
  });

  it("creates a home and exercises the undoable home and sensor editors", async () => {
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    fireEvent.click(screen.getByRole("button", { name: "room room" }));
    fireEvent.change(screen.getByLabelText("Kind", { selector: "select" }), { target: { value: "outdoor" } });
    fireEvent.click(screen.getByRole("button", { name: "Room" }));
    fireEvent.click(screen.getByRole("button", { name: /Validate and publish plan/ }));
    await screen.findByText(/Plan validated and published/);
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));
    fireEvent.change(screen.getByLabelText("X position"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "temperature" }));
    fireEvent.click(screen.getByText("Undo"));
    fireEvent.click(screen.getByText("Redo"));
    fireEvent.click(screen.getByLabelText("Zoom in"));
    fireEvent.click(screen.getByLabelText("Zoom out"));
    fireEvent.click(screen.getByLabelText("Pan left"));
    fireEvent.click(screen.getByLabelText("Pan up"));
    fireEvent.click(screen.getByLabelText("Pan down"));
    fireEvent.click(screen.getByLabelText("Pan right"));
    fireEvent.click(screen.getByLabelText("Fit plan"));
  });

  it("presents a generated plan as a recommendation until the researcher answers", async () => {
    // Until it is answered, the planimetry on screen is a proposal, and the page says so and
    // offers the two ways of answering: take it as it stands, or open it and change it.
    const approve = vi.fn(() => response({ homeId: "home_1", planApproval: { home: "researcher", sensor: "researcher", approved: true } }));
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job], planApproval: { home: "recommended", sensor: "recommended", approved: false } };
    overrides["/homes/home_1/plan-approval"] = approve;
    mount("/homes/home_1");

    await screen.findByText("This planimetry is a proposal");
    fireEvent.click(screen.getByRole("button", { name: /Confirm this plan/ }));

    await screen.findByText(/Plan confirmed/);
    expect(approve).toHaveBeenCalledTimes(1);
  });

  it("says nothing about approval for a plan the researcher already stands behind", async () => {
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job], planApproval: { home: "researcher", sensor: "researcher", approved: true } };
    mount("/homes/home_1");

    await screen.findByRole("heading", { name: "Golden home" });
    expect(screen.queryByText("This planimetry is a proposal")).not.toBeInTheDocument();
  });

  it("widens a PIR range from the inspector and keeps it inside the room", async () => {
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));

    const range = screen.getByLabelText("Range m") as HTMLInputElement;
    // The whole 4x4 room, so the control reads 2 metres around the node.
    expect(range.value).toBe("2");
    fireEvent.change(range, { target: { value: "0.5" } });
    expect((screen.getByLabelText("Range m") as HTMLInputElement).value).toBe("0.5");
  });

  it("reports a refused confirmation and drags nothing when nothing is selected", async () => {
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job], planApproval: { home: "recommended", sensor: "recommended", approved: false } };
    overrides["/homes/home_1/plan-approval"] = () => response({ error: { code: "WORKSPACE_OPERATION_FAILED", message: "this home has no plan to approve yet" } }, { status: 409 });
    mount("/homes/home_1");

    await screen.findByText("This planimetry is a proposal");
    fireEvent.click(screen.getByRole("button", { name: /Confirm this plan/ }));
    expect(await screen.findByText(/no plan to approve/)).toBeInTheDocument();

    // With no object selected there is nothing to move: the inspector says so instead of guessing.
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    expect(screen.getByText(/Select an object on the plan/)).toBeInTheDocument();
  });

  it("keeps the plain published-home callout for a generation whose plan is unavailable", async () => {
    const progress = { phase: "completed", percent: 100, completedUnits: 2, totalUnits: 2, message: "done" };
    const genJob = { jobId: "gen_2", homeId: "home_1", kind: "generation", status: "completed", progress, requestedAt: now, finishedAt: now, resultReference: "home_1" };
    overrides = {
      "/generations": [genJob],
      "/jobs/gen_2": { job: genJob },
      "/generation/gen_2/artifact/persona.json": { name: "Elena", age: 72, city: "Bologna" },
      "/generation/gen_2/artifact/behavioral-profile.json": { recurringActivities: [] },
      "/generation/gen_2/artifact/batch-manifest.json": { runs: [1] },
      "/generation/gen_2/artifact/planned-activity-trace.json": { entries: [] },
      "/homes/home_1": { home, residents: [resident], models: {}, jobs: [job] },
    };
    mount("/generate");
    fireEvent.click(await screen.findByText("gen_2"));

    expect(await screen.findByText(/Published as a home input/)).toBeInTheDocument();
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("keeps unpublished edits when the home reloads under them, and publishes one tab at a time", async () => {
    // A run in progress reloads the home on every progress event, and the drafts used to be
    // reseeded from the server each time — quietly discarding the wall you had just moved.
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));
    fireEvent.change(screen.getByLabelText("Range m"), { target: { value: "0.6" } });

    expect(await screen.findByText(/Unpublished edits/)).toBeInTheDocument();
    // The button says which of the two revisions it is about to create.
    expect(screen.getByRole("button", { name: /Validate and publish sensors/ })).toBeInTheDocument();

    // A reload arrives (as a running job would trigger); the edit survives it.
    fireEvent.click(screen.getByRole("tab", { name: "overview" }));
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));
    expect((screen.getByLabelText("Range m") as HTMLInputElement).value).toBe("0.6");

    fireEvent.click(screen.getByRole("button", { name: /Validate and publish sensors/ }));
    await screen.findByText(/Sensor field validated and published/);
    expect(screen.queryByText(/Unpublished edits/)).not.toBeInTheDocument();
  });

  it("opens diary, oracle observations, replay and complete export manifest", async () => {
    mount("/simulations/run_1");
    await screen.findByText("Persistent state");
    fireEvent.click(screen.getByRole("button", { name: "Export complete dataset" }));
    expect(await screen.findByText(/files across observable/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "diary" }));
    expect((await screen.findAllByText("prepare meal")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("tab", { name: "observations" }));
    fireEvent.click(screen.getByRole("button", { name: "Oracle links" }));
    expect(await screen.findByText("simulated cause")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "replay" }));
    fireEvent.click(await screen.findByRole("button", { name: /walk/ }));
    fireEvent.click(screen.getByRole("button", { name: /Verify semantic digest/ }));
    await waitFor(() => expect(screen.getByText(/Replay verified/)).toBeInTheDocument());
  });

  it("shows structured failed-run diagnostics without requesting unavailable evidence", async () => {
    const failed = { ...job, status: "failed" as const, progress: { ...job.progress, phase: "simulation", percent: 52, message: "Action precondition failed" }, errorCode: "PRECONDITION_FAILED", errorMessage: "Action 'leave_home' failed precondition 'resident.at_home'." };
    overrides["/jobs/run_1"] = { job: failed, artifacts: {}, events: [
      { jobId: "run_1", sequence: 4, occurredAt: now, eventType: "issue", level: "error", message: "Action 'leave_home' failed precondition 'resident.at_home'.", payload: { phase: "simulation", code: "PRECONDITION_FAILED", stage: "execution", path: "$.actionBindings[activity_7:action_02]", details: { activityId: "activity_7", actionType: "leave_home", expected: true, actual: false } } },
      { jobId: "run_1", sequence: 5, occurredAt: now, eventType: "issue", level: "error", message: "Additional diagnostic context", payload: { stage: "output", details: { context: { source: "worker" } } } },
    ] };
    mount("/simulations/run_1");
    expect(await screen.findByRole("heading", { name: "Execution evidence was not published" })).toBeInTheDocument();
    expect(screen.getAllByText("PRECONDITION_FAILED")).toHaveLength(2);
    expect(screen.getByText("$.actionBindings[activity_7:action_02]")).toBeInTheDocument();
    expect(screen.getByText("activity_7")).toBeInTheDocument();
    expect(screen.getByText('{"source":"worker"}')).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "diary" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "observations" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "replay" })).toBeDisabled();
    const requested = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requested.some((url) => url.includes("/runs/run_1/"))).toBe(false);
  });

  it("falls back to the job error when a failed run has no issue event", async () => {
    const failed = { ...job, status: "failed" as const, progress: { ...job.progress, phase: "failed", message: "Worker stopped" }, errorCode: undefined, errorMessage: undefined };
    overrides["/jobs/run_1"] = { job: failed, artifacts: {}, events: [] };
    mount("/simulations/run_1");
    expect(await screen.findByText("The run failed before execution evidence could be published.")).toBeInTheDocument();
    expect(screen.getByText("RUN_FAILED")).toBeInTheDocument();
    expect(screen.getByText(/Diary, observations and replay become available only after a completed run/)).toBeInTheDocument();

    cleanup();
    const exited = { ...failed, finishedAt: undefined, errorCode: "WORKER_EXIT", errorMessage: "Worker exited before publication." };
    overrides["/jobs/run_1"] = { job: exited, artifacts: {}, events: [] };
    mount("/simulations/run_1");
    expect(await screen.findByText("Worker exited before publication.")).toBeInTheDocument();
    expect(screen.getByText("WORKER_EXIT")).toBeInTheDocument();
  });

  it("covers diagnostic, empty and active dashboard states", async () => {
    const running = { ...job, jobId: "run_active", status: "running" as const, finishedAt: undefined, progress: { ...job.progress, phase: "simulation", percent: 40 } };
    overrides["/overview"] = { ...overview, workspace: { ...overview.workspace, diagnosticMode: true }, homes: [], jobs: [running] };
    class Source {
      onmessage = vi.fn();
      addEventListener = vi.fn();
      close = vi.fn();
      constructor(public url: string) { void url; }
    }
    vi.stubGlobal("EventSource", Source);
    mount("/");
    expect(await screen.findByText("Workspace opened in diagnostic mode")).toBeInTheDocument();
    expect(screen.getByText("No environment yet")).toBeInTheDocument();
    expect(screen.getByText("simulation")).toBeInTheDocument();
  });

  it("builds the home and sensors before any run, and keeps evidence views closed for it", async () => {
    const started = vi.fn(() => response({ ...job, jobId: "env_1", kind: "environment", status: "queued", finishedAt: undefined, progress: { phase: "queued", percent: 0, completedUnits: 0, message: "Waiting for a local worker" } }, { status: 202 }));
    overrides["/homes/home_1"] = { home: { ...home, currentHomeArtifactId: undefined, currentSensorArtifactId: undefined }, residents: [resident], models: {}, jobs: [] };
    overrides["/homes/home_1/environment"] = started;
    mount("/homes/home_1");
    await screen.findByText("Authoritative revisions");
    fireEvent.click(screen.getByRole("button", { name: /Generate home and sensors/ }));
    await waitFor(() => expect(started).toHaveBeenCalled());
    expect(await screen.findByText(/Nothing is executed until you start a run/)).toBeInTheDocument();

    cleanup();
    const environmentJob = { ...job, jobId: "env_1", kind: "environment" as const, progress: { ...job.progress, message: "Home and sensor field published; no simulation was executed" } };
    overrides["/jobs/env_1"] = { job: environmentJob, events: [], artifacts: { home_model: { artifactId: "artifact_home", role: "home_model", sha256: "a".repeat(64), sizeBytes: 100 } } };
    mount("/simulations/env_1");
    expect(await screen.findByText(/executed nothing/)).toBeInTheDocument();
    // A completed job with no trace must not offer the diary, the observations or the replay.
    expect(screen.getByRole("tab", { name: "diary" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Export complete dataset/ })).toBeDisabled();
  });

  it("reports an environment build the server refuses", async () => {
    overrides["/homes/home_1"] = { home: { ...home, currentHomeArtifactId: undefined, currentSensorArtifactId: undefined }, residents: [resident], models: {}, jobs: [] };
    overrides["/homes/home_1/environment"] = () => response({ error: { message: "all local workers are busy" } }, { status: 409 });
    mount("/homes/home_1");
    await screen.findByText("Authoritative revisions");
    fireEvent.click(screen.getByRole("button", { name: /Generate home and sensors/ }));
    expect(await screen.findByText("all local workers are busy")).toBeInTheDocument();
  });

  it("tells the dashboard what a startup reconciliation had to change", async () => {
    overrides["/overview"] = {
      ...overview,
      lastRepair: { performedAt: now, homesRemoved: 0, runsRemoved: 0, exportsRemoved: 1, artifactsPruned: 34, artifactsAdopted: 0, filesRemoved: 2, bytesFreed: 5_242_880, corruptRemaining: 0, details: ["forgot 34 catalogue entries whose file is no longer in the workspace folder"] },
    };
    mount("/");
    expect(await screen.findByText(/The workspace folder changed since the last session/)).toBeInTheDocument();
    expect(screen.getByText(/forgot 34 catalogue entries/)).toBeInTheDocument();
    expect(screen.getByText(/5.0 MB reclaimed/)).toBeInTheDocument();
    // Files a researcher deleted are not corruption, so nothing is paused.
    expect(screen.queryByText("Workspace opened in diagnostic mode")).toBeNull();
  });

  it("reports integrity, reconciles the folder and deletes a stored export", async () => {
    const finding = { kind: "missing" as const, relativePath: "exports/export_1/observable.csv", artifactId: "artifact_1", role: "export_observable_csv", sizeBytes: 2048, detail: "the file is no longer in the workspace folder" };
    let integrity = { checkedAt: now, diagnosticMode: false, missing: [finding], corrupt: [], orphans: [{ kind: "orphan" as const, relativePath: "exports/stray.csv", sizeBytes: 1024, detail: "not in the catalogue" }], reclaimableBytes: 1024 };
    let listed = [{ exportId: "export_1", runId: "run_1", createdAt: now, available: true, archived: false, fileCount: 3, sizeBytes: 4096 }];
    overrides["/workspace/integrity"] = () => response(integrity);
    overrides["/exports"] = () => response(listed);
    overrides["/workspace/repair?remove_orphans=true"] = () => {
      integrity = { ...integrity, missing: [], orphans: [], reclaimableBytes: 0 };
      return response({ summary: { performedAt: now, homesRemoved: 0, runsRemoved: 0, exportsRemoved: 0, artifactsPruned: 1, artifactsAdopted: 0, filesRemoved: 1, bytesFreed: 1024, corruptRemaining: 0, details: ["deleted 1 uncatalogued file(s) from the folder"] } });
    };
    overrides["/exports/export_1"] = () => {
      listed = [];
      return response({ performedAt: now, homesRemoved: 0, runsRemoved: 0, exportsRemoved: 1, artifactsPruned: 3, artifactsAdopted: 0, filesRemoved: 3, bytesFreed: 4096, corruptRemaining: 0, details: ["deleted export 'export_1' and its 3 catalogued file(s)"] });
    };
    mount("/maintenance");
    expect(await screen.findByText("exports/export_1/observable.csv")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Delete 1 uncatalogued file/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Delete 1 uncatalogued file/ })[0]);
    expect(await screen.findByText(/1.0 KB reclaimed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete export export_1" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Delete export export_1" })[0]);
    expect(await screen.findByText("No export has been built")).toBeInTheDocument();
  });

  it("keeps publication paused while content contradicts the catalogue", async () => {
    overrides["/workspace/integrity"] = { checkedAt: now, diagnosticMode: true, missing: [], corrupt: [{ kind: "corrupt", relativePath: "objects/abc.json", artifactId: "artifact_2", role: "home_model", sizeBytes: 10, detail: "size or digest mismatch" }], orphans: [], reclaimableBytes: 0 };
    overrides["/exports"] = [];
    mount("/maintenance");
    expect(await screen.findByText("Publication is paused")).toBeInTheDocument();
    expect(screen.getByText("objects/abc.json")).toBeInTheDocument();
  });

  it("surfaces a failed reconciliation without changing the report", async () => {
    overrides["/workspace/integrity"] = { checkedAt: now, diagnosticMode: false, missing: [], corrupt: [], orphans: [], reclaimableBytes: 0 };
    overrides["/exports"] = [];
    overrides["/workspace/repair?remove_orphans=false"] = () => response({ error: { message: "the folder is read only" } }, { status: 409 });
    mount("/maintenance");
    await screen.findByText("The folder and the catalogue agree");
    fireEvent.click(screen.getByRole("button", { name: /Reconcile now/ }));
    expect(await screen.findByText("the folder is read only")).toBeInTheDocument();
  });

  it("deletes a home and its evidence from the home workspace", async () => {
    const removed = vi.fn(() => response({ performedAt: now, homesRemoved: 1, runsRemoved: 1, exportsRemoved: 0, artifactsPruned: 9, artifactsAdopted: 0, filesRemoved: 9, bytesFreed: 2048, corruptRemaining: 0, details: ["deleted home 'Golden home' with 1 run(s) and 0 export(s)"] }));
    overrides["/homes/home_1"] = (options?: RequestInit) => options?.method === "DELETE" ? removed() : response({ home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job] });
    mount("/homes/home_1");
    await screen.findByText("Environment workspace");
    fireEvent.click(screen.getByRole("button", { name: /Delete home/ }));
    expect(screen.getByText(/Its 1 resident context\(s\), 1 run\(s\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByText(/Its 1 resident context/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Delete home/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Delete home/ })[0]);
    await waitFor(() => expect(removed).toHaveBeenCalled());
    expect(await screen.findByText("Workspace catalogue")).toBeInTheDocument();
  });

  it("refuses to delete a home the server still has work for", async () => {
    overrides["/homes/home_1"] = (options?: RequestInit) => options?.method === "DELETE"
      ? response({ error: { message: "wait for this home's active jobs to finish before deleting it" } }, { status: 409 })
      : response({ home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job] });
    mount("/homes/home_1");
    await screen.findByText("Environment workspace");
    fireEvent.click(screen.getByRole("button", { name: /Delete home/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Delete home/ })[0]);
    expect(await screen.findByText(/wait for this home's active jobs/)).toBeInTheDocument();
  });

  it("deletes a finished run from its detail page", async () => {
    const removed = vi.fn(() => response({ performedAt: now, homesRemoved: 0, runsRemoved: 1, exportsRemoved: 2, artifactsPruned: 12, artifactsAdopted: 0, filesRemoved: 12, bytesFreed: 4096, corruptRemaining: 0, details: ["deleted run 'run_1' and its 2 export(s)"] }));
    overrides["/jobs/run_1"] = (options?: RequestInit) => options?.method === "DELETE" ? removed() : response({ job, events: [], artifacts: {} });
    mount("/simulations/run_1");
    await screen.findByText("Run evidence");
    fireEvent.click(screen.getByRole("button", { name: /Delete run/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Delete run/ })[0]);
    await waitFor(() => expect(removed).toHaveBeenCalled());
    expect(await screen.findByText("Execution centre")).toBeInTheDocument();
  });

  it("reports a run deletion the server refuses", async () => {
    overrides["/jobs/run_1"] = (options?: RequestInit) => options?.method === "DELETE"
      ? response({ error: { message: "cancel this run before deleting it" } }, { status: 409 })
      : response({ job, events: [], artifacts: {} });
    mount("/simulations/run_1");
    await screen.findByText("Run evidence");
    fireEvent.click(screen.getByRole("button", { name: /Delete run/ }));
    fireEvent.click(screen.getAllByRole("button", { name: /Delete run/ })[0]);
    expect(await screen.findByText("cancel this run before deleting it")).toBeInTheDocument();
  });

  it("loads and persists the workspace theme preference", async () => {
    overrides["/settings/theme"] = { value: "dark" };
    mount("/");
    await screen.findByText("Good evidence starts with inspectable inputs.");
    await waitFor(() => expect(screen.getByLabelText("Use light theme")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Use light theme"));
    expect(localStorage.getItem("habitat-theme")).toBe('"light"');
  });

  it("uses home creation controls and the empty catalogue action", async () => {
    overrides["/homes"] = [];
    mount("/homes");
    await screen.findByText("Create an environment to begin");
    fireEvent.click(screen.getAllByRole("button", { name: /New home/ })[0]);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New lab" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Purpose" } });
    overrides["/homes"] = home;
    fireEvent.click(screen.getByRole("button", { name: /Create home/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Golden home" })).toBeInTheDocument());
  });

  it("filters homes from the global query and clears an empty result", async () => {
    overrides["/homes?query=missing"] = [];
    mount("/homes?query=missing");
    await screen.findByText("No homes match this search");
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(await screen.findByRole("heading", { name: "Golden home" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Filter homes"), { target: { value: "Golden" } });
    expect(screen.getByPlaceholderText("Filter homes")).toHaveValue("Golden");
  });

  it("imports accepted authoring without manual JSON editing and starts a run", async () => {
    const emptyDetail = { home: { ...home, residentCount: 0, runCount: 0, currentHomeArtifactId: undefined, currentSensorArtifactId: undefined }, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1"] = emptyDetail;
    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    const file = new File(["{}"], "input.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText(/Simulation authoring bundle/), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /Validate bundle and attach/ }));
    expect(await screen.findByText(/complete authoring bundle passed validation/)).toBeInTheDocument();
    cleanup(); overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [] };
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText(/queued in an isolated/)).toBeInTheDocument();
  });

  it("keeps split-document import Advanced and reports malformed bundle JSON", async () => {
    const emptyDetail = { home: { ...home, residentCount: 0 }, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1"] = emptyDetail;
    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    fireEvent.click(screen.getByText(/Advanced: import canonical documents separately/));
    const file = new File(["{}"], "canonical.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText(/Scenario JSON/), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText(/Personal process package/), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /Validate Advanced import/ }));
    expect(await screen.findByText(/complete authoring bundle passed validation/)).toBeInTheDocument();

    cleanup();
    mount("/homes/home_1");
    await screen.findByText("Attach accepted authoring");
    const malformed = new File(["{"], "broken-bundle.json", { type: "application/json" });
    Object.defineProperty(malformed, "text", { value: () => Promise.resolve("{") });
    fireEvent.change(screen.getByLabelText(/Simulation authoring bundle/), { target: { files: [malformed] } });
    fireEvent.click(screen.getByRole("button", { name: /Validate bundle and attach/ }));
    expect(await screen.findByText(/“broken-bundle.json” is not valid JSON/)).toBeInTheDocument();
  });

  it("edits all sensor types, nudges objects, removes drafts and imports models", async () => {
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    fireEvent.click(screen.getByRole("button", { name: "door door" }));
    fireEvent.change(screen.getByLabelText("Provider type"), { target: { value: "entry_door" } });
    fireEvent.change(screen.getByLabelText("Containing region"), { target: { value: "room" } });
    fireEvent.change(screen.getByLabelText("Roles"), { target: { value: "door, entrance" } });
    fireEvent.change(screen.getByLabelText("Operations"), { target: { value: "open, close" } });
    fireEvent.change(screen.getByLabelText("open"), { target: { value: "true" } });
    fireEvent.click(screen.getByRole("button", { name: "Add capability" }));
    fireEvent.click(screen.getByLabelText("Remove capability 2"));
    fireEvent.click(screen.getByRole("button", { name: "Move right" }));
    fireEvent.click(screen.getByRole("button", { name: "Obstacle" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove selected object" }));
    const homeFile = new File([JSON.stringify(homeModel)], "home.json"); Object.defineProperty(homeFile, "text", { value: () => Promise.resolve(JSON.stringify(homeModel)) });
    fireEvent.change(screen.getByLabelText(/Import home/), { target: { files: [homeFile] } });
    expect(await screen.findByText(/Home model loaded as a draft/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: "contact" }));
    fireEvent.click(screen.getByRole("button", { name: /contact sensor contact_01/ }));
    fireEvent.change(screen.getByLabelText("Entity"), { target: { value: "door" } });
    fireEvent.click(screen.getByRole("button", { name: "temperature" }));
    fireEvent.click(screen.getByRole("button", { name: /temperature sensor temperature_01/ }));
    fireEvent.change(screen.getByLabelText("Baseline °C"), { target: { value: "21" } });
    fireEvent.change(screen.getByLabelText("Dropout 0–1"), { target: { value: "0.02" } });
    fireEvent.click(screen.getByRole("button", { name: "Move up" }));
  });

  it("covers precise region, obstacle and PIR controls plus invalid model feedback", async () => {
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    fireEvent.click(screen.getByRole("button", { name: "room room" }));
    fireEvent.click(screen.getByLabelText("Traversable"));
    fireEvent.change(screen.getByLabelText("Vertex 1 X"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText("Vertex 1 Y"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Obstacle" }));
    fireEvent.change(screen.getByLabelText("Containing region"), { target: { value: "room" } });
    fireEvent.click(screen.getByRole("tab", { name: "sensors" }));
    fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add window" }));
    fireEvent.click(screen.getByLabelText("Remove failure window 1"));
    for (const [label, value] of [["Y position", "3"], ["Latency ms", "5"], ["Jitter ms", "2"], ["Cooldown ms", "10"], ["False negative 0–1", "0.01"], ["False positives/day", "0.02"], ["Noise σ", "0"]]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Move left" }));
    const sensorFile = new File([JSON.stringify(sensorModel)], "sensors.json"); Object.defineProperty(sensorFile, "text", { value: () => Promise.resolve(JSON.stringify(sensorModel)) });
    fireEvent.change(screen.getByLabelText(/Import sensors/), { target: { files: [sensorFile] } });
    expect(await screen.findByText(/Sensor model loaded as a draft/)).toBeInTheDocument();
    const invalid = new File(["[]"], "invalid.json"); Object.defineProperty(invalid, "text", { value: () => Promise.resolve("[]") });
    fireEvent.change(screen.getByLabelText(/Import sensors/), { target: { files: [invalid] } });
    expect(await screen.findByText(/must contain one JSON object/)).toBeInTheDocument();
  });

  it("renders empty grouped views, filters statuses and displays request errors", async () => {
    overrides["/overview"] = { ...overview, homes: [], residents: [], jobs: [] };
    mount("/residents"); expect(await screen.findByText("No residents attached")).toBeInTheDocument();
    cleanup(); overrides["/jobs?limit=500"] = []; mount("/simulations");
    await screen.findByText("No simulation evidence yet");
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "failed" } });
    expect(screen.getByText("No failed runs.")).toBeInTheDocument();
    cleanup(); mount("/exports"); expect(await screen.findByText("No completed run to export")).toBeInTheDocument();
    cleanup(); overrides["/overview"] = new Response(JSON.stringify({ error: { message: "Broken workspace" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/"); expect(await screen.findByText("Broken workspace")).toBeInTheDocument();
  });

  it("monitors and safely cancels an active run", async () => {
    const running = { ...job, status: "running" as const, finishedAt: undefined, processId: 42, progress: { ...job.progress, phase: "simulation", percent: 50, message: "Executing" } };
    overrides["/jobs/run_1"] = { job: running, events: [{ jobId: "run_1", sequence: 1, occurredAt: now, eventType: "progress", level: "info", message: "Executing", payload: {} }], artifacts: {} };
    class Source { onmessage = vi.fn(); addEventListener = vi.fn(); close = vi.fn(); constructor(public url: string) { void url; } }
    vi.stubGlobal("EventSource", Source);
    mount("/simulations/run_1");
    expect(await screen.findByText("Current backend phase")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Cancel safely/ }));
    fireEvent.click(screen.getByRole("tab", { name: "artifacts" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/jobs/run_1/cancel"), expect.anything()));
  });

  it("covers empty evidence, replay playback and digest mismatch", async () => {
    overrides["/runs/run_1/diary?limit=500"] = { total: 0, items: [] };
    overrides["/runs/run_1/replay/verify"] = { matches: false, actualSemanticDigest: "d".repeat(64) };
    mount("/simulations/run_1"); await screen.findByText("Persistent state");
    fireEvent.click(screen.getByRole("tab", { name: "diary" }));
    expect(await screen.findByText("Select an activity")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "replay" }));
    fireEvent.click(screen.getByRole("button", { name: /Play movements/ }));
    fireEvent.click(screen.getByRole("button", { name: /Verify semantic digest/ }));
    expect(await screen.findByText("Replay digest did not match")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  });

  it("covers draft, multi-resident, no-model and invalid publication paths", async () => {
    const second = { ...resident, residentId: "resident_2", sourceResidentId: "luigi", displayName: "Luigi" };
    overrides["/homes/home_1"] = { home: { ...home, currentHomeArtifactId: undefined, currentSensorArtifactId: undefined }, residents: [resident, second], models: {}, jobs: [] };
    mount("/homes/home_1");
    expect(await screen.findByText("2 associated residents")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    expect(screen.getByText("No spatial model yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "runs" }));
    expect(screen.getByText("No simulation evidence yet")).toBeInTheDocument();
    cleanup(); overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [] };
    overrides["/homes/home_1/home-model"] = { valid: false, issues: [{ message: "Geometry overlaps" }] };
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    fireEvent.click(screen.getByRole("button", { name: /Validate and publish/ }));
    expect(await screen.findByText("Geometry overlaps")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Dismiss message"));
    fireEvent.click(screen.getByText("Undo"));
  });

  it("shows invalid authoring and failed creation without partial state", async () => {
    overrides["/homes/home_1"] = { home, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1/authoring-bundle"] = { valid: false, issues: [{ code: "BEHAVIOR_MISMATCH", path: "$.personalProcessPackage", message: "Behavior mismatch" }, { code: "BEHAVIOR_MISMATCH", path: "$.personalProcessPackage", message: "Behavior mismatch" }] };
    mount("/homes/home_1"); await screen.findByText("Attach accepted authoring");
    const file = new File(["{}"], "input.json"); Object.defineProperty(file, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText(/Simulation authoring bundle/), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /Validate bundle and attach/ }));
    expect(await screen.findByText("Behavior mismatch (BEHAVIOR_MISMATCH · $.personalProcessPackage)")).toBeInTheDocument();
    cleanup(); overrides["/homes"] = new Response(JSON.stringify({ error: { message: "Name conflict" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/homes"); await screen.findByText("Name conflict");
  });

  it("covers missing provenance, observable units, absent oracle cause and run errors", async () => {
    const incomplete = { ...job, seed: undefined, startedAt: undefined, finishedAt: undefined };
    overrides["/jobs/run_1"] = { job: incomplete, events: [], artifacts: {} };
    overrides["/runs/run_1/observations?limit=500&include_oracle=false"] = { total: 1, mode: "observable", items: [{ observationId: "temp", sensorId: "temperature", sensorType: "temperature", observedAt: now, measurement: "temperature", value: 21, unit: "celsius", quality: "nominal" }] };
    overrides["/runs/run_1/observations?limit=500&include_oracle=true"] = { total: 1, mode: "oracle", items: [{ observationId: "temp", sensorId: "temperature", sensorType: "temperature", observedAt: now, measurement: "temperature", value: 21, quality: "nominal" }] };
    mount("/simulations/run_1"); await screen.findByText("Persistent state");
    fireEvent.click(screen.getByRole("tab", { name: "observations" }));
    expect(await screen.findByText("21 celsius")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Oracle links" }));
    expect(await screen.findByText("No oracle link")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "replay" }));
    expect(screen.getByText("Home artifact unavailable")).toBeInTheDocument();
    cleanup(); overrides["/jobs/run_1"] = new Response(JSON.stringify({ error: { message: "Run missing" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/simulations/run_1"); expect(await screen.findByText("Run missing")).toBeInTheDocument();
  });

  it("covers fallback labels and mutation transport failures", async () => {
    overrides["/overview"] = { ...overview, homes: [{ ...home, description: "" }], residents: [{ ...resident, homeId: "unknown", scenarioArtifactId: undefined, behaviorArtifactId: undefined }] };
    mount("/"); expect(await screen.findByText("Executable home environment")).toBeInTheDocument();
    cleanup(); mount("/residents");
    expect(await screen.findByText("Home: unknown")).toBeInTheDocument();
    expect(screen.getAllByText("Missing")).toHaveLength(2);
    cleanup(); overrides["/homes"] = (options?: RequestInit) => options?.method === "POST"
      ? response({ error: { message: "Cannot create" } }, { status: 409 })
      : response([]);
    mount("/homes"); await screen.findByText("Create an environment to begin");
    fireEvent.click(screen.getAllByRole("button", { name: /New home/ })[0]);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Conflict" } });
    fireEvent.click(screen.getByRole("button", { name: /Create home/ }));
    expect(await screen.findByText(/Conflict|Cannot create/)).toBeInTheDocument();
  });

  it("reports failed authoring, run start and model publication requests", async () => {
    overrides["/homes/home_1"] = { home, residents: [], models: {}, jobs: [] };
    overrides["/homes/home_1/authoring-bundle"] = new Response(JSON.stringify({ error: { message: "Upload failed" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/homes/home_1"); await screen.findByText("Attach accepted authoring");
    const file = new File(["{}"], "input.json"); Object.defineProperty(file, "text", { value: () => Promise.resolve("{}") });
    fireEvent.change(screen.getByLabelText(/Simulation authoring bundle/), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /Validate bundle and attach/ }));
    expect(await screen.findByText("Upload failed")).toBeInTheDocument();
    cleanup(); overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [] };
    overrides["/homes/home_1/runs"] = new Response(JSON.stringify({ error: { message: "Worker unavailable" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText("Worker unavailable")).toBeInTheDocument();
    cleanup(); overrides["/homes/home_1/home-model"] = new Response(JSON.stringify({ error: { message: "Write failed" } }), { status: 409, headers: { "Content-Type": "application/json" } });
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "Plan & resources" }));
    fireEvent.click(screen.getByRole("button", { name: /Validate and publish/ }));
    expect(await screen.findByText("Write failed")).toBeInTheDocument();
  });

  it("renders a one-window sensor and long diary duration", async () => {
    const windowed = { ...sensorModel, sensors: [{ ...sensorModel.sensors[0], failureWindows: [{ startsAt: now, endsAt: "2026-07-22T11:00:00Z" }] }] };
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel: windowed }, jobs: [] };
    mount("/homes/home_1"); await screen.findByRole("heading", { name: "Golden home" });
    fireEvent.click(screen.getByRole("tab", { name: "sensors" })); fireEvent.click(screen.getByRole("button", { name: /pir sensor pir/ }));
    expect(screen.getByRole("heading", { name: "Failure windows" })).toBeInTheDocument();
    expect(screen.getByLabelText("Starts")).toHaveValue("2026-07-22T10:00");
    cleanup();
    const longEnd = "2026-07-22T12:05:00Z";
    overrides["/runs/run_1/diary?limit=500"] = { total: 1, items: [{ activityExecutionId: "long", sourceActivityId: "source", actorId: "mario", intent: "long_activity", processModelId: "process", plannedStart: now, plannedEnd: longEnd, actualStart: now, actualEnd: longEnd, status: "completed", actions: [], movementIds: [], deviationIds: [], traceId: "trace", traceSemanticDigest: "b".repeat(64) }] };
    mount("/simulations/run_1"); await screen.findByText("Persistent state"); fireEvent.click(screen.getByRole("tab", { name: "diary" }));
    expect(await screen.findByText(/2 h 5 min/)).toBeInTheDocument();
  });

  it("generates, reviews, lists past generations and hands over to the published home", async () => {
    const progress = { phase: "completed", percent: 100, completedUnits: 2, totalUnits: 2, message: "done" };
    const genJob = { jobId: "gen_1", homeId: "home_1", kind: "generation", status: "completed", progress, requestedAt: now, finishedAt: now, resultReference: "home_1" };
    let confirmed = false;
    overrides = {
      "/generations": [genJob],
      "/generation": () => response(genJob, { status: 202 }),
      "/jobs/gen_1": { job: genJob },
      "/generation/gen_1/artifact/persona.json": { name: "Elena", age: 72, city: "Bologna" },
      "/generation/gen_1/artifact/behavioral-profile.json": { recurringActivities: [1, 2, 3, 4, 5, 6, 7, 8] },
      "/generation/gen_1/artifact/batch-manifest.json": { runs: [1, 2] },
      "/generation/gen_1/artifact/planned-activity-trace.json": { entries: [1, 2, 3] },
      // The workspace answers with the home's current state, which confirming the plan changes.
      "/homes/home_1": () => response({ home, residents: [resident], models: { homeModel, sensorModel }, jobs: [job], planApproval: { home: confirmed ? "researcher" : "recommended", sensor: confirmed ? "researcher" : "recommended", approved: confirmed } }),
      "/homes/home_1/plan-approval": () => { confirmed = true; return response({ homeId: "home_1" }); },
    };
    mount("/generate");
    await screen.findByText("No generation selected");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "an elderly woman" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    await screen.findByText("Elena");
    fireEvent.click(screen.getByText("gen_1"));
    // The generated house is shown where it was generated, labelled as what it still is.
    expect(await screen.findByText("Recommended plan")).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Plan of model_home/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Edit the plan/ })).toHaveAttribute("href", "/homes/home_1");
    fireEvent.click(screen.getByRole("button", { name: /Confirm plan/ }));
    await waitFor(() => expect(screen.getByText("Approved plan")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Open the home and run the simulation/ })).toHaveAttribute("href", "/homes/home_1");
  });

  it("publishes an earlier generation that has no home yet", async () => {
    const progress = { phase: "completed", percent: 100, completedUnits: 1, totalUnits: 1, message: "done" };
    const legacy = { jobId: "gen_old", kind: "generation", status: "completed", progress, requestedAt: now };
    const artifacts = {
      "/generations": [legacy],
      "/jobs/gen_old": { job: legacy },
      "/generation/gen_old/artifact/persona.json": { name: "Ada", age: 80, city: "Milan" },
      "/generation/gen_old/artifact/behavioral-profile.json": { recurringActivities: [1] },
      "/generation/gen_old/artifact/batch-manifest.json": { runs: [1] },
      "/generation/gen_old/artifact/planned-activity-trace.json": { entries: [1] },
    };
    overrides = { ...artifacts, "/generation/gen_old/publish": () => response({ error: { message: "artifacts are gone" } }, { status: 409 }) };
    mount("/generate");
    fireEvent.click(await screen.findByText("gen_old"));
    expect(await screen.findByText(/published no home yet/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open the home/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Publish as a home/ }));
    expect(await screen.findByText("artifacts are gone")).toBeInTheDocument();

    cleanup();
    overrides = { ...artifacts, "/generation/gen_old/publish": () => response({ homeId: "home_1" }, { status: 201 }) };
    mount("/generate");
    fireEvent.click(await screen.findByText("gen_old"));
    fireEvent.click(await screen.findByRole("button", { name: /Publish as a home/ }));
    expect(await screen.findByRole("heading", { name: "Golden home" })).toBeInTheDocument();
  });

  it("runs a generated home as one merged horizon run", async () => {
    const generation = { generationJobId: "gen_1", dayCount: 31, experimentId: "elena_horizon" };
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [], generation };
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    expect(screen.getByText(/31 days, each compiled and bundled separately/)).toBeInTheDocument();
    expect(screen.getByText(/single trace, one observable sensor log/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText(/queued in an isolated/)).toBeInTheDocument();
  });

  it("surfaces a generation start error", async () => {
    overrides = {
      "/generations": [],
      "/generation": () => response({ error: { message: "LM Studio down" } }, { status: 502 }),
    };
    mount("/generate");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(await screen.findByText(/LM Studio down/)).toBeInTheDocument();
  });

  it("shows a failed generation job", async () => {
    const failed = { jobId: "gen_x", kind: "generation", status: "failed", progress: { phase: "failed", percent: 40, completedUnits: 0, message: "phase failed" }, errorMessage: "LM Studio timeout", requestedAt: now };
    overrides = {
      "/generations": [],
      "/generation": () => response(failed, { status: 202 }),
      "/jobs/gen_x": { job: failed },
    };
    mount("/generate");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(await screen.findByText("LM Studio timeout")).toBeInTheDocument();
  });

  it("streams live generation progress", async () => {
    const running = { jobId: "gen_r", kind: "generation", status: "running", progress: { phase: "authoring_habits", percent: 30, completedUnits: 2, totalUnits: 7, message: "Authoring habits" }, requestedAt: now };
    overrides = {
      "/generations": [],
      "/generation": () => response(running, { status: 202 }),
      "/jobs/gen_r": { job: running },
    };
    mount("/generate");
    fireEvent.change(screen.getByLabelText("Person and case brief"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(await screen.findByText("authoring habits")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generating/ })).toBeDisabled();
  });

  it("shows the live horizon run of a generated home", async () => {
    const generation = { generationJobId: "gen_1", dayCount: 2 };
    const running = { ...job, jobId: "run_h", status: "running" as const, finishedAt: undefined, progress: { phase: "simulating", percent: 50, completedUnits: 1, totalUnits: 2, message: "Day 1 of 2 · 640 observations" } };
    overrides["/homes/home_1"] = { home, residents: [resident], models: { homeModel, sensorModel }, jobs: [running], generation };
    class Source { onmessage = vi.fn(); addEventListener = vi.fn(); close = vi.fn(); constructor(public url: string) { void url; } }
    vi.stubGlobal("EventSource", Source);
    mount("/homes/home_1");
    await screen.findByRole("heading", { name: "Golden home" });
    expect(screen.getByText(/Day 1 of 2 · 640 observations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run simulation" })).toBeDisabled();
  });
});
