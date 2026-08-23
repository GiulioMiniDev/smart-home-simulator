import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ReplayStage } from "../replay/ReplayStage";
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
