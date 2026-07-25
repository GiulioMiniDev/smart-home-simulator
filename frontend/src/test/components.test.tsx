import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Breadcrumbs, EmptyState, ErrorPanel, Metric, PageHeader, PlanCanvas, ProgressBar, RunLink, Shell, Skeleton, StatusBadge } from "../components";
import type { HomeModel, SensorModel } from "../types";

const home: HomeModel = {
  schemaVersion: "1.0.0", documentType: "home_model", homeId: "home", homeVersion: "1", coordinateSystem: {},
  regions: [{ regionId: "kitchen", kind: "room", traversable: true, boundary: { vertices: [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 4 }, { x: 0, y: 4 }] } }],
  connections: [], obstacles: [{ obstacleId: "table", regionId: "kitchen", boundary: { vertices: [{ x: 1, y: 1 }, { x: 2, y: 1 }, { x: 2, y: 2 }] } }],
  interactionPoints: [{ interactionPointId: "point", regionId: "kitchen", position: { x: 3, y: 3 }, approachRadiusMeters: 1 }],
  entities: [{ entityId: "oven", entityType: "oven", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} }],
  locationBindings: [], resourceBindings: [], kinematicDefaults: {},
};
const sensors: SensorModel = { schemaVersion: "1.0.0", documentType: "sensor_model", sensorModelId: "s", sensorModelVersion: "1", sourceBundleId: "b", sourceBundleSha256: "a".repeat(64), seed: 1, regionIds: ["kitchen"], entityIds: ["oven"], sensors: [{ sensorId: "pir", sensorType: "pir", position: { x: 2, y: 2 }, timing: { latencyMilliseconds: 0, clockJitterMilliseconds: 0, cooldownMilliseconds: 0 }, errorModel: { dropoutProbability: 0, falseNegativeProbability: 0, falsePositiveProbabilityPerDay: 0, measurementNoiseStandardDeviation: 0 }, failureWindows: [], coverage: home.regions[0].boundary }] };

