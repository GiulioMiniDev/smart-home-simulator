import {
  Activity,
  AlertTriangle,
  BookOpen,
  Box,
  ChevronRight,
  CircleHelp,
  Download,
  FlaskConical,
  Home,
  ListTree,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Sparkles,
  Sun,
  Trash2,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, PointerEvent as ReactPointerEvent, PropsWithChildren, ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  boxOf,
  cutDoorways,
  dwellingRegionIds,
  magnet,
  planDoors,
  planFrontDoor,
  planProblems,
  planWalls,
  polygonArea,
  regionAt,
  sharedWallAt,
} from "./editor";
import type { PlanBox, ResizeHandle, WallCandidate } from "./editor";
import { furnitureSymbol, structuralSymbol } from "./furniture";
import { FurnitureGlyph } from "./furniture-glyph";
import { FurnitureSymbols } from "./furniture-symbols";
import { CustomFurnitureSymbols } from "./vocabulary/CustomFurnitureSymbols";
import type { HomeModel, JobStatus, Point, Polygon, SensorModel } from "./types";

const nav = [
  { to: "/", label: "Dashboard", icon: Activity },
  { to: "/generate", label: "Generate", icon: Sparkles },
  { to: "/homes", label: "Homes", icon: Home },
  { to: "/vocabulary", label: "Vocabulary", icon: ListTree },
  { to: "/residents", label: "Residents", icon: Users },
  { to: "/simulations", label: "Simulations", icon: FlaskConical },
  { to: "/exports", label: "Exports", icon: Download },
  { to: "/maintenance", label: "Maintenance", icon: Wrench },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/help", label: "Guide", icon: BookOpen },
];

interface ShellProps extends PropsWithChildren {
  workspaceName?: string;
  theme: "light" | "dark";
  onTheme: () => void;
  navOpen: boolean;
  onNav: () => void;
  /** Collapsed to its icons, to give the plan the width it deserves. Persisted by the page. */
  navCollapsed?: boolean;
  onNavCollapse?: () => void;
}

export function Shell({
  children,
  workspaceName = "Local workspace",
  theme,
  onTheme,
  navOpen,
  onNav,
  navCollapsed = false,
  onNavCollapse,
}: ShellProps) {
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    navigate(`/homes${query.trim() ? `?query=${encodeURIComponent(query.trim())}` : ""}`);
  };
  return (
    <div className={`app-shell ${navCollapsed ? "nav-collapsed" : ""}`} data-theme={theme}>
      <aside className={`sidebar ${navOpen ? "is-open" : ""}`} aria-label="Primary navigation">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <Box size={18} strokeWidth={1.8} />
          </span>
          <span>
            <strong>Habitat Lab</strong>
            <small>Simulation workspace</small>
          </span>
          <button className="icon-button sidebar-close" onClick={onNav} aria-label="Close navigation">
            <X size={18} />
          </button>
          {onNavCollapse && (
            <button
              className="icon-button sidebar-collapse"
              onClick={onNavCollapse}
              aria-label={navCollapsed ? "Expand navigation" : "Collapse navigation"}
              aria-pressed={navCollapsed}
              title={navCollapsed ? "Expand navigation" : "Collapse navigation"}
            >
              {navCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            </button>
          )}
        </div>
        <nav>
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => navOpen && onNav()} title={label}>
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-context">
          <span>Current workspace</span>
          <strong>{workspaceName}</strong>
          <small>Local · schema 1.0.0</small>
        </div>
      </aside>
      {navOpen && <button className="nav-scrim" onClick={onNav} aria-label="Close navigation" />}
      <div className="app-body">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={onNav} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <form className="global-search" role="search" onSubmit={submitSearch}>
            <Search size={17} aria-hidden="true" />
            <input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search workspace" placeholder="Search homes" />
            <kbd>Ctrl K</kbd>
          </form>
          <span className="worker-indicator"><i /> Local engine ready</span>
          <button className="icon-button" onClick={onTheme} aria-label={`Use ${theme === "light" ? "dark" : "light"} theme`}>
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <NavLink className="icon-button" to="/help" aria-label="Open help">
            <CircleHelp size={18} />
          </NavLink>
        </header>
        <main id="main-content">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

/**
 * A destructive action that takes two deliberate clicks and says what it will destroy.
 *
 * Deleting a home takes its runs, exports and stored inputs with it, which is exactly what a
 * researcher reclaiming disk space wants and exactly what nobody wants by accident. The second
 * click is the confirmation; the consequence is written above it rather than in a browser dialog
 * that the local application cannot style, translate or test.
 */
export function ConfirmAction({
  label,
  title,
  consequence,
  busy = false,
  disabled = false,
  compact = false,
  onConfirm,
}: {
  label: string;
  title: string;
  consequence: string;
  busy?: boolean;
  disabled?: boolean;
  compact?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button
        className={compact ? "icon-button danger" : "button danger"}
        disabled={disabled || busy}
        aria-label={compact ? label : undefined}
        onClick={() => setAsking(true)}
      >
        <Trash2 size={compact ? 15 : 16} />
        {!compact && label}
      </button>
    );
  }
  return (
    <div className="confirm-action" role="alertdialog" aria-label={title}>
      <div>
        <strong>{title}</strong>
        <small>{consequence}</small>
      </div>
      <div className="button-row">
        <button className="button secondary" disabled={busy} onClick={() => setAsking(false)}>
          Keep it
        </button>
        <button
          className="button danger"
          disabled={busy}
          onClick={() => {
            setAsking(false);
            void onConfirm();
          }}
        >
          <Trash2 size={15} /> {busy ? "Deleting…" : label}
        </button>
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: JobStatus | string }) {
  return (
    <span className={`status status-${status}`}>
      <i aria-hidden="true" />
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="progress-block">
      <div className="progress-label">
        <span>{label}</span>
        <span>{Math.round(value)}%</span>
      </div>
      <div className="progress-track" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
        <i style={{ width: `${Math.max(0, Math.min(value, 100))}%` }} />
      </div>
    </div>
  );
}

