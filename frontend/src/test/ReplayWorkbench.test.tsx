import { cleanup, render, screen } from "@testing-library/react";
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
    { at: "2026-01-01T08:10:00Z", regionId: "market", traversalMode: "walk", position: { x: 2, y: 10 } },
  ], details: {} }],
};

describe("ReplayStage", () => {
  afterEach(cleanup);

  it("keeps every resident in the structured alternative and expands external places only for a visible leaving trajectory", () => {
    const view = render(<ReplayStage controller={{ frame, events, selectedEventId: "leave-home", filters: { selectedResidentId: "mario" } }} models={{ homeModel: home, sensorModel: sensors }} />);

    expect(screen.getByRole("list", { name: "Replay resident states" })).toHaveTextContent("Mario");
    expect(screen.getByRole("list", { name: "Replay resident states" })).toHaveTextContent("Luisa: Position unknown");
    expect(view.container.querySelector('[aria-label="external market"]')).toBeInTheDocument();

    view.rerender(<ReplayStage controller={{ frame, events, filters: { selectedResidentId: "mario" } }} models={{ homeModel: home, sensorModel: sensors }} />);
    expect(view.container.querySelector('[aria-label="external market"]')).not.toBeInTheDocument();
  });
});
