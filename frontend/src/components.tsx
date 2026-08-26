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
import { useEffect, useRef, useState } from "react";
import type { FormEvent, PointerEvent as ReactPointerEvent, PropsWithChildren, ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  boxOf,
  cutDoorways,
  dwellingRegionIds,
  planDoors,
  planFrontDoor,
  planWalls,
  polygonArea,
} from "./editor";
import type { ResizeHandle } from "./editor";
import { furnitureSymbol } from "./furniture";
import { FurnitureSymbols } from "./furniture-symbols";
import type { HomeModel, JobStatus, Point, Polygon, SensorModel } from "./types";

const nav = [
  { to: "/", label: "Dashboard", icon: Activity },
  { to: "/generate", label: "Generate", icon: Sparkles },
  { to: "/homes", label: "Homes", icon: Home },
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
export interface PlanEditing {
  onDragStart: () => void;
  onMove: (id: string, dx: number, dy: number) => void;
  onResize: (id: string, handle: ResizeHandle, dx: number, dy: number) => void;
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
}) {
  // A planimetry is a drawing of the house. The supermarket and the bar are regions the simulator
  // needs, not architecture, and at 12 metres away they decide the viewport and leave the flat
  // unreadable in a corner — so the plan is the dwelling unless the researcher asks for the rest.
  const dwelling = dwellingRegionIds(home);
  const visible = (regionId: string | undefined) =>
    showExternalPlaces || regionId === undefined || dwelling.has(regionId);
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
  const visibleIds = new Set(regionsShown.map((region) => region.regionId));
  const frontDoor = planFrontDoor(home, visibleIds);
  const doorGlyphs = [...planDoors(home, visibleIds), ...(frontDoor ? [frontDoor] : [])];
  const wallPieces = cutDoorways(planWalls(home, visibleIds), doorGlyphs);
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
  // Obstacles carry no type of their own; the generator names them after the entity they belong to.
  const entityByObstacle = new Map(home.entities.map((entity) => [`obstacle_${entity.entityId}`, entity]));
  const activate = (id: string) => onSelect?.(id);
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
  const beginDrag = (event: ReactPointerEvent, id: string, handle?: ResizeHandle) => {
    if (!editing) return;
    // Only what is already selected moves. On a plan whose rooms cover the whole canvas a drag is
    // far more often an attempt to look around than to rebuild the flat, and an accidental one is
    // a published wall in the wrong place. So the first gesture pans — the event keeps bubbling to
    // the canvas — and the click that ends it selects; the next drag moves what you chose.
    if (!handle && id !== selectedId) return;
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
    else editing.onMove(current.id, dx, dy);
  };
  const endDrag = () => {
    drag.current = undefined;
    pan.current = undefined;
  };
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
  const wheelZoom = (event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return;
    const next = Math.max(
      MINIMUM_ZOOM,
      Math.min(zoom * Math.exp(-event.deltaY * 0.0015), MAXIMUM_ZOOM),
    );
    if (next === zoom) return;
    // Keep the point under the cursor still: zoom towards what the reader is looking at.
    const fx = (event.clientX - box.left) / box.width;
    const fy = (event.clientY - box.top) / box.height;
    const world = { x: viewX + fx * width, y: viewY + fy * height };
    const nextWidth = (maxX - minX) / next;
    const nextHeight = (maxY - minY) / next;
    changeViewport({
      zoom: next,
      x: world.x - fx * nextWidth - minX - (maxX - minX - nextWidth) / 2,
      y: world.y - fy * nextHeight - minY - (maxY - minY - nextHeight) / 2,
    });
  };
  useEffect(() => {
    if (interactionMode !== "interactive") return;
    const svg = svgRef.current;
    if (!svg) return;
    // React registers wheel listeners as passive in this runtime, so retain the browser-level
    // cancellation that keeps interactive canvas zoom from scrolling the containing page.
    const preventPageScroll = (event: WheelEvent) => event.preventDefault();
    svg.addEventListener("wheel", preventPageScroll, { passive: false });
    return () => svg.removeEventListener("wheel", preventPageScroll);
  }, [interactionMode]);
  const draggable = (id: string) =>
    editing ? { onPointerDown: (event: ReactPointerEvent) => beginDrag(event, id) } : {};
  // Carrying the id alongside the box removes the need to re-check it when wiring the handles.
  const selectedBox = editing && selectedId ? selectionBox(home, sensors, selectedId) : undefined;
  const selection = selectedBox ? { id: selectedId as string, box: selectedBox } : undefined;
  const planInteractions = interactionMode === "interactive" ? {
    onPointerDown: beginPan,
    onPointerMove: (event: ReactPointerEvent) => { continueDrag(event); continuePan(event); },
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onPointerLeave: endDrag,
    onWheel: wheelZoom,
  } : {};
  return (
    <div className="plan-canvas-wrap">
      <svg
        ref={svgRef}
        className={`plan-canvas ${editing ? "is-editable" : ""} ${sensors ? "shows-sensors" : ""}`}
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
        </defs>
        <rect x={minX} y={minY} width={maxX - minX} height={maxY - minY} fill="url(#grid)" className="plan-grid" />
        <g role="group" aria-label="Regions">
          {regionsShown.map((region) => (
            <g
              key={region.regionId}
              role="button"
              tabIndex={0}
              aria-label={`${region.kind} ${region.regionId}`}
              onClick={() => activate(region.regionId)}
              onKeyDown={(event) => keyboard(event, region.regionId)}
              data-region-id={region.regionId}
              className={selectedId === region.regionId ? "is-selected" : undefined}
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
            const symbol = furnitureSymbol(entity?.entityType);
            const box = bounds(obstacle.boundary.vertices);
            return (
              <g
                key={obstacle.obstacleId}
                role="button"
                tabIndex={0}
                aria-label={`Obstacle ${obstacle.obstacleId}${entity ? ` (${entity.entityType})` : ""}`}
                className={selectedId === obstacle.obstacleId ? "is-selected" : ""}
                onClick={() => activate(obstacle.obstacleId)}
                onKeyDown={(event) => keyboard(event, obstacle.obstacleId)}
                {...draggable(obstacle.obstacleId)}
              >
                <polygon points={polygonPoints(obstacle.boundary.vertices)} className="obstacle" />
                {symbol && box && (
                  <use
                    href={`#furn-${symbol}`}
                    x={box.minX}
                    y={box.minY}
                    width={box.maxX - box.minX}
                    height={box.maxY - box.minY}
                    className="furniture-glyph"
                    preserveAspectRatio="xMidYMid meet"
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
        {sensors && <g role="group" aria-label="Sensors">
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
      </svg>
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
