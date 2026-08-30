import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Breadcrumbs, EmptyState, ErrorPanel, Metric, PageHeader, PlanCanvas, ProgressBar, RunLink, Shell, Skeleton, StatusBadge } from "../components";
import { FurnitureSymbols } from "../furniture-symbols";
import { FURNITURE_SIZES } from "../furniture";
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

// jsdom has no PointerEvent, and a synthetic one loses the coordinates the canvas measures with.
const pointer = (type: string, clientX: number, clientY: number) =>
  new MouseEvent(type, { bubbles: true, clientX, clientY });

describe("application components", () => {
  // Without this every render in the file stacks up in the document, and a query for a room finds
  // one per test that ever drew it.
  afterEach(cleanup);

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

  it("collapses the navigation to its icons and back", () => {
    const collapse = vi.fn();
    const view = render(<MemoryRouter><Shell workspaceName="Lab" theme="light" onTheme={vi.fn()} navOpen={false} onNav={vi.fn()} navCollapsed={false} onNavCollapse={collapse}><p>Content</p></Shell></MemoryRouter>);
    fireEvent.click(screen.getByLabelText("Collapse navigation"));
    expect(collapse).toHaveBeenCalled();
    expect(view.container.querySelector(".app-shell.nav-collapsed")).toBeNull();

    view.rerender(<MemoryRouter><Shell workspaceName="Lab" theme="light" onTheme={vi.fn()} navOpen={false} onNav={vi.fn()} navCollapsed onNavCollapse={collapse}><p>Content</p></Shell></MemoryRouter>);
    expect(view.container.querySelector(".app-shell.nav-collapsed")).not.toBeNull();
    expect(screen.getByLabelText("Expand navigation")).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a sensor field without burying the plan under it", () => {
    // Every coverage drawn at once was six translucent rectangles over one another; the field a
    // researcher is reading is the one they selected.
    const view = render(<PlanCanvas home={home} sensors={sensors} />);
    expect(view.container.querySelector("polygon.sensor-coverage")).toBeNull();
    // Interaction points are context the sensor layer does not need.
    expect(view.container.querySelector("circle.interaction-point")).toBeNull();
    expect(view.container.querySelector(".plan-canvas.shows-sensors")).not.toBeNull();

    view.rerender(<PlanCanvas home={home} sensors={sensors} selectedId="pir" />);
    expect(view.container.querySelector("polygon.sensor-coverage")).not.toBeNull();
    // Each family keeps its own shape, so a plan of thirty nodes still says what watches what.
    expect(view.container.querySelector(".sensor-pir .sensor-glyph")).not.toBeNull();
    expect(view.container.querySelector(".sensor-pir text")?.textContent).toBe("pir");
  });

  it("draws every symbol at the size the generator gives that piece of furniture", () => {
    // A symbol is authored at life size, one unit to the centimetre, which is what lets the glyph
    // fill its footprint instead of floating inside it — and what lets the palette hand you a bed
    // that is really 1.60 by 2.00. Two tables saying the same thing drift; this is what stops them.
    const { container } = render(<svg><FurnitureSymbols /></svg>);
    const symbols = [...container.querySelectorAll("symbol")];
    expect(symbols.length).toBeGreaterThan(40);
    for (const symbol of symbols) {
      const type = (symbol.getAttribute("id") ?? "").replace(/^furn-/, "");
      const size = FURNITURE_SIZES[type];
      expect(size, `no size declared for ${type}`).toBeDefined();
      const [extent, depth] = size!;
      expect(symbol.getAttribute("viewBox"), `${type} is drawn at the wrong size`)
        .toBe(`0 0 ${String(Math.round(extent * 100))} ${String(Math.round(depth * 100))}`);
    }
  });

  it("draws furniture turned the way the obstacle says it is turned", () => {
    // The glyph is authored with the wall at the top and the front at the bottom, which is a
    // bearing of 90. Anything else has to be rotated, and a bed drawn across its own headboard was
    // what the plan did before the obstacle carried an orientation at all.
    const turned: HomeModel = {
      ...home,
      obstacles: [
        { obstacleId: "obstacle_bed", regionId: "kitchen", orientationDegrees: 180,
          boundary: { vertices: [{ x: .5, y: .5 }, { x: 2.5, y: .5 }, { x: 2.5, y: 2.1 }, { x: .5, y: 2.1 }] } },
        { obstacleId: "obstacle_stairs_kitchen", regionId: "kitchen",
          boundary: { vertices: [{ x: 3, y: .5 }, { x: 3.8, y: .5 }, { x: 3.8, y: 3 }, { x: 3, y: 3 }] } },
      ],
      entities: [{ entityId: "bed", entityType: "bed", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} }],
    };
    const view = render(<PlanCanvas home={turned} />);
    const bed = view.container.querySelector('use[href="#furn-bed"]');
    expect(bed).not.toBeNull();
    // Turned a quarter about the footprint's centre, and drawn into the transposed box so it fills
    // the obstacle instead of shrinking to fit inside it.
    expect(bed?.parentElement?.getAttribute("transform")).toBe("rotate(90 1.5 1.3)");
    expect(bed?.getAttribute("width")).toBe("1.6");
    expect(bed?.getAttribute("preserveAspectRatio")).toBe("none");
    // A staircase belongs to the building, not to its contents, so it has no entity to be named by.
    expect(view.container.querySelector('use[href="#furn-stairs"]')).not.toBeNull();
  });

  it("draws a home written before orientation existed exactly as it did before", () => {
    // No bearing to turn by, so nothing is turned and the glyph is fitted rather than stretched —
    // which is what every home generated up to now says, and it must keep saying it.
    const old: HomeModel = {
      ...home,
      obstacles: [{ obstacleId: "obstacle_bed", regionId: "kitchen",
        boundary: { vertices: [{ x: .5, y: .5 }, { x: 2.5, y: .5 }, { x: 2.5, y: 2.1 }, { x: .5, y: 2.1 }] } }],
      entities: [{ entityId: "bed", entityType: "bed", regionId: "kitchen", interactionPointId: "point", capabilities: [], initialState: {} }],
    };
    const view = render(<PlanCanvas home={old} />);
    const glyph = view.container.querySelector('use[href="#furn-bed"]');
    expect(glyph?.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    expect(glyph?.parentElement?.getAttribute("transform")).toBeNull();
  });

  it("reads a house one storey at a time", () => {
    const house: HomeModel = {
      ...home,
      regions: [
        home.regions[0],
        { regionId: "bedroom", kind: "room", traversable: true, level: 1,
          boundary: { vertices: [{ x: 8, y: 0 }, { x: 12, y: 0 }, { x: 12, y: 4 }, { x: 8, y: 4 }] } },
        { regionId: "cellar", kind: "room", traversable: true, level: -1,
          boundary: { vertices: [{ x: 16, y: 0 }, { x: 19, y: 0 }, { x: 19, y: 3 }, { x: 16, y: 3 }] } },
        { regionId: "vault", kind: "room", traversable: true, level: -2,
          boundary: { vertices: [{ x: 22, y: 0 }, { x: 25, y: 0 }, { x: 25, y: 3 }, { x: 22, y: 3 }] } },
      ],
    };
    const view = render(<PlanCanvas home={house} />);
    expect(screen.getByLabelText("room kitchen")).toBeInTheDocument();
    expect(screen.queryByLabelText("room bedroom")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Floor 1" }));
    expect(screen.getByLabelText("room bedroom")).toBeInTheDocument();
    expect(screen.queryByLabelText("room kitchen")).not.toBeInTheDocument();
    // Down is a floor like any other, and the switcher says so in the words a house uses.
    fireEvent.click(screen.getByRole("button", { name: "Basement" }));
    expect(screen.getByLabelText("room cellar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Basement 2" }));
    expect(screen.getByLabelText("room vault")).toBeInTheDocument();
    // A flat has one floor and nothing to choose between.
    view.rerender(<PlanCanvas home={home} />);
    expect(screen.queryByRole("group", { name: "Storey" })).not.toBeInTheDocument();
  });

  it("renders shared content and callback states", () => {
    const retry = vi.fn();
    render(<MemoryRouter><PageHeader eyebrow="Context" title="Title" description="Description" actions={<button>Act</button>} /><StatusBadge status="running" /><ProgressBar value={120} label="Work" /><EmptyState title="Empty"><p>Nothing</p></EmptyState><ErrorPanel message="Failure" onRetry={retry} /><Skeleton lines={2} /><Metric label="Runs" value={4} detail="verified" /><Breadcrumbs items={[{ label: "Homes", to: "/homes" }, { label: "Kitchen" }]} /><RunLink id="run">Open</RunLink></MemoryRouter>);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "120");
    fireEvent.click(screen.getByText("Try again")); expect(retry).toHaveBeenCalled();
    expect(screen.getByLabelText("Breadcrumb")).toHaveTextContent("Kitchen");
    expect(screen.getByText("Open").closest("a")).toHaveAttribute("href", "/simulations/run");
  });

  it("supports pointer and keyboard plan selection", () => {
    const select = vi.fn();
    const view = render(<PlanCanvas home={home} sensors={sensors} selectedId="kitchen" onSelect={select} viewport={{ zoom: 2, x: 1, y: -1 }} />);
    fireEvent.click(screen.getByLabelText("room kitchen"));
    fireEvent.keyDown(screen.getByLabelText("oven oven"), { key: "Enter" });
    fireEvent.keyDown(screen.getByLabelText("pir sensor pir"), { key: " " });
    fireEvent.click(screen.getByLabelText("Obstacle table"));
    expect(select.mock.calls.flat()).toEqual(["kitchen", "oven", "pir", "table"]);
    view.rerender(<PlanCanvas home={{ ...home, connections: [{ connectionId: "broken", regionAId: "kitchen", regionBId: "missing", kind: "doorway", bidirectional: true, widthMeters: 1 }], entities: [...home.entities, { ...home.entities[0], entityId: "orphan", interactionPointId: "missing" }] }} />);
    expect(screen.queryByLabelText("oven orphan")).not.toBeInTheDocument();
  });

  it("keeps passive plans fitted while the wheel remains available to page scrolling", () => {
    const passive = render(<PlanCanvas home={home} sensors={sensors} interactionMode="passive" />);
    const passivePlan = passive.container.querySelector("svg.plan-canvas") as SVGSVGElement;
    const initialViewBox = passivePlan.getAttribute("viewBox");
    const passiveWheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 120 });

    fireEvent(passivePlan, passiveWheel);

    expect(passiveWheel.defaultPrevented).toBe(false);
    expect(passivePlan).toHaveAttribute("data-interaction-mode", "passive");
    expect(passivePlan).toHaveAttribute("viewBox", initialViewBox);

    passive.unmount();
    const interactive = render(<PlanCanvas home={home} sensors={sensors} />);
    const interactivePlan = interactive.container.querySelector("svg.plan-canvas") as SVGSVGElement;
    const interactiveWheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 120 });

    fireEvent(interactivePlan, interactiveWheel);

    expect(interactiveWheel.defaultPrevented).toBe(true);
    expect(interactivePlan).toHaveAttribute("data-interaction-mode", "interactive");
  });

  it("moves and resizes plan objects by pointer, reporting gestures in metres", () => {
    // The canvas measures the gesture and hands over metres; the page owns the model. Without a
    // laid-out SVG there is no pixel-to-metre scale, so the element is given one here.
    const editing = { onDragStart: vi.fn(), onMove: vi.fn(), onResize: vi.fn() };
    const { container } = render(<PlanCanvas home={home} sensors={sensors} selectedId="kitchen" editing={editing} />);
    const svg = container.querySelector("svg") as SVGSVGElement;
    // 8 metres of plan (4 of rooms plus the 2-metre margins) drawn across 800 pixels.
    svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" });

    const room = container.querySelector('[aria-label="room kitchen"]') as Element;
    fireEvent(room, pointer("pointerdown", 100, 100));
    fireEvent(svg, pointer("pointermove", 200, 100));

    expect(editing.onDragStart).toHaveBeenCalledTimes(1);
    expect(editing.onMove).toHaveBeenCalledWith("kitchen", 1, 0);

    const handle = container.querySelector('[aria-label="Resize kitchen e"]') as Element;
    fireEvent(handle, pointer("pointerdown", 0, 0));
    fireEvent(svg, pointer("pointermove", 50, 0));
    fireEvent(svg, pointer("pointerup", 50, 0));

    expect(editing.onResize).toHaveBeenCalledWith("kitchen", "e", 0.5, 0);
    // A gesture that ended reports nothing more, and a plan that is not being edited never starts.
    fireEvent(svg, pointer("pointermove", 400, 400));
    expect(editing.onMove).toHaveBeenCalledTimes(1);
  });

  it("drags furniture in one gesture and a room only once it is chosen", () => {
    // A chair is small and you press it because you mean it, so it moves on the first drag — which
    // is what drag and drop means everywhere else. A room covers the canvas, and a stray drag on
    // one is a published wall in the wrong place, so it still has to be selected first.
    const editing = { onDragStart: vi.fn(), onMove: vi.fn(), onResize: vi.fn() };
    const select = vi.fn();
    const { container } = render(<PlanCanvas home={home} sensors={sensors} onSelect={select} editing={editing} />);
    const svg = container.querySelector("svg") as SVGSVGElement;
    svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" });

    const obstacle = container.querySelector('[aria-label^="Obstacle table"]') as Element;
    fireEvent(obstacle, pointer("pointerdown", 100, 100));
    fireEvent(svg, pointer("pointermove", 180, 100));
    fireEvent(svg, pointer("pointerup", 180, 100));
    expect(select).toHaveBeenCalledWith("table");
    expect(editing.onMove).toHaveBeenCalled();

    editing.onMove.mockClear();
    const before = svg.getAttribute("viewBox");
    const room = container.querySelector('[aria-label="room kitchen"]') as Element;
    fireEvent(room, pointer("pointerdown", 100, 100));
    fireEvent(svg, pointer("pointermove", 180, 100));
    fireEvent(svg, pointer("pointerup", 180, 100));
    expect(editing.onMove).not.toHaveBeenCalled();
    expect(svg.getAttribute("viewBox")).not.toBe(before);
  });

  it("shows the line a drag lines up with, while the drag is held", () => {
    // The magnet was arithmetic nobody could see: the piece simply arrived somewhere slightly
    // different from where it was let go. Drawing the line it landed on is what makes that a
    // feature rather than a drift.
    const furnished: HomeModel = {
      ...home,
      obstacles: [{
        obstacleId: "wardrobe", regionId: "kitchen",
        boundary: { vertices: [{ x: 1, y: 1 }, { x: 1.6, y: 1 }, { x: 1.6, y: 2.2 }, { x: 1, y: 2.2 }] },
      }],
    };
    const moved = { ...furnished, obstacles: [{ ...furnished.obstacles[0]!, boundary: { vertices: [{ x: .08, y: 1 }, { x: .68, y: 1 }, { x: .68, y: 2.2 }, { x: .08, y: 2.2 }] } }] };
    const editing = { onDragStart: vi.fn(), onMove: vi.fn(), onResize: vi.fn() };
    const view = render(<PlanCanvas home={furnished} selectedId="wardrobe" editing={editing} />);
    const svg = view.container.querySelector("svg") as SVGSVGElement;
    svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" }) as DOMRect;

    fireEvent(view.container.querySelector('[aria-label^="Obstacle wardrobe"]') as Element, pointer("pointerdown", 200, 200));
    // Re-rendered with the piece where the page moved it to: eight centimetres from the wall, which
    // is inside the magnet's reach, so the next sample reports a corrected delta and a guide.
    view.rerender(<PlanCanvas home={moved} selectedId="wardrobe" editing={editing} />);
    fireEvent(svg, pointer("pointermove", 199, 200));
    expect(view.container.querySelector(".align-guide")).not.toBeNull();
    fireEvent(svg, pointer("pointerup", 199, 200));
    expect(view.container.querySelector(".align-guide")).toBeNull();
  });

  it("draws a room, opens a doorway and drops an object where it was pointed at", () => {
    const editing = {
      onDragStart: vi.fn(), onMove: vi.fn(), onResize: vi.fn(),
      onDrawRoom: vi.fn(), onPlaceDoor: vi.fn(), onPlaceObject: vi.fn(), onToolUsed: vi.fn(),
    };
    const twoRooms: HomeModel = {
      ...home,
      regions: [
        home.regions[0]!,
        { regionId: "hall", kind: "room", traversable: true, boundary: { vertices: [{ x: 4, y: 0 }, { x: 8, y: 0 }, { x: 8, y: 4 }, { x: 4, y: 4 }] } },
      ],
    };
    const measured = (svg: SVGSVGElement) => {
      svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" });
      return svg;
    };

    const drawn = render(<PlanCanvas home={twoRooms} editing={editing} tool="room" />);
    const drawSvg = measured(drawn.container.querySelector("svg") as SVGSVGElement);
    fireEvent(drawSvg, pointer("pointerdown", 200, 200));
    fireEvent(drawSvg, pointer("pointermove", 400, 400));
    expect(drawn.container.querySelector(".draw-draft")).not.toBeNull();
    fireEvent(drawSvg, pointer("pointerup", 400, 400));
    expect(editing.onDrawRoom).toHaveBeenCalled();
    expect(editing.onToolUsed).toHaveBeenCalled();
    cleanup();

    const doored = render(<PlanCanvas home={twoRooms} editing={editing} tool="door" />);
    const doorSvg = measured(doored.container.querySelector("svg") as SVGSVGElement);
    // The party wall runs at x = 4; the pointer is put on it in plan metres, through the viewBox.
    const [viewX, viewY, viewW, viewH] = (doorSvg.getAttribute("viewBox") ?? "0 0 1 1").split(" ").map(Number);
    const atPlan = (x: number, y: number) => [
      ((x - viewX!) / viewW!) * 800, ((y - viewY!) / viewH!) * 800,
    ] as const;
    fireEvent(doorSvg, pointer("pointermove", ...atPlan(4, 2)));
    expect(doored.container.querySelector(".door-preview")).not.toBeNull();
    fireEvent(doorSvg, pointer("pointerup", ...atPlan(4, 2)));
    expect(editing.onPlaceDoor).toHaveBeenCalledWith(expect.objectContaining({ regionAId: "hall", regionBId: "kitchen" }));
    cleanup();

    const dropped = render(<PlanCanvas home={twoRooms} editing={editing} tool="obstacle" />);
    const dropSvg = measured(dropped.container.querySelector("svg") as SVGSVGElement);
    const [dx, dy] = atPlan(2, 2);
    fireEvent(dropSvg, pointer("pointermove", dx, dy));
    expect(dropped.container.querySelector(".drop-mark")).not.toBeNull();
    fireEvent(dropSvg, pointer("pointerup", dx, dy));
    expect(editing.onPlaceObject).toHaveBeenCalledWith("obstacle", expect.objectContaining({ x: expect.any(Number) }), 0);
    // Pointing at the void outside every room creates nothing rather than something nowhere.
    editing.onPlaceObject.mockClear();
    fireEvent(dropSvg, pointer("pointerup", 5, 5));
    expect(editing.onPlaceObject).not.toHaveBeenCalled();
  });

  it("selects without moving the plan when the press barely travels", () => {
    // Clicking a sensor used to shift the drawing out from under the pointer: the press is never
    // perfectly still, and the first stray pixel was taken for a pan.
    const select = vi.fn();
    const { container } = render(<PlanCanvas home={home} sensors={sensors} onSelect={select} />);
    const svg = container.querySelector("svg") as SVGSVGElement;
    svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" });
    const before = svg.getAttribute("viewBox");
    const sensor = container.querySelector('[aria-label="pir sensor pir"]') as Element;

    fireEvent(sensor, pointer("pointerdown", 300, 300));
    fireEvent(svg, pointer("pointermove", 302, 301));
    fireEvent(svg, pointer("pointerup", 302, 301));
    fireEvent.click(sensor);

    expect(svg.getAttribute("viewBox")).toBe(before);
    expect(select).toHaveBeenCalledWith("pir");

    // Past the threshold it is a drag, and the plan follows the pointer.
    fireEvent(svg, pointer("pointerdown", 300, 300));
    fireEvent(svg, pointer("pointermove", 340, 300));
    expect(svg.getAttribute("viewBox")).not.toBe(before);
  });

  it("offers resize handles for areas only, and none when the plan is read-only", () => {
    const editing = { onDragStart: vi.fn(), onMove: vi.fn(), onResize: vi.fn() };
    const areas = render(<PlanCanvas home={home} sensors={sensors} selectedId="pir" editing={editing} />);
    // A PIR is resized through its coverage: the area is what you are shaping.
    expect(areas.container.querySelectorAll("rect.resize-handle")).toHaveLength(8);
    areas.rerender(<PlanCanvas home={home} sensors={sensors} selectedId="oven" editing={editing} />);
    // A provider is a point on the plan; it can be dragged, not stretched.
    expect(areas.container.querySelectorAll("rect.resize-handle")).toHaveLength(0);
    areas.rerender(<PlanCanvas home={home} sensors={sensors} selectedId="kitchen" />);
    expect(areas.container.querySelectorAll("rect.resize-handle")).toHaveLength(0);
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
    // The door is an opening in the wall, not a line drawn over it: a 1-metre threshold across
    // the wall the two portals straddle, with a leaf and the quarter-circle it sweeps.
    const threshold = container.querySelector("line.door-threshold");
    expect(threshold?.getAttribute("x1")).toBe("0.5");
    expect(threshold?.getAttribute("x2")).toBe("1.5");
    expect(threshold?.getAttribute("y1")).toBe("0");
    const leaf = container.querySelector("line.door-leaf");
    expect(leaf?.getAttribute("y2")).toBe("-1");
    expect(container.querySelector("path.door-swing")).not.toBeNull();
  });

  it("pans by dragging the plan and zooms towards the cursor", () => {
    // Nudging a twelve-metre flat one metre per button press is not navigation.
    const { container } = render(<PlanCanvas home={home} sensors={sensors} />);
    const svg = container.querySelector("svg") as SVGSVGElement;
    svg.getBoundingClientRect = () => ({ width: 800, height: 800, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 800, toJSON: () => "" });
    const before = svg.getAttribute("viewBox");

    fireEvent(svg, pointer("pointerdown", 400, 400));
    fireEvent(svg, pointer("pointermove", 300, 400));
    fireEvent(svg, pointer("pointerup", 300, 400));
    const panned = svg.getAttribute("viewBox");
    expect(panned).not.toBe(before);
    // Dragging left moves the window right by the same metre count the pointer travelled.
    expect(Number(panned?.split(" ")[0]) - Number(before?.split(" ")[0])).toBeCloseTo(1, 6);

    fireEvent.wheel(svg, { deltaY: -400, clientX: 0, clientY: 0 });
    const zoomed = svg.getAttribute("viewBox")?.split(" ").map(Number) ?? [];
    const start = panned?.split(" ").map(Number) ?? [];
    expect(zoomed[2]).toBeLessThan(start[2] as number);
    // The corner under the cursor stays where it was while the view closes in on it.
    expect(zoomed[0]).toBeCloseTo(start[0] as number, 6);
    expect(zoomed[1]).toBeCloseTo(start[1] as number, 6);
  });

  it("draws the house, not the town it is standing in", () => {
    // The model keeps the supermarket as a region so the resident has somewhere to be when they
    // are out. On a planimetry it is 20 metres of empty canvas around a flat nobody can read.
    const town: HomeModel = {
      ...home,
      regions: [
        ...home.regions,
        { regionId: "supermarket", kind: "external", traversable: true, boundary: { vertices: [{ x: 0, y: 20 }, { x: 6, y: 20 }, { x: 6, y: 26 }, { x: 0, y: 26 }] } },
      ],
      connections: [{ connectionId: "t", regionAId: "kitchen", regionBId: "supermarket", kind: "transit", bidirectional: true, widthMeters: 1 }],
      obstacles: [...home.obstacles, { obstacleId: "shelf", regionId: "supermarket", boundary: { vertices: [{ x: 1, y: 21 }, { x: 2, y: 21 }, { x: 2, y: 22 }, { x: 1, y: 22 }] } }],
      entities: [...home.entities, { entityId: "till", entityType: "till", regionId: "supermarket", interactionPointId: "point", capabilities: [], initialState: {} }],
    };

    const view = render(<PlanCanvas home={town} sensors={sensors} />);
    expect(view.container.querySelector('[aria-label="external supermarket"]')).toBeNull();
    expect(view.container.querySelector('[aria-label="Obstacle shelf"]')).toBeNull();
    expect(view.container.querySelector('[aria-label="till till"]')).toBeNull();
    // A transit link with one end hidden would be drawn as a ray into empty space.
    expect(view.container.querySelector("line.connection-transit")).toBeNull();
    expect(view.container.querySelector('[aria-label="room kitchen"]')).not.toBeNull();
    // The viewport is the flat: 4 metres of room plus the fixed 2-metre margin on each side.
    expect(view.container.querySelector("svg")?.getAttribute("viewBox")).toBe("-2 -2 8 8");

    view.rerender(<PlanCanvas home={town} sensors={sensors} showExternalPlaces />);
    expect(view.container.querySelector('[aria-label="external supermarket"]')).not.toBeNull();
    expect(view.container.querySelector('[aria-label="till till"]')).not.toBeNull();
  });

  it("draws a provider as the spot you stand on, with the reach the model gives it", () => {
    // The blue dot is not the stove: it is where the resident stands to use it, and the hatched
    // box is the stove. The approach radius is what makes that legible without a caption.
    const { container } = render(<PlanCanvas home={home} />);
    const reach = container.querySelector(".entity-node .approach-radius");
    expect(reach?.getAttribute("r")).toBe("1");
    expect(container.querySelector(".plan-legend")?.textContent).toContain("Use point");
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