describe("application components", () => {
  it("renders the shell and controls navigation and theme", () => {
    const theme = vi.fn(); const nav = vi.fn();
    const view = render(<MemoryRouter><Shell workspaceName="Lab" theme="light" onTheme={theme} navOpen onNav={nav}><p>Content</p></Shell></MemoryRouter>);
    expect(screen.getByText("Lab")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Use dark theme")); fireEvent.click(screen.getAllByLabelText("Close navigation")[0]);
    const search = screen.getByLabelText("Search workspace");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(search).toHaveFocus();
    fireEvent.change(search, { target: { value: "Golden home" } });
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.change(search, { target: { value: "" } });
    fireEvent.submit(screen.getByRole("search"));
    view.rerender(<MemoryRouter><Shell workspaceName="Lab" theme="dark" onTheme={theme} navOpen={false} onNav={nav}><p>Content</p></Shell></MemoryRouter>);
    expect(screen.getByLabelText("Use light theme")).toBeInTheDocument();
    expect(theme).toHaveBeenCalled(); expect(nav).toHaveBeenCalled();
  });

  it("renders shared content and callback states", () => {
    const retry = vi.fn();
    render(<MemoryRouter><PageHeader eyebrow="Context" title="Title" description="Description" actions={<button>Act</button>} /><StatusBadge status="running" /><ProgressBar value={120} label="Work" /><EmptyState title="Empty"><p>Nothing</p></EmptyState><ErrorPanel message="Failure" onRetry={retry} /><Skeleton lines={2} /><Metric label="Runs" value={4} detail="verified" /><Breadcrumbs items={[{ label: "Homes", to: "/homes" }, { label: "Kitchen" }]} /><RunLink id="run">Open</RunLink></MemoryRouter>);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "120");
    fireEvent.click(screen.getByText("Try again")); expect(retry).toHaveBeenCalled();
    expect(screen.getByLabelText("Breadcrumb")).toHaveTextContent("Kitchen");
    expect(screen.getByText("Open").closest("a")).toHaveAttribute("href", "/simulations/run");
  });

  it("supports pointer and keyboard plan selection plus replay trajectories", () => {
    const select = vi.fn();
    const view = render(<PlanCanvas home={home} sensors={sensors} selectedId="kitchen" onSelect={select} viewport={{ zoom: 2, x: 1, y: -1 }} activeMovement={{ at: "2026-01-01T00:00:00Z", end: "2026-01-01T00:01:00Z", kind: "movement", id: "m", actorId: "r", label: "walk", status: "completed", waypoints: [{ at: "2026-01-01T00:00:00Z", regionId: "kitchen", position: { x: 1, y: 1 } }] }} />);
    fireEvent.click(screen.getByLabelText("room kitchen"));
    fireEvent.keyDown(screen.getByLabelText("oven oven"), { key: "Enter" });
    fireEvent.keyDown(screen.getByLabelText("pir sensor pir"), { key: " " });
    fireEvent.click(screen.getByLabelText("Obstacle table"));
    expect(select.mock.calls.flat()).toEqual(["kitchen", "oven", "pir", "table"]);
    expect(screen.getByLabelText("Active trajectory")).toBeInTheDocument();
    view.rerender(<PlanCanvas home={{ ...home, connections: [{ connectionId: "broken", regionAId: "kitchen", regionBId: "missing", kind: "doorway", bidirectional: true, widthMeters: 1 }], entities: [...home.entities, { ...home.entities[0], entityId: "orphan", interactionPointId: "missing" }] }} />);
    expect(screen.queryByLabelText("oven orphan")).not.toBeInTheDocument();
  });

  it("draws a furniture glyph over a typed obstacle and a doorway at its portals", () => {
    const furnished: HomeModel = {
      ...home,
      connections: [{ connectionId: "door", regionAId: "kitchen", regionBId: "kitchen", kind: "doorway", bidirectional: true, widthMeters: 1, portalA: { x: 1, y: 0.4 }, portalB: { x: 1, y: -0.4 } }],
      obstacles: [
        { obstacleId: "obstacle_fridge_01", regionId: "kitchen", boundary: { vertices: [{ x: 0, y: 0 }, { x: 0.7, y: 0 }, { x: 0.7, y: 0.7 }, { x: 0, y: 0.7 }] } },
        { obstacleId: "obstacle_mystery_01", regionId: "kitchen", boundary: { vertices: [{ x: 2, y: 2 }, { x: 3, y: 2 }, { x: 3, y: 3 }, { x: 2, y: 3 }] } },
      ],
      entities: [
        { entityId: "fridge_01", entityType: "refrigerator", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} },
        { entityId: "mystery_01", entityType: "unmapped_thing", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} },
      ],
    };
    const { container } = render(<PlanCanvas home={furnished} />);
    const glyphs = container.querySelectorAll("use.furniture-glyph");
    // The known type gets its symbol; the unmapped one falls back to the bare footprint.
    expect(glyphs).toHaveLength(1);
    expect(glyphs[0].getAttribute("href")).toBe("#furn-refrigerator");
    expect(screen.getByLabelText("Obstacle obstacle_fridge_01 (refrigerator)")).toBeInTheDocument();
    const door = container.querySelector("line.connection-doorway");
    expect(door?.getAttribute("y1")).toBe("0.4");
    expect(door?.getAttribute("y2")).toBe("-0.4");
  });

  it("mutes the generated fallback provider so it does not caption every room", () => {
    const withService: HomeModel = {
      ...home,
      entities: [
        ...home.entities,
        { entityId: "service_kitchen", entityType: "generated_environment_service", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} },
      ],
    };
    const { container } = render(<PlanCanvas home={withService} />);
    const service = container.querySelector("g.entity-node.is-service");
    const real = container.querySelector("g.entity-node:not(.is-service)");
    expect(service).not.toBeNull();
    expect(service?.querySelector("circle")?.getAttribute("r")).toBe(".1");
    // A real provider keeps its marker and its crosshair; the fallback gets neither.
    expect(service?.querySelector("path")).toBeNull();
    expect(real?.querySelector("path")).not.toBeNull();
  });
});