export function EmptyState({
  icon = <Box size={25} />,
  title,
  children,
  action,
}: PropsWithChildren<{ icon?: ReactNode; title: string; action?: ReactNode }>) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      <div>{children}</div>
      {action}
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-panel" role="alert">
      <AlertTriangle size={20} aria-hidden="true" />
      <div><strong>Could not load this view</strong><p>{message}</p></div>
      {onRetry && <button className="button secondary" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-label="Loading" aria-busy="true">
      {Array.from({ length: lines }, (_, index) => <i key={index} style={{ width: `${92 - index * 7}%` }} />)}
    </div>
  );
}

export function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: Array<{ label: string; to?: string }> }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`}>
          {item.to ? <NavLink to={item.to}>{item.label}</NavLink> : <span aria-current="page">{item.label}</span>}
          {index < items.length - 1 && <ChevronRight size={14} aria-hidden="true" />}
        </span>
      ))}
    </nav>
  );
}

function polygonPoints(points: Point[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

// Generated fallback provider: carries the capabilities no real piece of furniture claims.
const SERVICE_ENTITY_TYPE = "generated_environment_service";

function bounds(points: Point[]): { minX: number; minY: number; maxX: number; maxY: number } | undefined {
  if (points.length === 0) return undefined;
  return {
    minX: Math.min(...points.map((point) => point.x)),
    minY: Math.min(...points.map((point) => point.y)),
    maxX: Math.max(...points.map((point) => point.x)),
    maxY: Math.max(...points.map((point) => point.y)),
  };
}

function center(points: Point[]): Point {
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / Math.max(points.length, 1),
    y: points.reduce((sum, point) => sum + point.y, 0) / Math.max(points.length, 1),
  };
}

/**
 * What the canvas needs from the page to let the plan be edited by hand.
 *
 * The canvas measures gestures and reports them in metres; it never owns the model. `onDragStart`
 * is what the page turns into one undo step per gesture, rather than one per pointer sample.
 */
/**
 * What the canvas is for at this moment.
 *
 * Every one of these was a button that dropped its object somewhere and left you to drag it into
 * place — a room off the side of the plan, a sofa in the middle of the first room, a PIR in
 * whichever room happened to be traversable first. A tool puts the object where you point.
 */
/** Ground floor, the floors above it, and the cellars below. */
function storeyLabel(level: number): string {
  if (level === 0) return "Ground floor";
  if (level > 0) return `Floor ${String(level)}`;
  return level === -1 ? "Basement" : `Basement ${String(-level)}`;
}

export type PlanTool = "select" | "room" | "door" | "obstacle" | "pir" | "contact" | "temperature";

export interface PlanEditing {
  onDragStart: () => void;
  onMove: (id: string, dx: number, dy: number) => void;
  onResize: (id: string, handle: ResizeHandle, dx: number, dy: number) => void;
  /** Drawn out on empty floor with the room tool. */
  onDrawRoom?: (box: PlanBox, level: number) => void;
  /** Clicked on the party wall the door tool was hovering. */
  onPlaceDoor?: (wall: WallCandidate) => void;
  /** Dropped at a point inside a room, by whichever of the object tools is held. */
  onPlaceObject?: (tool: PlanTool, point: Point, level: number) => void;
  /** Back to the pointer once the tool has been used, so nothing is created twice by accident. */
  onToolUsed?: () => void;
}

/** How far a press has to travel before it counts as a drag rather than a click. */
const PAN_THRESHOLD_PIXELS = 4;

const MINIMUM_ZOOM = 0.4;
const MAXIMUM_ZOOM = 12;

const HANDLES: Array<{ handle: ResizeHandle; fx: number; fy: number }> = [
  { handle: "nw", fx: 0, fy: 0 },
  { handle: "n", fx: 0.5, fy: 0 },
  { handle: "ne", fx: 1, fy: 0 },
  { handle: "e", fx: 1, fy: 0.5 },
  { handle: "se", fx: 1, fy: 1 },
  { handle: "s", fx: 0.5, fy: 1 },
  { handle: "sw", fx: 0, fy: 1 },
  { handle: "w", fx: 0, fy: 0.5 },
];

/**
 * A room's name and floor area, sized so it stays inside the room.
 *
 * One fixed font size is why a 1.8-metre balcony ended up captioned across its neighbours: the
 * label has to answer to the room it belongs to. Below the size where a name would still be
 * legible the caption is dropped rather than drawn over the walls — zooming in brings it back.
 */
function RegionLabel({ region, raised = false }: { region: HomeModel["regions"][number]; raised?: boolean }) {
  const box = boxOf(region.boundary.vertices);
  const width = box.maxX - box.minX;
  const height = box.maxY - box.minY;
  const name = region.regionId.replaceAll("_", " ");
  // 0.55em per glyph is a good enough width estimate for the plan's own typeface.
  const size = Math.min(0.34, Math.max(0.14, height * 0.16), (width * 0.86) / (name.length * 0.55));
  if (size < 0.16) return null;
  const point = center(region.boundary.vertices);
  // The policy puts a room's temperature sensor at its centre, exactly where the caption sits, so
  // with the sensor layer on the caption moves up out of its way rather than through it.
  const y = raised ? point.y - Math.min(height * 0.22, size * 2.2) : point.y;
  return (
    <g className="region-caption" aria-hidden="true">
      <text x={point.x} y={y} className="region-label" style={{ fontSize: `${size}px` }}>{name}</text>
      {height > size * 3 && (
        <text x={point.x} y={y + size * 1.15} className="region-area" style={{ fontSize: `${size * 0.72}px` }}>
          {polygonArea(region.boundary.vertices).toFixed(1)} m²
        </text>
      )}
    </g>
  );
}

/**
 * What each kind of sensor looks like on the plan.
 *
 * Three identical crosshair circles told the reader nothing: a field of thirty nodes read as
 * thirty of the same thing. Each family gets the shape its own diagrams use — motion waves, a reed
 * pair, a thermometer — so a glance over the flat says what is watching what.
 */
function SensorGlyph({ type }: { type: string }) {
  if (type === "contact") {
    return (
      <g className="sensor-glyph">
        <rect x="-.21" y="-.07" width=".17" height=".14" rx=".03" className="glyph-solid" />
        <rect x=".04" y="-.07" width=".17" height=".14" rx=".03" className="glyph-solid" />
      </g>
    );
  }
  if (type === "temperature") {
    return (
      <g className="sensor-glyph">
        <path d="M-.055 -.22 h.11 v.2 h-.11 z" />
        <circle cx="0" cy=".08" r=".13" />
      </g>
    );
  }
  return (
    <g className="sensor-glyph">
      <circle r=".1" className="glyph-solid" />
      <path d="M-.15 -.16 A .22 .22 0 0 0 -.15 .16" />
      <path d="M.15 -.16 A .22 .22 0 0 1 .15 .16" />
      <path d="M-.26 -.28 A .38 .38 0 0 0 -.26 .28" />
      <path d="M.26 -.28 A .38 .38 0 0 1 .26 .28" />
    </g>
  );
}

/** `pir_bathroom_4` reads as `bathroom 4` once you know which layer you are looking at. */
function shortSensorName(sensorId: string): string {
  return sensorId.replace(/^(pir|contact|temperature)_/, "").replaceAll("_", " ");
}

export function PlanCanvas({
  home,
  sensors,
  selectedId,
  onSelect,
  viewport,
  editing,
  showExternalPlaces = false,
  onViewport,
  interactionMode = "interactive",
  tool = "select",
  layer = "home",
  storey: storeyProp,
  onStoreyChange,
}: {
  home: HomeModel;
  sensors?: SensorModel;
  selectedId?: string;
  onSelect?: (id: string) => void;
  viewport?: { zoom: number; x: number; y: number };
  editing?: PlanEditing;
  showExternalPlaces?: boolean;
  onViewport?: (next: { zoom: number; x: number; y: number }) => void;
  interactionMode?: "interactive" | "passive";
  tool?: PlanTool;
  /** Which drawing the pointer edits. The other one is still drawn, and is inert. */
  layer?: "home" | "sensors";
  /** The storey being drawn. Owned by the page when it has tools that create on one. */
  storey?: number;
  onStoreyChange?: (level: number) => void;
}) {
  // A planimetry is a drawing of the house. The supermarket and the bar are regions the simulator
  // needs, not architecture, and at 12 metres away they decide the viewport and leave the flat
  // unreadable in a corner — so the plan is the dwelling unless the researcher asks for the rest.
  const dwelling = dwellingRegionIds(home);
  // Storeys are separate blocks of one coordinate plane, so a two-storey house drawn whole is a
  // diptych: two half-size floors side by side with a gap down the middle. A plan is read one floor
  // at a time, and a house with one floor has nothing to choose.
  const storeys = [...new Set(home.regions.map((region) => region.level ?? 0))].sort((a, b) => a - b);
  // A plan opens on the ground floor when the house has one: the lowest storey is the right
  // fallback only for a house that starts above or below it, not for one with a cellar.
  const ground = storeys.includes(0) ? 0 : (storeys[0] ?? 0);
  const [ownStorey, setOwnStorey] = useState(ground);
  const storey = storeyProp ?? ownStorey;
  const setStorey = onStoreyChange ?? setOwnStorey;
  const shownStorey = storeys.includes(storey) ? storey : ground;
  const levelOf = new Map(home.regions.map((region) => [region.regionId, region.level ?? 0]));
  const isOnStorey = (regionId: string | undefined) =>
    storeys.length < 2 || regionId === undefined || (levelOf.get(regionId) ?? 0) === shownStorey;
  const visible = (regionId: string | undefined) =>
    (showExternalPlaces || regionId === undefined || dwelling.has(regionId)) && isOnStorey(regionId);
  const regionsShown = home.regions.filter((region) => visible(region.regionId));
  const entitiesShown = home.entities.filter((entity) => visible(entity.regionId));
  const shownEntityIds = new Set(entitiesShown.map((entity) => entity.entityId));
  const obstaclesShown = home.obstacles.filter((item) => visible(item.regionId));
  const interactionPointsShown = home.interactionPoints.filter((item) => visible(item.regionId));
  // A transit link to a hidden place has one end nowhere: it would be drawn as a ray into the void.
  const connectionsShown = home.connections.filter(
    (item) => visible(item.regionAId) && visible(item.regionBId),
  );
  const sensorsShown = (sensors?.sensors ?? []).filter((sensor) => {
    const regionIds = (sensor.regionIds as string[] | undefined) ?? [];
    if (regionIds.length > 0) return regionIds.some((regionId) => visible(regionId));
    if (typeof sensor.regionId === "string") return visible(sensor.regionId);
    // A contact sensor lives on a door or a cupboard, so it is shown wherever that thing is.
    return typeof sensor.entityId !== "string" || shownEntityIds.has(sensor.entityId);
  });
  // Walls are cut against every doorway and doorways are found by comparing every pair of rooms,
  // so this is quadratic in the plan — and it used to run on every render, which during a drag is
  // every pointer sample. A furnished flat then dropped frames while you moved a chair.
  const { frontDoor, doorGlyphs, wallPieces } = useMemo(() => {
    const ids = new Set(
      home.regions
        .filter((region) => (showExternalPlaces || dwellingRegionIds(home).has(region.regionId))
          && (storeys.length < 2 || (region.level ?? 0) === shownStorey))
        .map((region) => region.regionId),
    );
    const front = planFrontDoor(home, ids);
    const glyphs = [...planDoors(home, ids), ...(front ? [front] : [])];
    return { frontDoor: front, doorGlyphs: glyphs, wallPieces: cutDoorways(planWalls(home, ids), glyphs) };
  }, [home, showExternalPlaces, shownStorey, storeys.length]);
  const vertices = regionsShown.flatMap((region) => region.boundary.vertices);
  const minX = Math.min(...vertices.map((point) => point.x)) - 2;
  const minY = Math.min(...vertices.map((point) => point.y)) - 2;
  const maxX = Math.max(...vertices.map((point) => point.x)) + 2;
  const maxY = Math.max(...vertices.map((point) => point.y)) + 2;
  // A plan the page does not steer still has to be navigable, so the canvas keeps its own
  // viewport for those cases; when a page owns one — the editor, with its toolbar — that wins.
  const [ownViewport, setOwnViewport] = useState({ zoom: 1, x: 0, y: 0 });
  const view = viewport ?? ownViewport;
  const changeViewport = onViewport ?? setOwnViewport;
  const zoom = Math.max(MINIMUM_ZOOM, Math.min(view.zoom, MAXIMUM_ZOOM));
  const width = (maxX - minX) / zoom;
  const height = (maxY - minY) / zoom;
  const viewX = minX + (maxX - minX - width) / 2 + view.x;
  const viewY = minY + (maxY - minY - height) / 2 + view.y;
  const regions = new Map(home.regions.map((region) => [region.regionId, region]));
  const interactionPoints = new Map(home.interactionPoints.map((point) => [point.interactionPointId, point]));
  // What is wrong with the plan right now, so the objects at fault say so while they are being
  // moved rather than after the publish that rejects them. Only while editing: a published plan
  // has already passed the authoritative gate and marking it up would be noise.
  const problems = useMemo(
    () => new Map(editing ? planProblems(home).map((item) => [item.objectId, item.message]) : []),
    [home, editing],
  );
  // Obstacles carry no type of their own; the generator names them after the entity they belong to.
  const entityByObstacle = new Map(home.entities.map((entity) => [`obstacle_${entity.entityId}`, entity]));
  // The click that finishes a tool gesture must not also select whatever was under it: placing a
  // doorway left the room underneath selected, which is not what you just did. It is the DOM click
  // that has to be stopped, in capture, and only the one belonging to that gesture — swallowing
  // "the next activation" instead would eat an unrelated click that happened to come first.
  const toolJustUsed = useRef(false);
  // Which of the two drawings on this canvas the pointer is allowed to touch. Editing a plan means
  // editing one thing at a time: reaching for a sofa and picking up the detector above it is the
  // kind of mistake that is only noticed after publishing, and the two layers are always drawn
  // together because a sensor is placed *with respect to* the furniture it watches.
  const sensorIds = new Set((sensors?.sensors ?? []).map((item) => item.sensorId));
  const editable = (id: string) => (sensorIds.has(id) ? layer === "sensors" : layer === "home");
  const activate = (id: string) => {
    if (!editable(id)) return;
    onSelect?.(id);
  };
  const keyboard = (event: React.KeyboardEvent<SVGGElement>, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(id);
    }
  };
  const svgRef = useRef<SVGSVGElement>(null);
  // The gesture remembers what it grabbed. Selection is React state and settles a render later, so
  // a drag that read it back would drop its first samples — or move the previous selection.
  const drag = useRef<{ x: number; y: number; id: string; handle?: ResizeHandle } | undefined>(
    undefined,
  );
  // Metres per pixel: what one pixel of pointer travel is worth on the plan at this zoom.
  const scale = () => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return { x: 0, y: 0 };
    return { x: width / box.width, y: height / box.height };
  };
  // The lines the magnet last landed on, drawn while the drag is held so the snap is something you
  // can see happening rather than a number that quietly changed.
  const [guides, setGuides] = useState<{ x?: number; y?: number }>({});
  /** Where a pointer event is on the plan, in metres. Everything a tool does starts here. */
  const planPoint = (event: { clientX: number; clientY: number }): Point => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return { x: 0, y: 0 };
    return {
      x: viewX + ((event.clientX - box.left) / box.width) * width,
      y: viewY + ((event.clientY - box.top) / box.height) * height,
    };
  };
  const beginDrag = (event: ReactPointerEvent, id: string, handle?: ResizeHandle) => {
    if (!editing || tool !== "select") return;
    // A room covers the canvas, so a press on one is far more often an attempt to look around than
    // to rebuild the flat, and an accidental drag is a published wall in the wrong place: rooms
    // still have to be selected before they move. A chair is small and deliberate — you press it
    // because you mean it — so furniture, providers and sensors are dragged in one gesture, which
    // is what "drag and drop" has always meant everywhere else.
    if (!handle && id !== selectedId && home.regions.some((item) => item.regionId === id)) return;
    if (!handle && id !== selectedId) onSelect?.(id);
    event.stopPropagation();
    event.preventDefault();
    drag.current = { x: event.clientX, y: event.clientY, id, handle };
    editing.onDragStart();
    // Capture keeps a fast drag from escaping the shape it grabbed. It is an improvement, not a
    // precondition — and it throws for a pointer the browser has not registered — so the gesture
    // is already live before it is attempted.
    if (typeof event.pointerId === "number") {
      (event.target as Element).setPointerCapture?.(event.pointerId);
    }
  };
  const continueDrag = (event: ReactPointerEvent) => {
    const current = drag.current;
    if (!editing || !current) return;
    const metres = scale();
    const dx = (event.clientX - current.x) * metres.x;
    const dy = (event.clientY - current.y) * metres.y;
    // Deltas are reported against the last sample, so the page applies them to its live draft.
    if (dx === 0 && dy === 0) return;
    drag.current = { ...current, x: event.clientX, y: event.clientY };
    if (current.handle) editing.onResize(current.id, current.handle, dx, dy);
    else {
      // Held near a wall or a neighbour's edge, a piece lands *on* it. Arranging a room by hand
      // otherwise means leaving the wardrobe four centimetres off the wall and out of line with
      // the chest of drawers beside it, and the plan reads as one somebody fought with.
      const pulled = event.altKey ? { dx, dy } : magnet(home, current.id, dx, dy);
      setGuides({ x: pulled.guideX, y: pulled.guideY });
      editing.onMove(current.id, pulled.dx, pulled.dy);
    }
  };
  const endDrag = () => {
    drag.current = undefined;
    pan.current = undefined;
    if (guides.x !== undefined || guides.y !== undefined) setGuides({});
  };
  // What the held tool is about to do, drawn under the pointer before it is done. A room is a
  // rubber band; a doorway is the party wall it would open; the object tools are a mark on the
  // floor. Nothing is created until the gesture finishes, so nothing is created by accident.
  const [draft, setDraft] = useState<PlanBox | undefined>(undefined);
  const [wallUnderPointer, setWallUnderPointer] = useState<WallCandidate | undefined>(undefined);
  const [dropPoint, setDropPoint] = useState<Point | undefined>(undefined);
  const drawing = useRef<Point | undefined>(undefined);
  const toolActive = Boolean(editing) && tool !== "select";

  // A tool gesture is not a text selection. Without this the drag that draws a room instead
  // highlighted every label on the page, and the browser kept the pointer for itself: the room was
  // never drawn because the move and the release never reached the canvas.
  const beginTool = (event: ReactPointerEvent) => {
    if (!toolActive || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    if (typeof event.pointerId === "number") {
      (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    }
    if (tool === "room") {
      const start = planPoint(event);
      drawing.current = start;
      setDraft({ minX: start.x, minY: start.y, maxX: start.x, maxY: start.y });
    }
  };
  const moveTool = (event: ReactPointerEvent) => {
    if (!toolActive) return;
    const point = planPoint(event);
    if (tool === "room") {
      const start = drawing.current;
      if (start) setDraft({ minX: start.x, minY: start.y, maxX: point.x, maxY: point.y });
      return;
    }
    if (tool === "door") {
      setWallUnderPointer(sharedWallAt(home, point, shownStorey));
      return;
    }
    setDropPoint(regionAt(home, point, shownStorey) ? point : undefined);
  };
  const endTool = (event: ReactPointerEvent) => {
    if (!toolActive) return;
    const point = planPoint(event);
    if (tool === "room") {
      const start = drawing.current;
      drawing.current = undefined;
      setDraft(undefined);
      if (!start) return;
      editing?.onDrawRoom?.({ minX: start.x, minY: start.y, maxX: point.x, maxY: point.y }, shownStorey);
      editing?.onToolUsed?.();
      return;
    }
    if (tool === "door") {
      const wall = sharedWallAt(home, point, shownStorey);
      setWallUnderPointer(undefined);
      if (!wall) return;
      editing?.onPlaceDoor?.(wall);
      editing?.onToolUsed?.();
      return;
    }
    setDropPoint(undefined);
    if (!regionAt(home, point, shownStorey)) return;
    editing?.onPlaceObject?.(tool, point, shownStorey);
    editing?.onToolUsed?.();
  };
  const usedTool = () => { toolJustUsed.current = true; };

  // Panning by dragging the background, and zooming with the wheel. The toolbar keeps its buttons
  // for keyboard and pointer-less use, but nobody should have to nudge a plan one metre at a time.
  const pan = useRef<{ x: number; y: number; live: boolean } | undefined>(undefined);
  const beginPan = (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    pan.current = { x: event.clientX, y: event.clientY, live: false };
  };
  const continuePan = (event: ReactPointerEvent) => {
    const current = pan.current;
    if (!current) return;
    // A click is a press that moves a pixel or two on its way up. Panning on the first of those
    // pixels means selecting a sensor also shifts the plan out from under the pointer, so the
    // gesture has to commit to being a drag before the view moves at all.
    if (!current.live) {
      if (Math.hypot(event.clientX - current.x, event.clientY - current.y) < PAN_THRESHOLD_PIXELS) {
        return;
      }
      pan.current = { ...current, live: true };
    }
    const metres = scale();
    const dx = (event.clientX - current.x) * metres.x;
    const dy = (event.clientY - current.y) * metres.y;
    if (dx === 0 && dy === 0) return;
    pan.current = { x: event.clientX, y: event.clientY, live: true };
    // Dragging the plan right moves the window left, which is what makes it feel like paper.
    changeViewport({ zoom, x: view.x - dx, y: view.y - dy });
  };
  // No wheel zoom. The plan is fitted to its own extent when it opens, so the wheel had almost
  // nothing left to do and plenty to get wrong: it swallowed the page scroll over a canvas that
  // fills the view, and a reader scrolling down to the inspector zoomed the drawing instead. The
  // toolbar keeps the buttons, which are also the only zoom a keyboard ever had.
  const draggable = (id: string) =>
    editing && editable(id)
      ? { onPointerDown: (event: ReactPointerEvent) => beginDrag(event, id) }
      : {};
  // Carrying the id alongside the box removes the need to re-check it when wiring the handles.
  const selectedBox = editing && selectedId ? selectionBox(home, sensors, selectedId) : undefined;
  const selection = selectedBox ? { id: selectedId as string, box: selectedBox } : undefined;
  const planInteractions = interactionMode === "interactive" ? {
    onPointerDown: (event: ReactPointerEvent) => {
      // A new gesture: whatever the last one asked to be swallowed no longer applies.
      toolJustUsed.current = false;
      beginTool(event);
      if (!toolActive) beginPan(event);
    },
    onPointerMove: (event: ReactPointerEvent) => {
      moveTool(event);
      if (toolActive) return;
      continueDrag(event);
      continuePan(event);
    },
    onPointerUp: (event: ReactPointerEvent) => { if (toolActive) usedTool(); endTool(event); endDrag(); },
    onClickCapture: (event: React.MouseEvent<SVGSVGElement>) => {
      if (!toolJustUsed.current) return;
      toolJustUsed.current = false;
      event.stopPropagation();
    },
    onPointerCancel: () => { drawing.current = undefined; setDraft(undefined); endDrag(); },
    onPointerLeave: () => { setDropPoint(undefined); setWallUnderPointer(undefined); endDrag(); },
  } : {};
  return (
    <div className="plan-canvas-wrap">
      <svg
        ref={svgRef}
        className={`plan-canvas ${editing ? "is-editable" : ""} ${sensors ? "shows-sensors" : ""}`}
        data-tool={tool}
        viewBox={`${viewX} ${viewY} ${width} ${height}`}
        role="group"
        aria-label={`Plan of ${home.homeId}, ${regionsShown.length} regions and ${sensorsShown.length} sensors`}
        data-interaction-mode={interactionMode}
        {...planInteractions}
      >
        <defs>
          <pattern id="grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" /></pattern>
          <pattern id="obstacle" width=".55" height=".55" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2=".55" /></pattern>
          <FurnitureSymbols />
          <CustomFurnitureSymbols />
        </defs>
        <rect x={minX} y={minY} width={maxX - minX} height={maxY - minY} fill="url(#grid)" className="plan-grid" />
        {/* Editing the sensors means seeing the furniture they watch, so the house stays drawn
            behind them — greyed back, and deaf to the pointer. Editing the house is the other way
            round: the detectors are simply not part of that drawing and are left out of it. */}
        <g className={`plan-layer${layer === "sensors" ? " is-backdrop" : ""}`}>
        <g role="group" aria-label="Regions">
          {regionsShown.map((region) => (
            <g
              key={region.regionId}
              role="button"
              tabIndex={0}
              aria-label={`${region.kind} ${region.regionId}${
                problems.has(region.regionId) ? `, ${problems.get(region.regionId)}` : ""
              }`}
              onClick={() => activate(region.regionId)}
              onKeyDown={(event) => keyboard(event, region.regionId)}
              data-region-id={region.regionId}
              className={[
                selectedId === region.regionId ? "is-selected" : "",
                problems.has(region.regionId) ? "has-problem" : "",
              ].filter(Boolean).join(" ") || undefined}
              {...draggable(region.regionId)}
            >
              <polygon points={polygonPoints(region.boundary.vertices)} className={`region region-${region.kind}`} />
              <RegionLabel region={region} raised={!!sensors} />
            </g>
          ))}
        </g>
        <g role="group" aria-label="Walls" className="walls">
          {wallPieces.map((piece, index) => (
            <line
              key={`wall-${index}`}
              x1={piece.x1}
              y1={piece.y1}
              x2={piece.x2}
              y2={piece.y2}
              className={piece.exterior ? "wall wall-exterior" : "wall wall-partition"}
            />
          ))}
        </g>
        <g role="group" aria-label="Doors" className="doors">
          {doorGlyphs.map((door) => (
            <g key={door.connectionId} role="group" aria-label={`${door.kind} ${door.connectionId}`} className={`door door-${door.kind}`}>
              {/* A passage is an opening with no leaf; a doorway shows which way it swings. */}
              {door.kind !== "passage" && <>
                <path d={door.arc} className="door-swing" />
                <line x1={door.x1} y1={door.y1} x2={door.leafX} y2={door.leafY} className="door-leaf" />
              </>}
              <line x1={door.x1} y1={door.y1} x2={door.x2} y2={door.y2} className="door-threshold" />
              {/* The way out is the one opening a reader looks for first, so it says so. */}
              {door.kind === "entrance" && (
                <text
                  x={(door.x1 + door.x2) / 2 + (door.leafX - door.x1) * 0.55}
                  y={(door.y1 + door.y2) / 2 + (door.leafY - door.y1) * 0.55}
                  className="door-caption"
                >
                  Front door
                </text>
              )}
            </g>
          ))}
        </g>
        {showExternalPlaces && <g role="group" aria-label="Connections" className="connections">
          {connectionsShown.filter((item) => item.kind === "transit").map((connection) => {
            const a = connection.portalA ?? center(regions.get(connection.regionAId)?.boundary.vertices ?? []);
            const b = connection.portalB ?? center(regions.get(connection.regionBId)?.boundary.vertices ?? []);
            if (!a || !b) return null;
            return <line key={connection.connectionId} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="connection connection-transit" />;
          })}
        </g>}
        <g role="group" aria-label="Obstacles">
          {obstaclesShown.map((obstacle) => {
            const entity = entityByObstacle.get(obstacle.obstacleId);
            const symbol = furnitureSymbol(entity?.entityType) ?? structuralSymbol(obstacle.obstacleId);
            const box = bounds(obstacle.boundary.vertices);
            return (
              <g
                key={obstacle.obstacleId}
                role="button"
                tabIndex={0}
                aria-label={`Obstacle ${obstacle.obstacleId}${entity ? ` (${entity.entityType})` : ""}${
                  problems.has(obstacle.obstacleId) ? `, ${problems.get(obstacle.obstacleId)}` : ""
                }`}
                className={[
                  selectedId === obstacle.obstacleId ? "is-selected" : "",
                  problems.has(obstacle.obstacleId) ? "has-problem" : "",
                ].filter(Boolean).join(" ")}
                onClick={() => activate(obstacle.obstacleId)}
                onKeyDown={(event) => keyboard(event, obstacle.obstacleId)}
                {...draggable(obstacle.obstacleId)}
              >
                <polygon points={polygonPoints(obstacle.boundary.vertices)} className="obstacle" />
                {symbol && box && (
                  <FurnitureGlyph
                    symbol={symbol}
                    box={box}
                    orientationDegrees={obstacle.orientationDegrees}
                    className="furniture-glyph"
                  />
                )}
              </g>
            );
          })}
        </g>
        {!sensors && <g role="group" aria-label="Interaction points">
          {interactionPointsShown.map((point) => (
            <circle key={point.interactionPointId} cx={point.position.x} cy={point.position.y} r=".13" className="interaction-point" />
          ))}
        </g>}
        <g role="group" aria-label="Capability providers">
          {entitiesShown.map((entity) => {
            const point = interactionPoints.get(entity.interactionPointId);
            if (!point) return null;
            // The per-region fallback provider is an implementation detail with no footprint; one
            // per room, each captioned, buried the plan under its own labels.
            const isService = entity.entityType === SERVICE_ENTITY_TYPE;
            return (
              <g
                key={entity.entityId}
                role="button"
                tabIndex={0}
                aria-label={`${entity.entityType} ${entity.entityId}`}
                transform={`translate(${point.position.x} ${point.position.y})`}
                className={`entity-node ${isService ? "is-service" : ""} ${selectedId === entity.entityId ? "is-selected" : ""}`}
                onClick={() => activate(entity.entityId)}
                onKeyDown={(event) => keyboard(event, entity.entityId)}
                {...draggable(entity.entityId)}
              >
                {/* A provider is drawn where the resident STANDS to use the thing, not where the
                    thing is — its footprint is the hatched box. Showing the approach radius on
                    hover and selection says so without a caption nobody would read. */}
                {!isService && <circle r={point.approachRadiusMeters} className="approach-radius" />}
                <circle r={isService ? ".1" : ".18"} />
                {!isService && !sensors && <path d="M-.08 0h.16M0-.08v.16" />}
                <text x=".28" y=".1">{entity.entityType.replaceAll("_", " ")}</text>
              </g>
            );
          })}
        </g>
        </g>
        {sensors && <g className="plan-layer" role="group" aria-label="Sensors">
          {sensorsShown.map((sensor) => {
            const coverage = sensor.sensorType === "pir" ? (sensor.coverage as Polygon | undefined) : undefined;
            const isSelected = selectedId === sensor.sensorId;
            return (
              <g key={sensor.sensorId}>
                {/* Six overlapping translucent rectangles say nothing about any one of them. The
                    field a researcher is reading is the one they picked, so only that is drawn. */}
                {coverage && isSelected && (
                  <polygon points={polygonPoints(coverage.vertices)} className="sensor-coverage" />
                )}
                <g
                  role="button"
                  tabIndex={0}
                  aria-label={`${sensor.sensorType} sensor ${sensor.sensorId}`}
                  transform={`translate(${sensor.position.x} ${sensor.position.y})`}
                  className={`sensor-node sensor-${sensor.sensorType}${isSelected ? " is-selected" : ""}`}
                  onClick={() => activate(sensor.sensorId)}
                  onKeyDown={(event) => keyboard(event, sensor.sensorId)}
                  {...draggable(sensor.sensorId)}
                >
                  <SensorGlyph type={sensor.sensorType} />
                  <text x=".3" y=".1">{shortSensorName(sensor.sensorId)}</text>
                </g>
              </g>
            );
          })}
        </g>}
        {selection && <g role="group" aria-label="Resize handles" className="resize-handles">
          <rect
            x={selection.box.minX}
            y={selection.box.minY}
            width={selection.box.maxX - selection.box.minX}
            height={selection.box.maxY - selection.box.minY}
            className="selection-outline"
          />
          {HANDLES.map(({ handle, fx, fy }) => {
            // Handles keep a constant size on screen, so they stay grabbable at any zoom.
            const size = Math.min(width, height) / 45;
            return (
              <rect
                key={handle}
                className={`resize-handle handle-${handle}`}
                role="button"
                tabIndex={-1}
                aria-label={`Resize ${selection.id} ${handle}`}
                x={selection.box.minX + (selection.box.maxX - selection.box.minX) * fx - size / 2}
                y={selection.box.minY + (selection.box.maxY - selection.box.minY) * fy - size / 2}
                width={size}
                height={size}
                onPointerDown={(event) => beginDrag(event, selection.id, handle)}
              />
            );
          })}
        </g>}
        {/* What the pointer is about to do, and what it just lined up with. Both are drawn last so
            they sit over the plan, and neither takes a click. */}
        <g className="plan-overlay" aria-hidden="true">
          {guides.x !== undefined && <line className="align-guide" x1={guides.x} y1={minY} x2={guides.x} y2={maxY} />}
          {guides.y !== undefined && <line className="align-guide" x1={minX} y1={guides.y} x2={maxX} y2={guides.y} />}
          {draft && (
            <rect
              className="draw-draft"
              x={Math.min(draft.minX, draft.maxX)}
              y={Math.min(draft.minY, draft.maxY)}
              width={Math.abs(draft.maxX - draft.minX)}
              height={Math.abs(draft.maxY - draft.minY)}
            />
          )}
          {draft && (
            <text
              className="draw-measure"
              x={(draft.minX + draft.maxX) / 2}
              y={(draft.minY + draft.maxY) / 2}
            >
              {`${Math.abs(draft.maxX - draft.minX).toFixed(1)} × ${Math.abs(draft.maxY - draft.minY).toFixed(1)} m`}
            </text>
          )}
          {wallUnderPointer && (
            <line
              className="door-preview"
              x1={wallUnderPointer.vertical ? wallUnderPointer.x : wallUnderPointer.x - 0.5}
              y1={wallUnderPointer.vertical ? wallUnderPointer.y - 0.5 : wallUnderPointer.y}
              x2={wallUnderPointer.vertical ? wallUnderPointer.x : wallUnderPointer.x + 0.5}
              y2={wallUnderPointer.vertical ? wallUnderPointer.y + 0.5 : wallUnderPointer.y}
            />
          )}
          {dropPoint && <circle className="drop-mark" cx={dropPoint.x} cy={dropPoint.y} r=".35" />}
        </g>
      </svg>
      {storeys.length > 1 && (
        <div className="plan-storeys" role="group" aria-label="Storey">
          {storeys.map((level) => (
            <button
              key={level}
              type="button"
              className={level === shownStorey ? "is-current" : undefined}
              aria-pressed={level === shownStorey}
              onClick={() => setStorey(level)}
            >
              {storeyLabel(level)}
            </button>
          ))}
        </div>
      )}
      <div className="plan-legend" aria-label="Plan legend">
        <span><i className="legend-room" /> Room</span>
        <span><i className="legend-obstacle" /> Obstacle</span>
        <span><i className="legend-provider" /> Use point</span>
        {sensors && <span><i className="legend-sensor" /> Sensor</span>}
        {frontDoor && <span><i className="legend-entrance" /> Front door</span>}
      </div>
    </div>
  );
}

/**
 * The area a resize gesture acts on, or nothing for a selection that has no extent.
 *
 * A PIR is resized by its coverage — the area is the thing you are shaping — while a provider is
 * a point on the plan and can only be dragged.
 */
function selectionBox(
  home: HomeModel,
  sensors: SensorModel | undefined,
  selectedId: string,
): { minX: number; minY: number; maxX: number; maxY: number } | undefined {
  const sensor = sensors?.sensors.find((item) => item.sensorId === selectedId);
  const coverage = sensor?.sensorType === "pir" ? (sensor.coverage as Polygon | undefined) : undefined;
  if (coverage) return boxOf(coverage.vertices);
  if (sensor) return undefined;
  const region = home.regions.find((item) => item.regionId === selectedId);
  if (region) return boxOf(region.boundary.vertices);
  const obstacle = home.obstacles.find((item) => item.obstacleId === selectedId);
  return obstacle ? boxOf(obstacle.boundary.vertices) : undefined;
}

export function RunLink({ id, children }: PropsWithChildren<{ id: string }>) {
  return <NavLink className="row-link" to={`/simulations/${id}`}>{children}<ChevronRight size={17} /></NavLink>;
}
