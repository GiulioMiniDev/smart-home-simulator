import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Profiler } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReplayStage } from "../replay/ReplayStage";
import { ReplayTimeline } from "../replay/ReplayTimeline";
import { ReplayWorkbench } from "../replay/ReplayWorkbench";
import type { ReplayController } from "../replay/useReplayController";
import type { HomeModel, ReplayEventWindow, ReplayFrame, SensorModel } from "../types";

const home: HomeModel = {
  schemaVersion: "1.0.0", documentType: "home_model", homeId: "home", homeVersion: "1", coordinateSystem: {},
  regions: [
    { regionId: "kitchen", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } },
    { regionId: "market", kind: "external", traversable: true, boundary: { vertices: [{ x: 0, y: 8 }, { x: 4, y: 8 }, { x: 4, y: 12 }, { x: 0, y: 12 }] } },
  ],
  connections: [{ connectionId: "to-market", regionAId: "kitchen", regionBId: "market", kind: "transit", bidirectional: true, widthMeters: 1 }],
  obstacles: [], interactionPoints: [], entities: [], locationBindings: [], resourceBindings: [], kinematicDefaults: {},
};

const sensors: SensorModel = {
  schemaVersion: "1.0.0", documentType: "sensor_model", sensorModelId: "s", sensorModelVersion: "1", sourceBundleId: "b", sourceBundleSha256: "a".repeat(64), seed: 1,
  regionIds: ["kitchen"], entityIds: [], sensors: [{ sensorId: "pir", sensorType: "pir", position: { x: 2, y: 2 }, timing: { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 }, errorModel: { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 }, failureWindows: [] }],
};

const frame: ReplayFrame = {
  runId: "run", at: "2026-01-01T08:00:00Z", traceStart: "2026-01-01T08:00:00Z", traceEnd: "2026-01-01T09:00:00Z",
  residents: [
    { residentId: "mario", regionId: "kitchen", position: { x: 2, y: 2 }, executionState: "moving", heldResourceIds: [], facts: {} },
    { residentId: "luisa", regionId: null, position: null, executionState: "idle", heldResourceIds: [], facts: {} },
  ],
  sensorStates: [{ observationId: "observation", sensorId: "pir", sensorType: "pir", observedAt: "2026-01-01T08:00:00Z", measurement: "motion", value: true, quality: "nominal", changed: true }],
  entityStates: {}, environmentFacts: {}, resourceAvailableUnits: {},
};

const events: ReplayEventWindow = {
  total: 1, traceStart: frame.traceStart, traceEnd: frame.traceEnd, windowStart: frame.traceStart, windowEnd: frame.traceEnd,
  items: [{ at: frame.at, kind: "movement", eventId: "leave-home", label: "walk", status: "completed", actorId: "mario", waypoints: [
    { at: frame.at, regionId: "kitchen", traversalMode: "walk", position: { x: 2, y: 2 } },
    { at: "2026-01-01T08:10:00Z", regionId: "market", traversalMode: "walk", position: { x: 2.125, y: 10.5 } },
  ], details: {} }],
};

