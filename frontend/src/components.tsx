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
  Search,
  Sun,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, PropsWithChildren, ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import type { HomeModel, JobStatus, Point, Polygon, SensorModel, TimelineEvent } from "./types";

const nav = [
  { to: "/", label: "Dashboard", icon: Activity },
  { to: "/homes", label: "Homes", icon: Home },
  { to: "/residents", label: "Residents", icon: Users },
  { to: "/simulations", label: "Simulations", icon: FlaskConical },
  { to: "/exports", label: "Exports", icon: Download },
  { to: "/help", label: "Guide", icon: BookOpen },
];

interface ShellProps extends PropsWithChildren {
  workspaceName?: string;
  theme: "light" | "dark";
  onTheme: () => void;
  navOpen: boolean;
  onNav: () => void;
}

export function Shell({
  children,
  workspaceName = "Local workspace",
  theme,
  onTheme,
  navOpen,
  onNav,
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
    <div className="app-shell" data-theme={theme}>
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
        </div>
        <nav>
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => navOpen && onNav()}>
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

function center(points: Point[]): Point {
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / Math.max(points.length, 1),
    y: points.reduce((sum, point) => sum + point.y, 0) / Math.max(points.length, 1),
  };
}

export function PlanCanvas({
  home,
  sensors,
  selectedId,
  onSelect,
  activeMovement,
  viewport,
}: {
  home: HomeModel;
  sensors?: SensorModel;
  selectedId?: string;
  onSelect?: (id: string) => void;
  activeMovement?: TimelineEvent;
  viewport?: { zoom: number; x: number; y: number };
}) {
  const vertices = home.regions.flatMap((region) => region.boundary.vertices);
  const minX = Math.min(...vertices.map((point) => point.x)) - 2;
  const minY = Math.min(...vertices.map((point) => point.y)) - 2;
  const maxX = Math.max(...vertices.map((point) => point.x)) + 2;
  const maxY = Math.max(...vertices.map((point) => point.y)) + 2;
  const zoom = Math.max(0.5, Math.min(viewport?.zoom ?? 1, 4));
  const width = (maxX - minX) / zoom;
  const height = (maxY - minY) / zoom;
  const viewX = minX + (maxX - minX - width) / 2 + (viewport?.x ?? 0);
  const viewY = minY + (maxY - minY - height) / 2 + (viewport?.y ?? 0);
  const regions = new Map(home.regions.map((region) => [region.regionId, region]));
  const interactionPoints = new Map(home.interactionPoints.map((point) => [point.interactionPointId, point]));
  const activate = (id: string) => onSelect?.(id);
  const keyboard = (event: React.KeyboardEvent<SVGGElement>, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(id);
    }
  };
  return (
    <div className="plan-canvas-wrap">
      <svg
        className="plan-canvas"
        viewBox={`${viewX} ${viewY} ${width} ${height}`}
        role="img"
        aria-label={`Plan of ${home.homeId}, ${home.regions.length} regions and ${sensors?.sensors.length ?? 0} sensors`}
      >
        <defs>
          <pattern id="grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" /></pattern>
          <pattern id="obstacle" width=".55" height=".55" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2=".55" /></pattern>
        </defs>
        <rect x={minX} y={minY} width={maxX - minX} height={maxY - minY} fill="url(#grid)" className="plan-grid" />
        <g aria-label="Regions">
          {home.regions.map((region) => (
            <g
              key={region.regionId}
              role="button"
              tabIndex={0}
              aria-label={`${region.kind} ${region.regionId}`}
              onClick={() => activate(region.regionId)}
              onKeyDown={(event) => keyboard(event, region.regionId)}
              className={selectedId === region.regionId ? "is-selected" : ""}
            >
              <polygon points={polygonPoints(region.boundary.vertices)} className={`region region-${region.kind}`} />
              <text {...center(region.boundary.vertices)} className="region-label">{region.regionId.replaceAll("_", " ")}</text>
            </g>
          ))}
        </g>
        <g aria-label="Connections" className="connections">
          {home.connections.map((connection) => {
            const from = regions.get(connection.regionAId);
            const to = regions.get(connection.regionBId);
            if (!from || !to) return null;
            const a = center(from.boundary.vertices);
            const b = center(to.boundary.vertices);
            return <line key={connection.connectionId} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`connection connection-${connection.kind}`} />;
          })}
        </g>
        <g aria-label="Obstacles">
          {home.obstacles.map((obstacle) => (
            <polygon
              key={obstacle.obstacleId}
              role="button"
              tabIndex={0}
              aria-label={`Obstacle ${obstacle.obstacleId}`}
              points={polygonPoints(obstacle.boundary.vertices)}
              className={`obstacle ${selectedId === obstacle.obstacleId ? "is-selected" : ""}`}
              onClick={() => activate(obstacle.obstacleId)}
              onKeyDown={(event) => keyboard(event, obstacle.obstacleId)}
            />
          ))}
        </g>
        <g aria-label="Interaction points">
          {home.interactionPoints.map((point) => (
            <circle key={point.interactionPointId} cx={point.position.x} cy={point.position.y} r=".13" className="interaction-point" />
          ))}
        </g>
        <g aria-label="Capability providers">
          {home.entities.map((entity) => {
            const point = interactionPoints.get(entity.interactionPointId);
            if (!point) return null;
            return (
              <g
                key={entity.entityId}
                role="button"
                tabIndex={0}
                aria-label={`${entity.entityType} ${entity.entityId}`}
                transform={`translate(${point.position.x} ${point.position.y})`}
                className={`entity-node ${selectedId === entity.entityId ? "is-selected" : ""}`}
                onClick={() => activate(entity.entityId)}
                onKeyDown={(event) => keyboard(event, entity.entityId)}
              >
                <circle r=".34" />
                <path d="M-.14 0h.28M0-.14v.28" />
                <text x=".45" y=".12">{entity.entityType.replaceAll("_", " ")}</text>
              </g>
            );
          })}
        </g>
        {sensors && <g aria-label="Sensors">
          {sensors.sensors.map((sensor) => {
            const coverage = sensor.sensorType === "pir" ? (sensor.coverage as Polygon | undefined) : undefined;
            return (
              <g key={sensor.sensorId}>
                {coverage && <polygon points={polygonPoints(coverage.vertices)} className="sensor-coverage" />}
                <g
                  role="button"
                  tabIndex={0}
                  aria-label={`${sensor.sensorType} sensor ${sensor.sensorId}`}
                  transform={`translate(${sensor.position.x} ${sensor.position.y})`}
                  className={`sensor-node sensor-${sensor.sensorType} ${selectedId === sensor.sensorId ? "is-selected" : ""}`}
                  onClick={() => activate(sensor.sensorId)}
                  onKeyDown={(event) => keyboard(event, sensor.sensorId)}
                >
                  <circle r=".25" />
                  <path d="M-.11 0h.22M0-.11v.22" />
                  <text x=".34" y=".11">{sensor.sensorId}</text>
                </g>
              </g>
            );
          })}
        </g>}
        {activeMovement?.waypoints && <g aria-label="Active trajectory" className="active-trajectory">
          <polyline points={polygonPoints(activeMovement.waypoints.map((item) => item.position))} />
          {activeMovement.waypoints.map((item, index) => <circle key={`${item.at}-${index}`} cx={item.position.x} cy={item.position.y} r=".12" />)}
        </g>}
      </svg>
      <div className="plan-legend" aria-label="Plan legend">
        <span><i className="legend-room" /> Room</span>
        <span><i className="legend-obstacle" /> Obstacle</span>
        <span><i className="legend-provider" /> Provider</span>
        {sensors && <span><i className="legend-sensor" /> Sensor</span>}
      </div>
    </div>
  );
}

export function RunLink({ id, children }: PropsWithChildren<{ id: string }>) {
  return <NavLink className="row-link" to={`/simulations/${id}`}>{children}<ChevronRight size={17} /></NavLink>;
}