describe("ReplayStage", () => {
  afterEach(cleanup);

  const reducedMotion = () => vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)", media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })));

  it("snaps a uniquely identified midpoint movement to its previous authoritative waypoint for reduced motion", () => {
    reducedMotion();
    const midpoint = { ...frame, at: "2026-01-01T08:05:00Z", residents: [{ ...frame.residents[0]!, position: { x: 2.0625, y: 6.25 } }] };
    render(<ReplayStage controller={{ frame: midpoint, events, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    const marker = screen.getByLabelText("Mario in kitchen, moving");
    expect(marker).toHaveAttribute("transform", "translate(2 2)");
    expect(marker).toHaveAttribute("data-motion", "step");
  });

  it("does not manufacture a reduced-motion marker when an actor-associated resident has no frame position", () => {
    reducedMotion();
    const missingPosition = { ...frame, at: "2026-01-01T08:05:00Z", residents: [{ ...frame.residents[0]!, position: null, regionId: null }] };
    render(<ReplayStage controller={{ frame: missingPosition, events, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    expect(screen.queryByLabelText("Mario in kitchen, moving")).not.toBeInTheDocument();
    expect(screen.getByText("Mario: Position unknown; moving.")).toBeInTheDocument();
  });

  it("uses the last duplicate waypoint at an exact reduced-motion timestamp", () => {
    reducedMotion();
    const duplicate = { ...events, items: [{ ...events.items[0]!, waypoints: [
      { at: frame.at, regionId: "kitchen", traversalMode: "walk", position: { x: 1, y: 1 } },
      { at: frame.at, regionId: "kitchen", traversalMode: "walk", position: { x: 3, y: 3 } },
      { at: "2026-01-01T08:10:00Z", regionId: "market", traversalMode: "walk", position: { x: 4, y: 4 } },
    ] }] };
    const exact = { ...frame, residents: [{ ...frame.residents[0]!, position: { x: 3, y: 3 } }] };
    render(<ReplayStage controller={{ frame: exact, events: duplicate, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    expect(screen.getByLabelText("Mario in kitchen, moving")).toHaveAttribute("transform", "translate(3 3)");
  });

  it("does not snap an Observable resident when multiple active movements match its midpoint", () => {
    reducedMotion();
    const midpoint = { ...frame, at: "2026-01-01T08:05:00Z", residents: [{ ...frame.residents[0]!, position: { x: 2.0625, y: 6.25 } }] };
    const ambiguous = { ...events, items: [events.items[0]!, { ...events.items[0]!, eventId: "other-movement", actorId: "luisa" }] };
    render(<ReplayStage controller={{ frame: midpoint, events: ambiguous, selectedEventId: "leave-home", filters: { visibilityMode: "observable" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    const marker = screen.getByLabelText("Resident 1 in kitchen, moving");
    expect(marker).toHaveAttribute("transform", "translate(2.0625 6.25)");
    expect(marker).toHaveAttribute("data-motion", "none");
  });

  it("keeps the authoritative interpolated frame position when normal motion is enabled", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const midpoint = { ...frame, at: "2026-01-01T08:05:00Z", residents: [{ ...frame.residents[0]!, position: { x: 2.0625, y: 6.25 } }] };
    render(<ReplayStage controller={{ frame: midpoint, events, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    const marker = screen.getByLabelText("Mario in kitchen, moving");
    expect(marker).toHaveAttribute("transform", "translate(2.0625 6.25)");
    expect(marker).toHaveAttribute("data-motion", "interpolate");
  });

  it("keeps every resident in the structured alternative and expands external places only for a visible leaving trajectory", () => {
    const view = render(<ReplayStage controller={{ frame, events, selectedEventId: "leave-home", filters: { selectedResidentId: "mario", visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);

    const alternative = screen.getByRole("region", { name: "Replay spatial state" });
    expect(within(alternative).getByText("Mario: Position 2, 2 in kitchen; moving.")).toBeInTheDocument();
    expect(within(alternative).getByText("Luisa: Position unknown; idle.")).toBeInTheDocument();
    expect(view.container.querySelector('[aria-label="external market"]')).toBeInTheDocument();

    view.rerender(<ReplayStage controller={{ frame, events, filters: { selectedResidentId: "mario", visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(view.container.querySelector('[aria-label="external market"]')).not.toBeInTheDocument();
  });

  it("shows a selected movement route only within its authoritative interval", () => {
    const view = render(<ReplayStage controller={{ frame, events, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.getByLabelText("Active trajectory")).toBeInTheDocument();
    expect(view.container.querySelector('[aria-label="external market"]')).toBeInTheDocument();

    view.rerender(<ReplayStage controller={{ frame: { ...frame, at: "2026-01-01T07:59:59Z" }, events, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.queryByLabelText("Active trajectory")).not.toBeInTheDocument();
    expect(view.container.querySelector('[aria-label="external market"]')).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Replay spatial state" })).getByText("No active trajectory.")).toBeInTheDocument();
    expect(view.container.querySelector("[data-region-id='kitchen']")).toHaveClass("is-replay-active");
    expect(screen.getByLabelText("pir sensor pir")).toHaveClass("is-replay-active");

    view.rerender(<ReplayStage controller={{ frame: { ...frame, at: "2026-01-01T08:10:00Z" }, events: { ...events, items: [{ ...events.items[0]!, end: "2026-01-01T08:10:00Z" }] }, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.getByLabelText("Active trajectory")).toBeInTheDocument();

    view.rerender(<ReplayStage controller={{ frame: { ...frame, at: "2026-01-01T08:10:01Z" }, events: { ...events, items: [{ ...events.items[0]!, end: "2026-01-01T08:10:00Z" }] }, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.queryByLabelText("Active trajectory")).not.toBeInTheDocument();
    expect(view.container.querySelector('[aria-label="external market"]')).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Replay spatial state" })).getByText("No active trajectory.")).toBeInTheDocument();
    expect(view.container.querySelector("[data-region-id='kitchen']")).toHaveClass("is-replay-active");
    expect(screen.getByLabelText("pir sensor pir")).toHaveClass("is-replay-active");
  });

  it("uses the final waypoint as the end only when no event end is supplied and rejects unusable routes", () => {
    const fallback = { ...events, items: [{ ...events.items[0]!, end: null }] };
    const view = render(<ReplayStage controller={{ frame: { ...frame, at: "2026-01-01T08:10:00Z" }, events: fallback, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.getByLabelText("Active trajectory")).toBeInTheDocument();

    view.rerender(<ReplayStage controller={{ frame, events: { ...events, items: [{ ...events.items[0]!, end: null, waypoints: [] }] }, selectedEventId: "leave-home", filters: { visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(screen.queryByLabelText("Active trajectory")).not.toBeInTheDocument();
    expect(view.container.querySelector('[aria-label="external market"]')).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Replay spatial state" })).getByText("No active trajectory.")).toBeInTheDocument();
  });

  it("provides equivalent, safe structured replay evidence including empty states", () => {
    const { rerender } = render(<ReplayStage controller={{ frame, events, selectedEventId: "leave-home", filters: { visibilityMode: "observable" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    const alternative = screen.getByRole("region", { name: "Replay spatial state" });
    expect(within(alternative).getByRole("heading", { name: "Residents" })).toBeInTheDocument();
    expect(within(alternative).getByText("Resident 1: Identity unavailable; Position unknown; idle.")).toBeInTheDocument();
    expect(within(alternative).getByText("Resident 2: Identity unavailable; Position 2, 2 in kitchen; moving.")).toBeInTheDocument();
    expect(within(alternative).getByRole("heading", { name: "Active regions" }).nextElementSibling).toHaveTextContent("kitchen");
    expect(within(alternative).getByRole("heading", { name: "Changed sensors" }).nextElementSibling).toHaveTextContent("pir");
    const trajectory = within(alternative).getByRole("heading", { name: "Trajectory" }).parentElement!;
    expect(within(trajectory).getByRole("list", { name: "Active trajectory waypoints" })).toHaveTextContent("Step 1: kitchen; coordinates 2, 2; walk; 2026-01-01T08:00:00Z.");
    expect(within(trajectory).getByRole("list", { name: "Active trajectory waypoints" })).toHaveTextContent("Step 2: market; coordinates 2.125, 10.5; walk; 2026-01-01T08:10:00Z.");
    const selectedEvent = within(alternative).getByRole("heading", { name: "Selected event" }).parentElement!;
    expect(within(selectedEvent).getByText("walk")).toBeInTheDocument();
    expect(within(selectedEvent).getByText("movement")).toBeInTheDocument();
    expect(within(selectedEvent).getByText("completed")).toBeInTheDocument();
    expect(within(selectedEvent).getByText("2026-01-01T08:00:00Z")).toBeInTheDocument();
    expect(within(alternative).queryByText("Mario")).not.toBeInTheDocument();

    rerender(<ReplayStage controller={{ filters: { visibilityMode: "observable" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(within(screen.getByRole("region", { name: "Replay spatial state" })).getByText("No residents in the replay frame.")).toBeInTheDocument();
    expect(screen.getByText("No active regions.")).toBeInTheDocument();
    expect(screen.getByText("No changed sensors.")).toBeInTheDocument();
    expect(screen.getByText("No active trajectory.")).toBeInTheDocument();
    expect(screen.getByText("No event selected.")).toBeInTheDocument();
  });
});

const digest = "a".repeat(64);
const replayStart = "2026-01-01T08:00:00.000Z";
const replayEnd = "2026-01-01T09:00:00.000Z";
const simultaneousEvents = [
  { at: "2026-01-01T08:15:00.000Z", kind: "observation", eventId: "sensor-1", label: "motion detected", status: "completed", sensorId: "pir", waypoints: [], details: { measurement: "motion" } },
  { at: "2026-01-01T08:15:00.000Z", kind: "observation", eventId: "sensor-2", label: "door opened", status: "pending", sensorId: "contact", waypoints: [], details: { measurement: "contact" } },
];

function replayResponse(path: string): unknown {
  if (path.includes("/verify")) return { runId: "run_1", matches: true, expectedSemanticDigest: digest, actualSemanticDigest: digest, verifiedAt: replayStart };
  if (path.includes("/session")) return { runId: "run_1", verifiedDigest: digest, playable: true, positionAt: replayStart, filters: { eventKinds: [], actorIds: [], sensorIds: [], statuses: [], detailMode: "presentation", visibilityMode: "observable", speed: 1 } };
  if (path.includes("/models")) return { homeModel: home, sensorModel: sensors, oracleMapping: { artifactId: "oracle-mapping" } };
  if (path.includes("/events")) {
    const items = path.includes("include_oracle=true")
      ? simultaneousEvents.map((event) => ({ ...event, eventId: `oracle-${event.eventId}`, actorId: "mario" }))
      : simultaneousEvents;
    return { items, total: items.length, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd };
  }
  if (path.includes("/frame")) return { ...frame, runId: "run_1", at: replayStart, traceStart: replayStart, traceEnd: replayEnd };
  return {};
}

describe("ReplayWorkbench", () => {
  let response = replayResponse;
  beforeEach(() => {
    response = replayResponse;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(new Response(JSON.stringify(response(String(input))), { status: 200, headers: { "Content-Type": "application/json" } }))));
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("does not pair an observation with an unrelated frame resident and labels unavailable activity", async () => {
    response = (path) => path.includes("/models")
      ? { homeModel: home, sensorModel: { ...sensors, sensors: [{ ...sensors.sensors[0]!, regionId: "kitchen" }] }, oracleMapping: { artifactId: "oracle-mapping" } }
      : replayResponse(path);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));

    expect(screen.getByText("observation · 08:15")).toBeInTheDocument();
    expect(screen.getByText("Resident unavailable · kitchen")).toBeInTheDocument();
    expect(screen.getByText("Activity unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Resident 1 · kitchen · 08:00")).not.toBeInTheDocument();
  });

  it("keeps resident and region unavailable when the selected observation has no matching frame resident", async () => {
    response = (path) => path.includes("/frame")
      ? { ...frame, runId: "run_1", at: replayStart, traceStart: replayStart, traceEnd: replayEnd, residents: [] }
      : replayResponse(path);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));

    expect(screen.getByText("Resident unavailable · Region unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Resident 1")).not.toBeInTheDocument();
  });

  it("summarizes simulated date and an authoritative active activity separately", async () => {
    const activity = { at: replayStart, end: replayEnd, kind: "activity", eventId: "breakfast", label: "Breakfast", status: "active", waypoints: [], details: {} };
    response = (path) => path.includes("/events")
      ? { items: [activity, ...simultaneousEvents], total: 3, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd }
      : replayResponse(path);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");

    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Simulated date 2026-01-01"));
    const summary = screen.getByLabelText("Current replay state");
    expect(summary).toHaveTextContent("Current time 08:00");
    expect(summary).toHaveTextContent("Current activity Breakfast");
  });

  it("shows a selected activity only within its inclusive authoritative interval", async () => {
    const activity = { at: "2026-01-01T08:15:00.000Z", end: "2026-01-01T08:20:00.000Z", kind: "activity", eventId: "breakfast", label: "Breakfast", status: "active", waypoints: [], details: {} };
    response = (path) => {
      if (path.includes("/events")) return { items: [activity], total: 1, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd };
      if (path.includes("/frame")) {
        const at = new URL(path, "https://example.test").searchParams.get("at") ?? replayStart;
        return { ...frame, runId: "run_1", at, traceStart: replayStart, traceEnd: replayEnd };
      }
      return replayResponse(path);
    };
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    const slider = screen.getByRole("slider", { name: "Replay time" });
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));
    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Current activity Breakfast"));

    fireEvent.change(slider, { target: { value: Date.parse("2026-01-01T08:14:59.000Z") } });
    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Current activity Activity unavailable"));

    fireEvent.change(slider, { target: { value: Date.parse("2026-01-01T08:15:00.000Z") } });
    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Current activity Breakfast"));

    fireEvent.change(slider, { target: { value: Date.parse("2026-01-01T08:20:00.000Z") } });
    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Current activity Breakfast"));

    fireEvent.change(slider, { target: { value: Date.parse("2026-01-01T08:20:01.000Z") } });
    await waitFor(() => expect(screen.getByLabelText("Current replay state")).toHaveTextContent("Current activity Activity unavailable"));
  });

  it("keeps the same instant when analysis mode and oracle evidence are opened", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    const before = screen.getByRole("slider", { name: "Replay time" }).getAttribute("value");
    fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
    fireEvent.click(screen.getByRole("button", { name: "Oracle" }));
    expect(await screen.findByText("Simulated cause")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
  });

  it("presents authoritative evidence first and opens analysis at the identical instant", async () => {
    const view = render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));

    expect(screen.getByRole("heading", { name: "motion detected" })).toBeInTheDocument();
    expect(screen.getByText("Resident unavailable · Region unavailable")).toBeInTheDocument();
    expect(screen.getByText("Current evidence")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Event timeline" })).not.toBeInTheDocument();
    expect(view.container.querySelector(".replay-presentation-stage")).toBeInTheDocument();
    const before = screen.getByRole("slider", { name: "Replay time" }).getAttribute("value");

    fireEvent.click(screen.getByRole("button", { name: "Open evidence" }));

    expect(screen.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
    expect(screen.getByRole("heading", { name: "Event timeline" })).toBeInTheDocument();
  });

  it("steps presentation markers and suppresses sensor pulses for reduced motion", () => {
    const matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)", media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", matchMedia);

    const view = render(<ReplayStage controller={{ frame, events, selectedEventId: "leave-home", filters: { selectedResidentId: "mario", visibilityMode: "oracle" } }} models={{ homeModel: home, sensorModel: sensors }} presentation />);

    expect(screen.getByLabelText("Mario in kitchen, moving")).toHaveAttribute("data-motion", "step");
    expect(screen.getByLabelText("pir sensor pir")).toHaveAttribute("data-pulse", "off");
    expect(view.container.querySelector("[data-resident-index='1']")?.textContent).toContain("Mario");
  });

  it("steps events, filters tracks and exposes simultaneous events individually", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));
    const cluster = screen.getByRole("button", { name: "2 clustered events" });
    expect(cluster).toHaveAttribute("aria-expanded", "false");
    fireEvent.keyDown(cluster, { key: "Enter" });
    expect(cluster).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("button", { name: /08:15/ })).toHaveLength(2);
  });

  it("derives restored track checks from controller filters and composes additions", async () => {
    response = (path) => path.includes("/session") ? {
      runId: "run_1", verifiedDigest: digest, playable: true, positionAt: replayStart,
      filters: { eventKinds: ["movement"], actorIds: [], sensorIds: ["pir"], statuses: ["completed"], detailMode: "analysis", visibilityMode: "observable", speed: 1 },
    } : replayResponse(path);
    const fetchMock = vi.mocked(fetch);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByRole("heading", { name: "Inspector" });
    const movements = screen.getByRole("checkbox", { name: "Movements" });
    const sensors = screen.getByRole("checkbox", { name: "Sensors" });
    expect(movements).toBeChecked();
    expect(sensors).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Sensor" })).toHaveValue("pir");
    expect(screen.getByRole("combobox", { name: "Event status" })).toHaveValue("completed");
    const eventRequests = () => fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/replay/events?") && path.includes("limit=5000"));
    const beforeAddition = eventRequests().length;
    fireEvent.click(sensors);
    expect(movements).toBeChecked();
    expect(sensors).toBeChecked();
    await waitFor(() => expect(eventRequests().length).toBeGreaterThan(beforeAddition));
    expect(eventRequests().at(-1)).toContain("kinds=movement%2Cobservation");
    fireEvent.click(sensors);
    expect(movements).toBeChecked();
    expect(sensors).not.toBeChecked();
  });

  it("treats an empty controller kind filter as all tracks and returns to that canonical form", async () => {
    const fetchMock = vi.mocked(fetch);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    const sensors = screen.getByRole("checkbox", { name: "Sensors" });
    expect(screen.getAllByRole("checkbox").every((checkbox) => (checkbox as HTMLInputElement).checked)).toBe(true);
    const eventRequests = () => fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/replay/events?") && path.includes("limit=5000"));
    const beforeExclusion = eventRequests().length;
    fireEvent.click(sensors);
    expect(sensors).not.toBeChecked();
    await waitFor(() => expect(eventRequests().length).toBeGreaterThan(beforeExclusion));
    const beforeRestore = eventRequests().length;
    fireEvent.click(sensors);
    expect(screen.getAllByRole("checkbox").every((checkbox) => (checkbox as HTMLInputElement).checked)).toBe(true);
    await waitFor(() => expect(eventRequests().length).toBeGreaterThan(beforeRestore));
    expect(eventRequests().at(-1)).not.toContain("kinds=");
  });

  it("steps previous and next events from the keyboard", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    await screen.findByText("Replay verified");
    const next = screen.getByRole("button", { name: "Next event" });
    const previous = screen.getByRole("button", { name: "Previous event" });
    fireEvent.keyDown(next, { key: "Enter" });
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", String(Date.parse(simultaneousEvents[0]!.at)));
    fireEvent.keyDown(previous, { key: "Enter" });
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", String(Date.parse(simultaneousEvents[0]!.at)));
  });

  it("shows complete, labelled semantic digests when verification blocks replay", async () => {
    const actual = "b".repeat(64);
    response = (path) => path.includes("/verify")
      ? { runId: "run_1", matches: false, expectedSemanticDigest: digest, actualSemanticDigest: actual, verifiedAt: replayStart }
      : replayResponse(path);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    expect(await screen.findByText("Replay digest did not match")).toBeInTheDocument();
    expect(screen.getByText("Expected semantic digest").nextElementSibling).toHaveTextContent(digest);
    expect(screen.getByText("Actual semantic digest").nextElementSibling).toHaveTextContent(actual);
    expect(screen.getByRole("button", { name: "Next event" })).toBeDisabled();
  });

  it("does not offer Oracle evidence without an authoritative mapping artifact", async () => {
    response = (path) => path.includes("/models") ? { homeModel: home, sensorModel: sensors } : replayResponse(path);
    const fetchMock = vi.mocked(fetch);
    render(<ReplayWorkbench runId="run_1" />);
    await screen.findByText("Replay verified");
    const oracle = screen.getByRole("button", { name: "Oracle" });
    expect(oracle).toBeDisabled();
    expect(screen.getByText(/Oracle mapping unavailable/)).toBeInTheDocument();
    fireEvent.click(oracle);
    expect(fetchMock.mock.calls.some(([input]) => {
      const path = String(input);
      return (path.includes("/replay/events") || path.includes("/replay/frame")) && path.includes("include_oracle=true");
    })).toBe(false);
  });

  it("blocks transport when the authoritative replay window cannot be loaded", async () => {
    response = (path) => path.includes("events?limit=1")
      ? { error: "Replay range unavailable" }
      : replayResponse(path);
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      const status = path.includes("events?limit=1") ? 500 : 200;
      return Promise.resolve(new Response(JSON.stringify(response(path)), { status, headers: { "Content-Type": "application/json" } }));
    }));
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    expect(await screen.findByText(/Replay window unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous event" })).toBeDisabled();
    expect(screen.queryByText("Replay verified")).not.toBeInTheDocument();
  });

  it("keeps the selected semantic event across projections without painting Oracle evidence on downgrade", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    const cluster = screen.getByRole("button", { name: "2 clustered events" });
    fireEvent.click(cluster);
    fireEvent.click(screen.getByRole("button", { name: "08:15 motion detected" }));
    expect(screen.getByText("sensor-1")).toBeInTheDocument();
    const before = screen.getByRole("slider", { name: "Replay time" }).getAttribute("value");
    fireEvent.click(screen.getByRole("button", { name: "Oracle" }));
    expect(await screen.findByText("oracle-sensor-1")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
    fireEvent.click(screen.getByRole("button", { name: "Observable" }));
    expect(screen.queryByText("oracle-sensor-1")).not.toBeInTheDocument();
    expect(await screen.findByText("sensor-1")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
  });

  it("preserves the server-order occurrence of simultaneous evidence when projections use different labels", async () => {
    response = (path) => {
      if (path.includes("/events")) {
        const items = ["first", "second"].map((eventId, index) => ({
          at: "2026-01-01T08:15:00.000Z", kind: "observation" as const, eventId: path.includes("include_oracle=true") ? `oracle-${eventId}` : eventId,
          label: path.includes("include_oracle=true") ? `Mario ${index === 0 ? "opens" : "closes"} door` : "Observation event",
          sensorId: "contact", status: "completed", waypoints: [], details: {},
        }));
        return { items, total: items.length, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd };
      }
      return replayResponse(path);
    };
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "2 clustered events" }));
    fireEvent.click(screen.getAllByRole("button", { name: "08:15 Observation event" })[1]!);
    fireEvent.click(screen.getByRole("button", { name: "Oracle" }));
    expect(await screen.findByText("oracle-second")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Observable" }));
    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(screen.queryByText("oracle-second")).not.toBeInTheDocument();
  });

  it("clears an inspector selection as soon as its track filter hides it", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "2 clustered events" }));
    fireEvent.click(screen.getByRole("button", { name: "08:15 motion detected" }));
    expect(screen.getAllByText("motion detected")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: "Sensors" }));
    expect(screen.getByText("Select an event to inspect its source evidence.")).toBeInTheDocument();
  });

  it("reports an empty evidence window without manufacturing an event to step to", async () => {
    response = (path) => path.includes("/events")
      ? { items: [], total: 0, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd }
      : replayResponse(path);
    render(<ReplayWorkbench runId="run_1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    expect(await screen.findByText("No sensors in this window.")).toBeInTheDocument();
  });

  it("composes compact evidence filters, and keeps resident identity unavailable in Observable mode", async () => {
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    const resident = screen.getByRole("combobox", { name: "Resident" });
    const sensor = screen.getByRole("combobox", { name: "Sensor" });
    expect(resident).toBeDisabled();
    expect(screen.getByText(/Resident filtering is available only in Oracle/)).toBeInTheDocument();
    fireEvent.change(sensor, { target: { value: "pir" } });
    await waitFor(() => expect(sensor).toHaveValue("pir"));
    fireEvent.change(screen.getByRole("combobox", { name: "Event status" }), { target: { value: "completed" } });
    expect(screen.getByRole("combobox", { name: "Event status" })).toHaveValue("completed");
    expect(within(screen.getByRole("combobox", { name: "Event status" })).getByRole("option", { name: "pending" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Oracle" }));
    await waitFor(() => expect(resident).toBeEnabled());
    fireEvent.change(resident, { target: { value: "mario" } });
    await waitFor(() => expect(resident).toHaveValue("mario"));
    fireEvent.click(screen.getByRole("button", { name: "Observable" }));
    expect(resident).toBeDisabled();
    expect(resident).toHaveValue("");
  });

  it("requests the selected temporal zoom and does not claim a truncated dense window is complete", async () => {
    let denseRequests = 0;
    let dense = false;
    response = (path) => {
      if (dense && path.includes("/events?") && !path.includes("limit=1")) {
        denseRequests += 1;
        return { items: simultaneousEvents, total: 5_001, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd };
      }
      return replayResponse(path);
    };
    const fetchMock = vi.mocked(fetch);
    render(<ReplayWorkbench runId="run_1" oracleAvailable />);
    fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
    dense = true;
    fireEvent.change(screen.getByRole("combobox", { name: "Temporal zoom" }), { target: { value: String(5 * 60 * 1000) } });
    await waitFor(() => expect(denseRequests).toBeGreaterThan(1));
    expect((await screen.findAllByText(/Evidence window is incomplete/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/narrow the evidence filters/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Next event" })).toBeDisabled();
    const requests = fetchMock.mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/replay/events?") && path.includes("limit=5000"));
    expect(requests.at(-1)).toContain("limit=5000");
  });
});

describe("ReplayTimeline lane measurements", () => {
  let width = 640;
  let observers: Array<{ callback: ResizeObserverCallback; disconnect: ReturnType<typeof vi.fn> }> = [];

  beforeEach(() => {
    observers = [];
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({
      width, height: 20, x: 0, y: 0, top: 0, right: width, bottom: 20, left: 0, toJSON: () => ({}),
    } as DOMRect));
    vi.stubGlobal("ResizeObserver", class {
      callback: ResizeObserverCallback;
      disconnect = vi.fn();
      constructor(callback: ResizeObserverCallback) { this.callback = callback; observers.push(this); }
      observe(): void {}
      unobserve(): void {}
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  const controller = {
    status: "ready", positionMs: Date.parse(replayStart), traceStartMs: Date.parse(replayStart), traceEndMs: Date.parse(replayEnd),
    playing: false, filters: { eventKinds: [], actorIds: [], sensorIds: [], statuses: [], detailMode: "analysis", visibilityMode: "observable", speed: 1 },
    events: { ...events, items: simultaneousEvents, total: simultaneousEvents.length, traceStart: replayStart, traceEnd: replayEnd, windowStart: replayStart, windowEnd: replayEnd },
    windowSpanMs: 15 * 60 * 1000, evidenceIncomplete: false, evidenceLoading: false,
    filterOptions: { sensorIds: [], actorIds: [], statuses: [] },
    play: vi.fn(), pause: vi.fn(), seek: vi.fn(), step: vi.fn(), selectEvent: vi.fn(), updateFilters: vi.fn(), setWindowSpan: vi.fn(),
  } as unknown as ReplayController;

  it("does not re-render indefinitely when lane refs attach", () => {
    expect(() => render(<ReplayTimeline controller={controller} />)).not.toThrow();
    expect(observers).toHaveLength(8);
  });

  it("recomputes a lane after a resize but ignores the same finite width", () => {
    const commits: number[] = [];
    const { unmount } = render(<Profiler id="timeline" onRender={() => commits.push(1)}><ReplayTimeline controller={controller} /></Profiler>);
    const initialObservers = [...observers];
    act(() => initialObservers.forEach((observer) => observer.callback([], observer as unknown as ResizeObserver)));
    const afterInitialMeasurement = commits.length;

    width = 480;
    act(() => initialObservers.forEach((observer) => observer.callback([], observer as unknown as ResizeObserver)));
    const afterResize = commits.length;

    act(() => initialObservers.forEach((observer) => observer.callback([], observer as unknown as ResizeObserver)));
    expect(afterResize).toBeGreaterThan(afterInitialMeasurement);
    expect(commits).toHaveLength(afterResize);
    unmount();
    expect(initialObservers.every((observer) => observer.disconnect.mock.calls.length > 0)).toBe(true);
  });

  it("disables evidence filters and zoom only for a fatally blocked replay", () => {
    const view = render(<ReplayTimeline controller={{ ...controller, status: "blocked" }} />);
    expect(within(view.container).getByRole("checkbox", { name: "Movements" })).toBeDisabled();
    expect(within(view.container).getByLabelText("Sensor")).toBeDisabled();
    expect(within(view.container).getByLabelText("Event status")).toBeDisabled();
    expect(within(view.container).getByLabelText("Temporal zoom")).toBeDisabled();
    expect(within(view.container).getByRole("button", { name: "Clear filters" })).toBeDisabled();
  });

  it("keeps evidence filters and zoom available while dense evidence recovers", () => {
    const view = render(<ReplayTimeline controller={{ ...controller, evidenceIncomplete: true, evidenceLoading: true }} />);
    expect(within(view.container).getByRole("checkbox", { name: "Movements" })).toBeEnabled();
    expect(within(view.container).getByLabelText("Sensor")).toBeEnabled();
    expect(within(view.container).getByLabelText("Event status")).toBeEnabled();
    expect(within(view.container).getByLabelText("Temporal zoom")).toBeEnabled();
    expect(within(view.container).getByRole("button", { name: "Clear filters" })).toBeEnabled();
  });
});
