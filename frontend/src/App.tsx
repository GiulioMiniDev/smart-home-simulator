import {
  Activity,
  AlertCircle,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronDown,
  CircleDot,
  Clock3,
  Copy,
  Download,
  FileJson,
  Filter,
  FolderOpen,
  Gauge,
  Home as HomeIcon,
  ListTree,
  Pause,
  Play,
  Plus,
  Radar,
  RotateCcw,
  RotateCw,
  Route as RouteIcon,
  Save,
  ShieldCheck,
  Square,
  Trash2,
  Upload,
  UserRound,
  Users,
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, download, eventSourceUrl } from "./api";
import {
  Breadcrumbs,
  EmptyState,
  ErrorPanel,
  Metric,
  PageHeader,
  PlanCanvas,
  ProgressBar,
  RunLink,
  Shell,
  Skeleton,
  StatusBadge,
} from "./components";
import { useResource, useStoredState } from "./hooks";
import { addObstacle, addRoom, addSensor, removeSelection } from "./editor";
import { authoringPrompts } from "./prompts";
import type {
  DiaryEntry,
  ExportManifest,
  HomeDetail,
  HomeModel,
  HomeSummary,
  JobEvent,
  JobRecord,
  Observation,
  Overview,
  SensorModel,
  TimelineEvent,
} from "./types";

const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);

function formatDate(value?: string): string {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function duration(start: string, end: string): string {
  const minutes = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

async function readJson(file: File): Promise<Record<string, unknown>> {
  if (file.size > 50 * 1024 * 1024) throw new Error("The selected JSON file is larger than 50 MiB");
  let value: unknown;
  try {
    value = JSON.parse(await file.text()) as unknown;
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : String(reason);
    throw new Error(`“${file.name}” is not valid JSON: ${detail}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`“${file.name}” must contain one JSON object`);
  }
  return value as Record<string, unknown>;
}

type ImportIssue = { code?: string; path?: string; message: string };

function summarizeIssues(issues: ImportIssue[]): string {
  const unique = new Map<string, ImportIssue>();
  for (const issue of issues) {
    unique.set(`${issue.code ?? ""}|${issue.path ?? ""}|${issue.message}`, issue);
  }
  return [...unique.values()].map((issue) => {
    const context = [issue.code, issue.path].filter(Boolean).join(" · ");
    return context ? `${issue.message} (${context})` : issue.message;
  }).join(" · ");
}

export function App() {
  const overview = useResource<Overview>("/overview");
  const [theme, setTheme] = useStoredState<"light" | "dark">("habitat-theme", "light");
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    void api<{ value?: unknown }>("/settings/theme")
      .then((setting) => {
        if (setting.value === "light" || setting.value === "dark") setTheme(setting.value);
      })
      .catch(() => undefined);
  }, [setTheme]);
  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    void api("/settings/theme", {
      method: "PUT",
      body: JSON.stringify({ value: next }),
    }).catch(() => undefined);
  };
  return (
    <Shell
      workspaceName={overview.data?.workspace.name}
      theme={theme}
      onTheme={toggleTheme}
      navOpen={navOpen}
      onNav={() => setNavOpen(!navOpen)}
    >
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/homes" element={<HomesPage />} />
        <Route path="/homes/:homeId" element={<HomePage />} />
        <Route path="/residents" element={<ResidentsPage />} />
        <Route path="/simulations" element={<SimulationsPage />} />
        <Route path="/simulations/:runId" element={<RunPage />} />
        <Route path="/exports" element={<ExportsPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Shell>
  );
}

function Dashboard() {
  const resource = useResource<Overview>("/overview");
  if (resource.loading) return <div className="page"><Skeleton lines={7} /></div>;
  if (resource.error || !resource.data) return <div className="page"><ErrorPanel message={resource.error?.message ?? "Unknown error"} onRetry={() => void resource.reload()} /></div>;
  const { workspace, homes, jobs } = resource.data;
  const active = jobs.filter((job) => job.status === "queued" || job.status === "running");
  return (
    <div className="page dashboard-page">
      <PageHeader
        eyebrow="Local research workspace"
        title="Good evidence starts with inspectable inputs."
        description="Build the home, execute behavior, then follow each sensor observation back to its simulated cause."
        actions={<Link className="button primary" to="/homes"><Plus size={17} /> New experiment</Link>}
      />
      {workspace.diagnosticMode && (
        <div className="diagnostic-banner" role="alert">
          <ShieldCheck size={20} />
          <div><strong>Workspace opened in diagnostic mode</strong><p>One or more artifact files did not match the persistent catalogue. New publication is paused until integrity is restored.</p></div>
        </div>
      )}
      <section className="metrics-strip" aria-label="Workspace summary">
        <Metric label="Homes" value={workspace.homeCount} detail={`${workspace.residentCount} residents`} />
        <Metric label="Verified runs" value={workspace.runCount} detail={`${active.length} active`} />
        <Metric label="Artifacts" value={workspace.artifactCount} detail="Digest catalogued" />
        <Metric label="Workspace schema" value={workspace.formatVersion} detail="Local SQLite + files" />
      </section>
      <div className="dashboard-grid">
        <section className="surface recent-homes">
          <div className="section-heading"><div><p className="eyebrow">Environments</p><h2>Continue where you left off</h2></div><Link to="/homes">View all</Link></div>
          {homes.length ? (
            <div className="object-list">
              {homes.slice(0, 5).map((home) => (
                <Link className="object-row" to={`/homes/${home.homeId}`} key={home.homeId}>
                  <span className="object-symbol"><HomeIcon size={19} /></span>
                  <span><strong>{home.name}</strong><small>{home.description || "Executable home environment"}</small></span>
                  <span className="row-meta"><b>{home.residentCount}</b> residents</span>
                  <span className="row-meta"><b>{home.runCount}</b> runs</span>
                  <span className="row-arrow">Open</span>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title="No environment yet" icon={<HomeIcon size={25} />} action={<Link to="/homes" className="button primary"><Plus size={16} /> Create your first home</Link>}>
              <p>Import accepted M3 authoring, then let the deterministic policies produce an executable home and sensor field.</p>
            </EmptyState>
          )}
        </section>
        <aside className="surface run-monitor">
          <div className="section-heading"><div><p className="eyebrow">Local engine</p><h2>Run monitor</h2></div><Gauge size={20} /></div>
          {active.length ? active.map((job) => (
            <div className="monitor-job" key={job.jobId}>
              <div><StatusBadge status={job.status} /><time>{formatDate(job.requestedAt)}</time></div>
              <strong>{job.progress.message}</strong>
              <ProgressBar value={job.progress.percent} label={job.progress.phase} />
              <RunLink id={job.jobId}>Inspect live run</RunLink>
            </div>
          )) : (
            <div className="quiet-state"><CircleDot size={24} /><strong>No active work</strong><p>Workers are ready. Runs continue if this page is closed.</p></div>
          )}
        </aside>
      </div>
      <section className="quick-path" aria-labelledby="quick-path-title">
        <div><p className="eyebrow">First simulation</p><h2 id="quick-path-title">One traceable path, no hidden repair</h2></div>
        <ol>
          <li><span>01</span><strong>Import behavior</strong><small>Scenario and personal process package pass the frozen gates.</small></li>
          <li><span>02</span><strong>Review the home</strong><small>Rooms, capabilities and sensors remain explicit and editable.</small></li>
          <li><span>03</span><strong>Inspect evidence</strong><small>Replay ground truth beside the observable device stream.</small></li>
        </ol>
      </section>
    </div>
  );
}

function HomesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("query") ?? "";
  const resource = useResource<HomeSummary[]>(`/homes${query ? `?query=${encodeURIComponent(query)}` : ""}`);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string>();
  const navigate = useNavigate();
  const create = async () => {
    setError(undefined);
    try {
      const home = await api<HomeSummary>("/homes", { method: "POST", body: JSON.stringify({ name, description }) });
      navigate(`/homes/${home.homeId}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <div className="page">
      <PageHeader eyebrow="Workspace catalogue" title="Homes" description="Each home keeps its residents, revisions, bundles, runs and exports together." actions={<><label className="catalogue-filter"><span className="sr-only">Filter homes</span><Filter size={16} aria-hidden="true" /><input value={query} onChange={(event) => setSearchParams(event.target.value ? { query: event.target.value } : {})} placeholder="Filter homes" /></label><button className="button primary" onClick={() => setCreating(!creating)}><Plus size={17} /> New home</button></>} />
      {creating && (
        <section className="inline-creator" aria-labelledby="new-home-title">
          <div><p className="eyebrow">New environment</p><h2 id="new-home-title">Name the research context</h2><p>The physical model can be generated after accepted M3 authoring is attached.</p></div>
          <div className="form-stack">
            <label><span>Name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Monteverde apartment" /></label>
            <label><span>Description</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Purpose, cohort or experimental context" /></label>
            {error && <p className="field-error" role="alert">{error}</p>}
            <div className="button-row"><button className="button secondary" onClick={() => setCreating(false)}>Cancel</button><button className="button primary" disabled={!name.trim()} onClick={() => void create()}><Check size={16} /> Create home</button></div>
          </div>
        </section>
      )}
      {resource.loading && <Skeleton lines={6} />}
      {resource.error && <ErrorPanel message={resource.error.message} onRetry={() => void resource.reload()} />}
      {resource.data && (resource.data.length ? (
        <div className="home-catalogue">
          {resource.data.map((home, index) => (
            <Link to={`/homes/${home.homeId}`} className="home-record" key={home.homeId}>
              <div className="home-record-index">{String(index + 1).padStart(2, "0")}</div>
              <div><h2>{home.name}</h2><p>{home.description || "No description yet"}</p><code>{home.homeId}</code></div>
              <dl><div><dt>Residents</dt><dd>{home.residentCount}</dd></div><div><dt>Runs</dt><dd>{home.runCount}</dd></div><div><dt>Issues</dt><dd>{home.issueCount}</dd></div></dl>
              <span className="open-label">Open workspace</span>
            </Link>
          ))}
        </div>
      ) : !creating && <EmptyState title={query ? "No homes match this search" : "Create an environment to begin"} icon={<HomeIcon size={25} />} action={query ? <button className="button secondary" onClick={() => setSearchParams({})}>Clear search</button> : <button className="button primary" onClick={() => setCreating(true)}><Plus size={16} /> New home</button>}><p>{query ? "Try another name or clear the filter." : "A home is the durable container for resident inputs, planimetry, sensors and reproducible runs."}</p></EmptyState>)}
    </div>
  );
}

function useJobRefresh(jobs: JobRecord[], reload: () => Promise<void>) {
  const activeIds = jobs
    .filter((item) => !terminal.has(item.status))
    .map((item) => item.jobId)
    .join("|");
  useEffect(() => {
    const sources: EventSource[] = [];
    let disposed = false;
    for (const jobId of activeIds.split("|").filter(Boolean)) {
      void eventSourceUrl(jobId).then((url) => {
        if (disposed) return;
        const source = new EventSource(url);
        source.onmessage = () => void reload();
        source.addEventListener("progress", () => void reload());
        source.addEventListener("status", () => void reload());
        source.addEventListener("done", () => { void reload(); source.close(); });
        sources.push(source);
      });
    }
    return () => { disposed = true; sources.forEach((source) => source.close()); };
  }, [activeIds, reload]);
}

function HomePage() {
  const { homeId = "" } = useParams();
  const resource = useResource<HomeDetail>(`/homes/${homeId}`);
  const [tab, setTab] = useState<"overview" | "home" | "sensors" | "runs">("overview");
  const [selectedId, setSelectedId] = useState<string>();
  const [bundleFile, setBundleFile] = useState<File>();
  const [scenarioFile, setScenarioFile] = useState<File>();
  const [behaviorFile, setBehaviorFile] = useState<File>();
  const [manifestFile, setManifestFile] = useState<File>();
  const [manifestSourcePath, setManifestSourcePath] = useState("");
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string }>();
  const [homeDraft, setHomeDraft] = useState<HomeModel>();
  const [sensorDraft, setSensorDraft] = useState<SensorModel>();
  const [history, setHistory] = useState<Array<{ home?: HomeModel; sensor?: SensorModel }>>([]);
  const [future, setFuture] = useState<Array<{ home?: HomeModel; sensor?: SensorModel }>>([]);
  const [viewport, setViewport] = useState({ zoom: 1, x: 0, y: 0 });
  useJobRefresh(resource.data?.jobs ?? [], resource.reload);
  const sourceHome = resource.data?.models.homeModel;
  const sourceSensor = resource.data?.models.sensorModel;
  useEffect(() => {
    if (sourceHome) setHomeDraft(structuredClone(sourceHome));
    if (sourceSensor) setSensorDraft(structuredClone(sourceSensor));
  }, [sourceHome, sourceSensor]);
  if (resource.loading) return <div className="page"><Skeleton lines={8} /></div>;
  if (resource.error || !resource.data) return <div className="page"><ErrorPanel message={resource.error?.message ?? "Home not found"} onRetry={() => void resource.reload()} /></div>;
  const detail = resource.data;
  const activeJob = detail.jobs.find((job) => !terminal.has(job.status));
  const inputResident = detail.residents.find((resident) => resident.scenarioArtifactId && resident.behaviorArtifactId);

  const submitAuthoring = async (path: string, body: () => Promise<Record<string, unknown>>) => {
    setWorking(true); setNotice(undefined);
    try {
      const result = await api<{ valid: boolean; issues: ImportIssue[]; bundleArtifact?: { artifactId: string } }>(`/homes/${homeId}/${path}`, {
        method: "POST",
        body: JSON.stringify(await body()),
      });
      if (!result.valid) setNotice({ kind: "error", text: summarizeIssues(result.issues) });
      else { setNotice({ kind: "success", text: "The complete authoring bundle passed validation, compilation and behavior compatibility gates." }); await resource.reload(); }
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  const importBundle = async () => {
    if (!bundleFile) return;
    await submitAuthoring("authoring-bundle", () => readJson(bundleFile));
  };
  const importAdvancedInputs = async () => {
    if (!scenarioFile || !behaviorFile) return;
    await submitAuthoring("authoring", async () => ({
      scenario: await readJson(scenarioFile),
      personal_process_package: await readJson(behaviorFile),
    }));
  };
  const importLongitudinalManifest = async () => {
    if (!manifestFile) return;
    setWorking(true); setNotice(undefined);
    try {
      const manifest = await readJson(manifestFile);
      const imported = await api<{ valid: boolean; manifestArtifactId?: string; issues?: ImportIssue[]; runId?: string; chunkCount?: number }>(`/homes/${homeId}/longitudinal`, {
        method: "POST",
        body: JSON.stringify({ manifest, manifest_source_path: manifestSourcePath || undefined }),
      });
      if (!imported.valid) {
        setNotice({ kind: "error", text: summarizeIssues(imported.issues ?? []) });
      } else {
        await api(`/homes/${homeId}/longitudinal-runs`, {
          method: "POST",
          body: JSON.stringify({ manifest_artifact_id: imported.manifestArtifactId }),
        });
        setNotice({ kind: "success", text: `Longitudinal run '${imported.runId ?? "run"}' queued with ${imported.chunkCount ?? 0} sequence chunks.` });
        await resource.reload();
      }
    } catch (reason) {
      setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) });
    } finally {
      setWorking(false);
    }
  };
  const startRun = async () => {
    if (!inputResident?.scenarioArtifactId || !inputResident.behaviorArtifactId) return;
    setWorking(true); setNotice(undefined);
    try {
      await api(`/homes/${homeId}/runs`, { method: "POST", body: JSON.stringify({ scenario_artifact_id: inputResident.scenarioArtifactId, behavior_artifact_id: inputResident.behaviorArtifactId }) });
      setNotice({ kind: "success", text: "The run was queued in an isolated local worker." });
      await resource.reload();
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  const currentSnapshot = () => ({ home: homeDraft ? structuredClone(homeDraft) : undefined, sensor: sensorDraft ? structuredClone(sensorDraft) : undefined });
  const snapshot = () => { setHistory((items) => [...items.slice(-49), currentSnapshot()]); setFuture([]); };
  const nudgeSelected = (dx: number, dy: number) => {
    snapshot();
    if (tab === "sensors" && sensorDraft) {
      setSensorDraft({ ...sensorDraft, sensors: sensorDraft.sensors.map((sensor) => {
        if (sensor.sensorId !== selectedId) return sensor;
        const coverage = sensor.sensorType === "pir" && sensor.coverage && typeof sensor.coverage === "object"
          ? { vertices: (sensor.coverage as { vertices: Array<{ x: number; y: number }> }).vertices.map((point) => ({ x: point.x + dx, y: point.y + dy })) }
          : sensor.coverage;
        return { ...sensor, position: { x: sensor.position.x + dx, y: sensor.position.y + dy }, coverage };
      }) });
    } else if (homeDraft) {
      const entity = homeDraft.entities.find((item) => item.entityId === selectedId);
      const pointId = entity?.interactionPointId ?? selectedId;
      setHomeDraft({ ...homeDraft, interactionPoints: homeDraft.interactionPoints.map((point) => point.interactionPointId === pointId ? { ...point, position: { x: point.position.x + dx, y: point.position.y + dy } } : point) });
    }
  };
  const undo = () => {
    const previous = history.at(-1); if (!previous) return;
    setFuture((items) => [...items.slice(-49), currentSnapshot()]);
    if (previous.home) setHomeDraft(previous.home); if (previous.sensor) setSensorDraft(previous.sensor);
    setHistory((items) => items.slice(0, -1));
  };
  const redo = () => {
    const next = future.at(-1); if (!next) return;
    setHistory((items) => [...items.slice(-49), currentSnapshot()]);
    if (next.home) setHomeDraft(next.home); if (next.sensor) setSensorDraft(next.sensor);
    setFuture((items) => items.slice(0, -1));
  };
  const importModel = async (kind: "home" | "sensor", file?: File) => {
    if (!file) return;
    try {
      snapshot();
      const payload = await readJson(file);
      if (kind === "home") setHomeDraft(payload as unknown as HomeModel);
      else setSensorDraft(payload as unknown as SensorModel);
      setSelectedId(undefined);
      setNotice({ kind: "success", text: `${kind === "home" ? "Home" : "Sensor"} model loaded as a draft. Validate and publish to make it authoritative.` });
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
  };
  const addEditorObject = (kind: "room" | "obstacle" | "pir" | "contact" | "temperature") => {
    try {
      snapshot();
      if (kind === "room" && homeDraft) {
        const result = addRoom(homeDraft); setHomeDraft(result.model); setSelectedId(result.selectedId);
      } else if (kind === "obstacle" && homeDraft) {
        const result = addObstacle(homeDraft, selectedId); setHomeDraft(result.model); setSelectedId(result.selectedId);
      } else if (sensorDraft && homeDraft) {
        const result = addSensor(sensorDraft, homeDraft, kind as "pir" | "contact" | "temperature"); setSensorDraft(result.model); setSelectedId(result.selectedId);
      }
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
  };
  const removeEditorObject = () => {
    if (!selectedId || !homeDraft) return;
    snapshot();
    const result = removeSelection(homeDraft, sensorDraft, selectedId);
    setHomeDraft(result.home); if (result.sensors) setSensorDraft(result.sensors); setSelectedId(undefined);
  };
  const publish = async (kind: "home" | "sensor") => {
    const model = kind === "home" ? homeDraft : sensorDraft; if (!model) return;
    setWorking(true); setNotice(undefined);
    try {
      const result = await api<{ valid: boolean; issues: Array<{ message: string }> }>(`/homes/${homeId}/${kind}-model`, { method: "PUT", body: JSON.stringify({ model }) });
      if (!result.valid) setNotice({ kind: "error", text: result.issues.map((item) => item.message).join(" · ") });
      else { setNotice({ kind: "success", text: `${kind === "home" ? "Home" : "Sensor"} revision validated and published.` }); setHistory([]); setFuture([]); await resource.reload(); }
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  return (
    <div className="page home-page">
      <Breadcrumbs items={[{ label: "Homes", to: "/homes" }, { label: detail.home.name }]} />
      <PageHeader eyebrow="Environment workspace" title={detail.home.name} description={detail.home.description || "Executable spatial model and resident context"} actions={<><StatusBadge status={activeJob?.status ?? (homeDraft ? "valid" : "draft")} /><button className="button primary" disabled={!inputResident || !!activeJob || working} onClick={() => void startRun()}><Play size={16} /> Run simulation</button></>} />
      {notice && <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.kind === "success" ? <Check size={18} /> : <AlertCircle size={18} />}<span>{notice.text}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice(undefined)}><X size={16} /></button></div>}
      {!!detail.issues?.length && <section className="validation-summary" aria-labelledby="validation-issues-title"><div><p className="eyebrow">Persisted validation</p><h2 id="validation-issues-title">Resolve {detail.issues.length} authoritative issue{detail.issues.length === 1 ? "" : "s"}</h2></div><div>{detail.issues.map((issue, index) => <button key={`${issue.code}-${issue.path}-${index}`} onClick={() => { const target = issue.graphicalReference?.elementId; if (target && !target.startsWith("index:")) setSelectedId(target); if (issue.graphicalReference?.surface === "sensor") setTab("sensors"); else if (issue.graphicalReference?.surface === "home") setTab("home"); }}><AlertCircle size={16} /><span><strong>{issue.message}</strong><small>{issue.code} · {issue.path}</small></span></button>)}</div></section>}
      {activeJob && <section className="active-run-bar"><div><StatusBadge status={activeJob.status} /><strong>{activeJob.progress.message}</strong></div><ProgressBar value={activeJob.progress.percent} label={activeJob.progress.phase} /><Link to={`/simulations/${activeJob.jobId}`} className="button secondary">Open live detail</Link></section>}
      <div className="tabs" role="tablist" aria-label="Home sections">
        {(["overview", "home", "sensors", "runs"] as const).map((item) => <button key={item} role="tab" aria-selected={tab === item} onClick={() => setTab(item)}>{item === "home" ? "Plan & resources" : item}</button>)}
      </div>
      {tab === "overview" && <div className="home-overview-grid">
        <section className="surface context-sheet">
          <div className="section-heading"><div><p className="eyebrow">Resident context</p><h2>{detail.residents.length ? `${detail.residents.length} associated resident${detail.residents.length === 1 ? "" : "s"}` : "Attach accepted authoring"}</h2></div><Users size={21} /></div>
          {detail.residents.length ? <div className="resident-list">{detail.residents.map((resident) => <div key={resident.residentId}><span className="avatar"><UserRound size={17} /></span><span><strong>{resident.displayName}</strong><code>{resident.sourceResidentId}</code></span><StatusBadge status="valid" /></div>)}</div> : <div className="import-flow">
            <p>Import the single pure-JSON response generated by your external LLM. Nothing is published unless the whole bundle passes every authoritative gate.</p>
            <Link className="import-guide-link" to="/help#authoring"><BookOpen size={18} /><span><strong>Need to generate the file?</strong><small>Open the integrated guide and copy the simplified or complete prompt.</small></span></Link>
            <label className="file-picker bundle-picker"><FileJson size={22} /><span><strong>Simulation authoring bundle</strong><small>{bundleFile?.name ?? "Choose the complete authoring-bundle.json"}</small></span><input type="file" accept="application/json,.json" onChange={(event) => setBundleFile(event.target.files?.[0])} /></label>
            <button className="button primary" disabled={!bundleFile || working} onClick={() => void importBundle()}><Upload size={16} /> Validate bundle and attach</button>
            <details className="advanced-import">
              <summary><ChevronDown size={17} /><span><strong>Advanced: import canonical documents separately</strong><small>For debugging, migrations and expert intervention.</small></span></summary>
              <div>
                <p>The server reconstructs one bundle and applies the same atomic validation pipeline.</p>
                <label className="file-picker"><FileJson size={20} /><span><strong>Scenario JSON</strong><small>{scenarioFile?.name ?? "Choose the accepted scenario"}</small></span><input type="file" accept="application/json,.json" onChange={(event) => setScenarioFile(event.target.files?.[0])} /></label>
                <label className="file-picker"><ListTree size={20} /><span><strong>Personal process package</strong><small>{behaviorFile?.name ?? "Choose the matching process package"}</small></span><input type="file" accept="application/json,.json" onChange={(event) => setBehaviorFile(event.target.files?.[0])} /></label>
                <button className="button secondary" disabled={!scenarioFile || !behaviorFile || working} onClick={() => void importAdvancedInputs()}><Upload size={16} /> Validate Advanced import</button>
              </div>
            </details>
            <details className="advanced-import">
              <summary><ChevronDown size={17} /><span><strong>Longitudinal: import multi-scenario manifest</strong><small>For multi-day or multi-week continuous simulation runs.</small></span></summary>
              <div>
                <p>Upload a longitudinal simulation manifest JSON defining sequence chunks and package inputs.</p>
                <label className="file-picker"><FileJson size={20} /><span><strong>Longitudinal manifest JSON</strong><small>{manifestFile?.name ?? "Choose manifest.json"}</small></span><input type="file" accept="application/json,.json" onChange={(event) => setManifestFile(event.target.files?.[0])} /></label>
                <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", marginTop: "0.5rem" }}><small style={{ opacity: 0.7 }}>Manifest path on disk (for auto-resolving relative scenario files):</small><input type="text" placeholder="e.g. C:\path\to\manifest.json" value={manifestSourcePath} onChange={(event) => setManifestSourcePath(event.target.value)} style={{ padding: "0.35rem 0.5rem", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--bg-card)", color: "inherit", fontSize: "0.85rem" }} /></label>
                <button className="button primary" disabled={!manifestFile || working} onClick={() => void importLongitudinalManifest()}><Upload size={16} /> Validate and launch longitudinal run</button>
              </div>
            </details>
          </div>}
        </section>
        <section className="surface evidence-sheet">
          <div className="section-heading"><div><p className="eyebrow">Environment state</p><h2>Authoritative revisions</h2></div><ShieldCheck size={21} /></div>
          <dl className="definition-list"><div><dt>Home model</dt><dd>{detail.home.currentHomeArtifactId ? <><StatusBadge status="valid" /><code>{detail.home.currentHomeArtifactId}</code></> : <StatusBadge status="draft" />}</dd></div><div><dt>Sensor model</dt><dd>{detail.home.currentSensorArtifactId ? <><StatusBadge status="valid" /><code>{detail.home.currentSensorArtifactId}</code></> : <StatusBadge status="draft" />}</dd></div><div><dt>Runs</dt><dd>{detail.jobs.length}</dd></div></dl>
          {!homeDraft && inputResident && <button className="button primary" disabled={working || !!activeJob} onClick={() => void startRun()}><RouteIcon size={16} /> Generate home, sensors and first run</button>}
        </section>
      </div>}
      {(tab === "home" || tab === "sensors") && <div className="editor-layout">
        <section className="editor-stage">
          <div className="editor-toolbar"><div><button className="tool-button" disabled={!history.length} onClick={undo}><RotateCcw size={16} /> Undo</button><button className="tool-button" disabled={!future.length} onClick={redo}><RotateCw size={16} /> Redo</button><button className="tool-button" aria-pressed="true"><Square size={15} /> Select</button>{tab === "home" ? <><button className="tool-button" disabled={!homeDraft} onClick={() => addEditorObject("room")}><Plus size={15} /> Room</button><button className="tool-button" disabled={!homeDraft} onClick={() => addEditorObject("obstacle")}><Plus size={15} /> Obstacle</button></> : <>{(["pir", "contact", "temperature"] as const).map((kind) => <button key={kind} className="tool-button" disabled={!homeDraft || !sensorDraft} onClick={() => addEditorObject(kind)}><Plus size={15} /> {kind}</button>)}</>}<label className="tool-button file-tool"><Upload size={15} /> Import {tab === "home" ? "home" : "sensors"}<input type="file" accept="application/json,.json" onChange={(event) => void importModel(tab === "home" ? "home" : "sensor", event.target.files?.[0])} /></label></div><div className="viewport-tools" aria-label="Plan viewport"><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, zoom: Math.max(.5, item.zoom / 1.25) }))} aria-label="Zoom out"><ZoomOut size={15} /></button><button className="tool-button" onClick={() => setViewport({ zoom: 1, x: 0, y: 0 })} aria-label="Fit plan"><Maximize2 size={15} /></button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, zoom: Math.min(4, item.zoom * 1.25) }))} aria-label="Zoom in"><ZoomIn size={15} /></button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, x: item.x - 1 }))} aria-label="Pan left">←</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, y: item.y - 1 }))} aria-label="Pan up">↑</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, y: item.y + 1 }))} aria-label="Pan down">↓</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, x: item.x + 1 }))} aria-label="Pan right">→</button><span>{Math.round(viewport.zoom * 100)}%</span></div></div>
          {homeDraft ? <PlanCanvas home={homeDraft} sensors={tab === "sensors" ? sensorDraft : undefined} selectedId={selectedId} onSelect={setSelectedId} viewport={viewport} /> : <EmptyState title="No spatial model yet" icon={<RouteIcon size={25} />}><p>Run scenario-first materialization or import a valid home model to open the editor.</p></EmptyState>}
        </section>
        <aside className="inspector" aria-label="Selection inspector">
          <div className="inspector-heading"><div><p className="eyebrow">Inspector</p><h2>{selectedId ?? "Nothing selected"}</h2></div>{selectedId && <button className="icon-button" onClick={() => setSelectedId(undefined)} aria-label="Clear selection"><X size={16} /></button>}</div>
          {selectedId ? <><p className="inspector-help">Use precise keyboard-compatible controls. Publishing creates a new immutable revision and runs authoritative validation.</p><fieldset><legend>Position adjustment</legend><div className="nudge-grid"><span /><button onClick={() => nudgeSelected(0, -0.1)} aria-label="Move up">↑</button><span /><button onClick={() => nudgeSelected(-0.1, 0)} aria-label="Move left">←</button><b>0.1 m</b><button onClick={() => nudgeSelected(0.1, 0)} aria-label="Move right">→</button><span /><button onClick={() => nudgeSelected(0, 0.1)} aria-label="Move down">↓</button><span /></div></fieldset><EditorFields tab={tab} selectedId={selectedId} home={homeDraft} sensors={sensorDraft} onHome={(model) => { snapshot(); setHomeDraft(model); }} onSensors={(model) => { snapshot(); setSensorDraft(model); }} /><div className="inspector-section"><h3>Identity and provenance</h3><code>{selectedId}</code><p>Selection is preserved between the plan, structured tree and validation report.</p><button className="button danger" onClick={removeEditorObject}><Trash2 size={15} /> Remove selected object</button></div></> : <div className="quiet-state"><CircleDot size={22} /><strong>Select an object on the plan</strong><p>Rooms, providers, obstacles and sensors are also reachable with Tab, Enter and Space.</p></div>}
          <div className="inspector-footer"><button className="button primary" disabled={working || !(tab === "home" ? homeDraft : sensorDraft)} onClick={() => void publish(tab === "home" ? "home" : "sensor")}><Save size={16} /> Validate and publish</button></div>
        </aside>
      </div>}
      {tab === "runs" && <RunTable jobs={detail.jobs} empty="No run has been started for this home." />}
    </div>
  );
}

function EditorFields({ tab, selectedId, home, sensors, onHome, onSensors }: { tab: "home" | "sensors"; selectedId: string; home?: HomeModel; sensors?: SensorModel; onHome: (model: HomeModel) => void; onSensors: (model: SensorModel) => void }) {
  if (!home) return null;
  const sensor = sensors?.sensors.find((item) => item.sensorId === selectedId);
  if (tab === "sensors" && sensor && sensors) {
    const update = (next: Partial<typeof sensor>) => onSensors({ ...sensors, sensors: sensors.sensors.map((item) => item.sensorId === selectedId ? { ...item, ...next } : item) });
    const timing = (key: keyof typeof sensor.timing, value: number) => update({ timing: { ...sensor.timing, [key]: value } });
    const error = (key: keyof typeof sensor.errorModel, value: number) => update({ errorModel: { ...sensor.errorModel, [key]: value } });
    const setFailure = (index: number, key: "startsAt" | "endsAt", value: string) => update({ failureWindows: sensor.failureWindows.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: new Date(value).toISOString() } : item) });
    const addFailure = () => {
      const starts = new Date();
      const ends = new Date(starts.getTime() + 60 * 60 * 1000);
      update({ failureWindows: [...sensor.failureWindows, { startsAt: starts.toISOString(), endsAt: ends.toISOString() }] });
    };
    return <div className="inspector-section editor-fields"><h3>Sensor configuration</h3><div className="field-grid"><label><span>X position</span><input type="number" step="0.1" value={sensor.position.x} onChange={(event) => update({ position: { ...sensor.position, x: event.target.valueAsNumber } })} /></label><label><span>Y position</span><input type="number" step="0.1" value={sensor.position.y} onChange={(event) => update({ position: { ...sensor.position, y: event.target.valueAsNumber } })} /></label><label><span>Latency ms</span><input type="number" min="0" value={sensor.timing.latencyMilliseconds} onChange={(event) => timing("latencyMilliseconds", event.target.valueAsNumber)} /></label><label><span>Jitter ms</span><input type="number" min="0" value={sensor.timing.clockJitterMilliseconds} onChange={(event) => timing("clockJitterMilliseconds", event.target.valueAsNumber)} /></label><label><span>Cooldown ms</span><input type="number" min="0" value={sensor.timing.cooldownMilliseconds} onChange={(event) => timing("cooldownMilliseconds", event.target.valueAsNumber)} /></label><label><span>Dropout 0–1</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.dropoutProbability} onChange={(event) => error("dropoutProbability", event.target.valueAsNumber)} /></label><label><span>False negative 0–1</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.falseNegativeProbability} onChange={(event) => error("falseNegativeProbability", event.target.valueAsNumber)} /></label><label><span>False positives/day</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.falsePositiveProbabilityPerDay} onChange={(event) => error("falsePositiveProbabilityPerDay", event.target.valueAsNumber)} /></label><label><span>Noise σ</span><input type="number" min="0" step="0.01" value={sensor.errorModel.measurementNoiseStandardDeviation} onChange={(event) => error("measurementNoiseStandardDeviation", event.target.valueAsNumber)} /></label>{sensor.sensorType === "temperature" && <><label><span>Region</span><select value={String(sensor.regionId)} onChange={(event) => update({ regionId: event.target.value })}>{home.regions.map((item) => <option key={item.regionId}>{item.regionId}</option>)}</select></label><label><span>Baseline °C</span><input type="number" step="0.1" value={Number(sensor.baselineCelsius)} onChange={(event) => update({ baselineCelsius: event.target.valueAsNumber })} /></label></>}{sensor.sensorType === "contact" && <label><span>Entity</span><select value={String(sensor.entityId)} onChange={(event) => update({ entityId: event.target.value })}>{home.entities.map((item) => <option key={item.entityId}>{item.entityId}</option>)}</select></label>}</div><div className="failure-editor"><div><h4>Failure windows</h4><button className="button secondary" onClick={addFailure}><Plus size={14} /> Add window</button></div>{sensor.failureWindows.length ? sensor.failureWindows.map((window, index) => <div className="failure-window" key={`${window.startsAt}-${index}`}><label><span>Starts</span><input type="datetime-local" value={window.startsAt.slice(0, 16)} onChange={(event) => setFailure(index, "startsAt", event.target.value)} /></label><label><span>Ends</span><input type="datetime-local" value={window.endsAt.slice(0, 16)} onChange={(event) => setFailure(index, "endsAt", event.target.value)} /></label><button className="icon-button" aria-label={`Remove failure window ${index + 1}`} onClick={() => update({ failureWindows: sensor.failureWindows.filter((_, itemIndex) => itemIndex !== index) })}><Trash2 size={14} /></button></div>) : <p>No planned dropout interval. Random dropout remains controlled by the probability above.</p>}</div></div>;
  }
  const region = home.regions.find((item) => item.regionId === selectedId);
  if (region) return <div className="inspector-section editor-fields"><h3>Region geometry</h3><label><span>Kind</span><select value={region.kind} onChange={(event) => onHome({ ...home, regions: home.regions.map((item) => item.regionId === selectedId ? { ...item, kind: event.target.value as typeof item.kind } : item) })}>{["room", "outdoor", "external", "transit"].map((kind) => <option key={kind}>{kind}</option>)}</select></label><label className="check-field"><input type="checkbox" checked={region.traversable} onChange={(event) => onHome({ ...home, regions: home.regions.map((item) => item.regionId === selectedId ? { ...item, traversable: event.target.checked } : item) })} /><span>Traversable</span></label><div className="vertex-list">{region.boundary.vertices.map((point, index) => <div key={index}><span>Vertex {index + 1}</span><input aria-label={`Vertex ${index + 1} X`} type="number" step="0.1" value={point.x} onChange={(event) => onHome({ ...home, regions: home.regions.map((item) => item.regionId === selectedId ? { ...item, boundary: { vertices: item.boundary.vertices.map((vertex, vertexIndex) => vertexIndex === index ? { ...vertex, x: event.target.valueAsNumber } : vertex) } } : item) })} /><input aria-label={`Vertex ${index + 1} Y`} type="number" step="0.1" value={point.y} onChange={(event) => onHome({ ...home, regions: home.regions.map((item) => item.regionId === selectedId ? { ...item, boundary: { vertices: item.boundary.vertices.map((vertex, vertexIndex) => vertexIndex === index ? { ...vertex, y: event.target.valueAsNumber } : vertex) } } : item) })} /></div>)}</div></div>;
  const obstacle = home.obstacles.find((item) => item.obstacleId === selectedId);
  const entity = home.entities.find((item) => item.entityId === selectedId);
  if (entity) {
    const updateEntity = (next: Partial<typeof entity>) => onHome({ ...home, entities: home.entities.map((item) => item.entityId === selectedId ? { ...item, ...next } : item) });
    const setRegion = (regionId: string) => onHome({
      ...home,
      entities: home.entities.map((item) => item.entityId === selectedId ? { ...item, regionId } : item),
      interactionPoints: home.interactionPoints.map((item) => item.interactionPointId === entity.interactionPointId ? { ...item, regionId } : item),
    });
    const coerceState = (value: string): unknown => value === "true" ? true : value === "false" ? false : Number.isNaN(Number(value)) || !value.trim() ? value : Number(value);
    return <div className="inspector-section editor-fields"><h3>Capability provider</h3><label><span>Provider type</span><input value={entity.entityType} onChange={(event) => updateEntity({ entityType: event.target.value })} /></label><label><span>Containing region</span><select value={entity.regionId} onChange={(event) => setRegion(event.target.value)}>{home.regions.map((item) => <option key={item.regionId}>{item.regionId}</option>)}</select></label><div className="capability-editor"><div><h4>Capabilities</h4><button className="button secondary" onClick={() => updateEntity({ capabilities: [...entity.capabilities, { capability: `capability_${entity.capabilities.length + 1}`, roles: [], supportedOperations: [] }] })}><Plus size={14} /> Add capability</button></div>{entity.capabilities.map((capability, index) => <div className="capability-row" key={`${capability.capability}-${index}`}><label><span>Capability</span><input value={capability.capability} onChange={(event) => updateEntity({ capabilities: entity.capabilities.map((item, itemIndex) => itemIndex === index ? { ...item, capability: event.target.value } : item) })} /></label><label><span>Roles</span><input value={capability.roles.join(", ")} onChange={(event) => updateEntity({ capabilities: entity.capabilities.map((item, itemIndex) => itemIndex === index ? { ...item, roles: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } : item) })} /></label><label><span>Operations</span><input value={capability.supportedOperations.join(", ")} onChange={(event) => updateEntity({ capabilities: entity.capabilities.map((item, itemIndex) => itemIndex === index ? { ...item, supportedOperations: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } : item) })} /></label><button className="icon-button" aria-label={`Remove capability ${index + 1}`} onClick={() => updateEntity({ capabilities: entity.capabilities.filter((_, itemIndex) => itemIndex !== index) })}><Trash2 size={14} /></button></div>)}</div><div className="initial-state-editor"><h4>Initial state</h4>{Object.entries(entity.initialState).map(([fact, value]) => <label key={fact}><span>{fact}</span><input value={String(value)} onChange={(event) => updateEntity({ initialState: { ...entity.initialState, [fact]: coerceState(event.target.value) } })} /></label>)}</div></div>;
  }
  return <div className="inspector-section editor-fields"><h3>{obstacle ? "Obstacle" : "Spatial object"}</h3>{obstacle && <label><span>Containing region</span><select value={obstacle.regionId} onChange={(event) => onHome({ ...home, obstacles: home.obstacles.map((item) => item.obstacleId === selectedId ? { ...item, regionId: event.target.value } : item) })}>{home.regions.map((item) => <option key={item.regionId}>{item.regionId}</option>)}</select></label>}</div>;
}

function RunTable({ jobs, empty }: { jobs: JobRecord[]; empty: string }) {
  if (!jobs.length) return <EmptyState title="No simulation evidence yet" icon={<Activity size={25} />}><p>{empty}</p></EmptyState>;
  return <div className="run-table" role="table" aria-label="Simulation runs"><div className="run-table-head" role="row"><span>Run</span><span>Status</span><span>Phase</span><span>Seed</span><span>Requested</span><span /></div>{jobs.map((job) => <div className="run-row" role="row" key={job.jobId}><span><code>{job.jobId}</code><small>{job.kind}</small></span><StatusBadge status={job.status} /><span>{job.progress.phase}<small>{job.progress.message}</small></span><code>{job.seed ?? "source"}</code><time>{formatDate(job.requestedAt)}</time><RunLink id={job.jobId}>Details</RunLink></div>)}</div>;
}

function ResidentsPage() {
  const resource = useResource<Overview>("/overview");
  return <div className="page"><PageHeader eyebrow="People and provenance" title="Residents" description="Resident identities remain attached to their accepted scenario and behavior revisions." />{resource.loading ? <Skeleton lines={6} /> : resource.error ? <ErrorPanel message={resource.error.message} onRetry={() => void resource.reload()} /> : resource.data?.residents.length ? <div className="resident-catalogue">{resource.data.residents.map((resident) => { const home = resource.data?.homes.find((item) => item.homeId === resident.homeId); return <Link to={`/homes/${resident.homeId}`} key={resident.residentId} className="resident-record"><span className="avatar large"><UserRound size={22} /></span><div><h2>{resident.displayName}</h2><code>{resident.sourceResidentId}</code><p>Home: {home?.name ?? resident.homeId}</p></div><dl><div><dt>Scenario</dt><dd>{resident.scenarioArtifactId ? "Attached" : "Missing"}</dd></div><div><dt>Behavior</dt><dd>{resident.behaviorArtifactId ? "Attached" : "Missing"}</dd></div></dl></Link>; })}</div> : <EmptyState title="No residents attached" icon={<Users size={25} />}><p>Import accepted authoring from a home workspace to attach its declared residents.</p></EmptyState>}</div>;
}

function SimulationsPage() {
  const resource = useResource<JobRecord[]>("/jobs?limit=500");
  const [filter, setFilter] = useState<string>("all");
  const jobs = resource.data?.filter((job) => filter === "all" || job.status === filter) ?? [];
  return <div className="page"><PageHeader eyebrow="Execution centre" title="Simulations" description="Persistent local jobs, actual backend phases and independently verified artifacts." actions={<div className="select-wrap"><Filter size={15} /><select aria-label="Filter by status" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All statuses</option>{["queued", "running", "completed", "failed", "cancelled", "interrupted"].map((status) => <option value={status} key={status}>{status}</option>)}</select><ChevronDown size={14} /></div>} />{resource.loading ? <Skeleton lines={7} /> : resource.error ? <ErrorPanel message={resource.error.message} onRetry={() => void resource.reload()} /> : <RunTable jobs={jobs} empty={filter === "all" ? "Create a home and start its first deterministic simulation." : `No ${filter} runs.`} />}</div>;
}

interface JobDetail { job: JobRecord; events: JobEvent[]; artifacts: Record<string, { artifactId: string; role: string; sha256: string; sizeBytes: number }> }

function RunPage() {
  const { runId = "" } = useParams();
  const detail = useResource<JobDetail>(`/jobs/${runId}`);
  useJobRefresh(detail.data ? [detail.data.job] : [], detail.reload);
  const [tab, setTab] = useState<"summary" | "diary" | "observations" | "replay" | "artifacts">("summary");
  const [oracle, setOracle] = useState(false);
  const [selectedDiary, setSelectedDiary] = useState<string>();
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent>();
  const [playing, setPlaying] = useState(false);
  const [exportNotice, setExportNotice] = useState<string>();
  const [exportManifest, setExportManifest] = useState<ExportManifest>();
  const evidenceAvailable = detail.data?.job.status === "completed";
  const diary = useResource<{ items: DiaryEntry[]; total: number }>(evidenceAvailable ? `/runs/${runId}/diary?limit=500` : undefined);
  const observations = useResource<{ items: Observation[]; total: number; mode: string }>(evidenceAvailable ? `/runs/${runId}/observations?limit=500&include_oracle=${oracle}` : undefined);
  const timeline = useResource<TimelineEvent[]>(evidenceAvailable ? `/runs/${runId}/timeline?limit=5000` : undefined);
  useEffect(() => {
    if (!evidenceAvailable && !["summary", "artifacts"].includes(tab)) setTab("summary");
  }, [evidenceAvailable, tab]);
  useEffect(() => {
    if (!playing || !timeline.data?.length) return;
    const movements = timeline.data.filter((event) => event.kind === "movement");
    let index = 0;
    const timer = window.setInterval(() => { setSelectedEvent(movements[index]); index += 1; if (index >= movements.length) setPlaying(false); }, 650);
    return () => window.clearInterval(timer);
  }, [playing, timeline.data]);
  if (detail.loading) return <div className="page"><Skeleton lines={8} /></div>;
  if (detail.error || !detail.data) return <div className="page"><ErrorPanel message={detail.error?.message ?? "Run not found"} onRetry={() => void detail.reload()} /></div>;
  const job = detail.data.job;
  const issueEvents = detail.data.events.filter((event) => event.eventType === "issue");
  const homeModelArtifact = detail.data.artifacts.home_model;
  const cancel = async () => { await api(`/jobs/${runId}/cancel`, { method: "POST" }); await detail.reload(); };
  const verify = async () => { try { const result = await api<{ matches: boolean; actualSemanticDigest: string }>(`/runs/${runId}/replay/verify`, { method: "POST" }); setExportNotice(result.matches ? `Replay verified: ${result.actualSemanticDigest}` : "Replay digest did not match"); } catch (reason) { setExportNotice(reason instanceof Error ? reason.message : String(reason)); } };
  const createExport = async () => { try { const result = await api<ExportManifest>(`/runs/${runId}/exports`, { method: "POST", body: JSON.stringify({ runId, formats: ["jsonl", "csv", "xes"], roles: ["observable", "oracle", "activities", "actions", "movements", "state_transitions", "resources", "runtime_events", "plan_deviations", "final_state"] }) }); setExportManifest(result); setExportNotice(`Export ${result.exportId} published with ${result.files.length} verified files.`); } catch (reason) { setExportNotice(reason instanceof Error ? reason.message : String(reason)); } };
  return <div className="page run-page">
    <Breadcrumbs items={[{ label: "Simulations", to: "/simulations" }, { label: runId }]} />
    <PageHeader eyebrow="Run evidence" title={runId} description={job.progress.message} actions={<><StatusBadge status={job.status} />{!terminal.has(job.status) && <button className="button danger" onClick={() => void cancel()}><Square size={15} /> Cancel safely</button>}</>} />
    {!terminal.has(job.status) && <section className="active-run-detail"><div className="phase-orbit" aria-hidden="true"><i /><span>{Math.round(job.progress.percent)}%</span></div><div><p className="eyebrow">Current backend phase</p><h2>{job.progress.phase}</h2><p>{job.progress.message}</p><ProgressBar value={job.progress.percent} label="Overall progress" /></div><ol>{detail.data.events.slice(-6).map((event) => <li key={event.sequence}><time>{formatTime(event.occurredAt)}</time><span>{event.message}</span></li>)}</ol></section>}
    <div className="tabs" role="tablist" aria-label="Run detail sections">{(["summary", "diary", "observations", "replay", "artifacts"] as const).map((item) => <button key={item} role="tab" aria-selected={tab === item} disabled={!evidenceAvailable && !["summary", "artifacts"].includes(item)} onClick={() => setTab(item)}>{item}</button>)}</div>
    {exportNotice && <div className="notice notice-success" role="status"><Check size={17} /><span>{exportNotice}</span><button className="icon-button" aria-label="Dismiss" onClick={() => setExportNotice(undefined)}><X size={15} /></button></div>}
    {tab === "summary" && <>{job.status === "failed" && <FailureDiagnostics job={job} events={issueEvents} />}<div className="run-summary-grid"><section className="surface"><div className="section-heading"><div><p className="eyebrow">Execution</p><h2>Persistent state</h2></div><Clock3 size={20} /></div><dl className="definition-list"><div><dt>Status</dt><dd><StatusBadge status={job.status} /></dd></div><div><dt>Requested</dt><dd>{formatDate(job.requestedAt)}</dd></div><div><dt>Started</dt><dd>{formatDate(job.startedAt)}</dd></div><div><dt>Finished</dt><dd>{formatDate(job.finishedAt)}</dd></div><div><dt>Worker PID</dt><dd><code>{job.processId ?? "n/a"}</code></dd></div></dl></section><section className="surface"><div className="section-heading"><div><p className="eyebrow">Scientific output</p><h2>{Object.keys(detail.data.artifacts).length} verified artifacts</h2></div><ShieldCheck size={20} /></div><p>{evidenceAvailable ? "Bundle, trace, observations and oracle remain separate and digest-addressable." : "Execution evidence was not published. Diary, observations and replay become available only after a completed run."}</p><div className="button-row"><button className="button primary" disabled={!evidenceAvailable} onClick={() => setTab("diary")}><ListTree size={16} /> Open ground-truth diary</button><button className="button secondary" disabled={!evidenceAvailable} onClick={() => void createExport()}><Download size={16} /> Export complete dataset</button></div></section></div>{exportManifest && <section className="surface export-manifest"><div className="section-heading"><div><p className="eyebrow">Verified export manifest</p><h2>{exportManifest.files.length} files across observable and oracle roles</h2></div><StatusBadge status="valid" /></div><p><code>{exportManifest.exportId}</code> · seed {exportManifest.seed} · trace {exportManifest.sourceTraceSemanticDigest.slice(0, 16)}…</p><div className="artifact-table"><div className="artifact-head"><span>Role</span><span>Format</span><span>Records</span><span>Download</span></div>{exportManifest.files.map((file) => <div className="artifact-row" key={file.relativePath}><span>{file.role.replaceAll("_", " ")}</span><code>{file.format}</code><span>{file.recordCount}</span><button className="row-link" onClick={() => void download(`/exports/${exportManifest.exportId}/files/${file.relativePath.split("/").at(-1)}`, file.relativePath.split("/").at(-1) ?? "dataset")}><Download size={15} /> Download</button></div>)}</div></section>}</>}
    {tab === "diary" && <section className="diary-layout"><div className="diary-list"><div className="section-heading"><div><p className="eyebrow">Authoritative execution trace</p><h2>Ground-truth diary</h2></div><span>{diary.data?.total ?? 0} activities</span></div>{diary.loading ? <Skeleton lines={8} /> : diary.error ? <ErrorPanel message={diary.error.message} /> : diary.data?.items?.map((entry) => <button key={entry.activityExecutionId} className={`diary-entry ${selectedDiary === entry.activityExecutionId ? "is-selected" : ""}`} onClick={() => setSelectedDiary(entry.activityExecutionId)}><time>{formatTime(entry.actualStart)}</time><span><strong>{entry.intent.replaceAll("_", " ")}</strong><small>{entry.actorId} · {duration(entry.actualStart, entry.actualEnd)} · {entry.actions.length} actions</small></span><StatusBadge status={entry.status} /></button>)}</div><DiaryInspector entry={diary.data?.items?.find((item) => item.activityExecutionId === selectedDiary) ?? diary.data?.items?.[0]} /></section>}
    {tab === "observations" && <section><div className="observable-toolbar"><div><p className="eyebrow">Sensor projection</p><h2>{oracle ? "Oracle-linked observations" : "Observable device log"}</h2></div><div className="mode-switch" role="group" aria-label="Data visibility"><button aria-pressed={!oracle} onClick={() => setOracle(false)}>Observable</button><button aria-pressed={oracle} onClick={() => setOracle(true)}>Oracle links</button></div></div><p className="mode-explanation">{oracle ? "Identity and activity appear only through the separate oracle mapping." : "This view contains only fields a physical device could expose."}</p>{observations.loading ? <Skeleton lines={8} /> : observations.error ? <ErrorPanel message={observations.error.message} /> : <div className="observation-table"><div className="observation-head"><span>Time</span><span>Sensor</span><span>Measurement</span><span>Value</span><span>Quality</span>{oracle && <span>Ground-truth cause</span>}</div>{observations.data?.items?.map((record) => <div className="observation-row" key={record.observationId}><time>{formatTime(record.observedAt)}</time><span><code>{record.sensorId}</code><small>{record.sensorType}</small></span><span>{record.measurement}</span><strong>{String(record.value)}{record.unit ? ` ${record.unit}` : ""}</strong><StatusBadge status={record.quality} />{oracle && <span className="cause-cell">{record.oracleCause ? <><b>{record.oracleCause.origin.replaceAll("_", " ")}</b><small>{record.oracleCause.residentIds.join(", ") || "No resident identity"} · {record.oracleCause.causeType}</small></> : "No oracle link"}</span>}</div>)}</div>}</section>}
    {tab === "replay" && <section className="replay-workbench"><div className="replay-toolbar"><button className="button secondary" onClick={() => setPlaying(!playing)}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause" : "Play movements"}</button><button className="button secondary" onClick={() => void verify()}><ShieldCheck size={15} /> Verify semantic digest</button><span>{selectedEvent ? `${formatTime(selectedEvent.at)} · ${selectedEvent.label}` : "Select an event on the timeline"}</span></div><div className="replay-stage">{homeModelArtifact ? <ReplayPlan runId={runId} activeMovement={selectedEvent} /> : <EmptyState title="Home artifact unavailable"><p>The plan cannot be reconstructed without the persisted home model.</p></EmptyState>}<aside className="timeline-panel"><div className="section-heading"><div><p className="eyebrow">Synchronized trace</p><h2>Timeline</h2></div><Activity size={19} /></div>{timeline.loading ? <Skeleton lines={7} /> : timeline.error ? <ErrorPanel message={timeline.error.message} /> : timeline.data?.slice(0, 800).map((event) => <button key={event.id} className={`timeline-event kind-${event.kind} ${selectedEvent?.id === event.id ? "is-selected" : ""}`} onClick={() => setSelectedEvent(event)}><time>{formatTime(event.at)}</time><i /><span><strong>{event.label.replaceAll("_", " ")}</strong><small>{event.kind} · {event.actorId}</small></span></button>)}</aside></div></section>}
    {tab === "artifacts" && <div className="artifact-table"><div className="artifact-head"><span>Role</span><span>Artifact</span><span>Size</span><span>SHA-256</span></div>{Object.entries(detail.data.artifacts).map(([role, artifact]) => <div className="artifact-row" key={artifact.artifactId}><span>{role.replaceAll("_", " ")}</span><code>{artifact.artifactId}</code><span>{new Intl.NumberFormat(undefined, { style: "unit", unit: "megabyte", maximumFractionDigits: 2 }).format(artifact.sizeBytes / 1_000_000)}</span><code title={artifact.sha256}>{artifact.sha256.slice(0, 16)}…</code></div>)}</div>}
  </div>;
}

function FailureDiagnostics({ job, events }: { job: JobRecord; events: JobEvent[] }) {
  const diagnostics = events.length ? events : [{ jobId: job.jobId, sequence: 0, occurredAt: job.finishedAt ?? job.requestedAt, eventType: "issue" as const, level: "error" as const, message: job.errorMessage ?? "The run failed before execution evidence could be published.", payload: { code: job.errorCode ?? "RUN_FAILED", phase: job.progress.phase } }];
  return <section className="failure-diagnostics" role="alert"><div className="failure-diagnostics-heading"><span><AlertCircle size={20} /></span><div><p className="eyebrow">Run stopped safely</p><h2>Execution evidence was not published</h2><p>The source artifacts remain intact. Resolve the diagnostics below, then start a new run.</p></div></div><div className="failure-issue-list">{diagnostics.map((event) => { const payload = event.payload; const details = payload.details && typeof payload.details === "object" && !Array.isArray(payload.details) ? payload.details as Record<string, unknown> : {}; return <article key={event.sequence}><div><code>{String(payload.code ?? job.errorCode ?? "RUN_FAILED")}</code><span>{String(payload.phase ?? payload.stage ?? job.progress.phase)}</span></div><h3>{event.message}</h3>{payload.path ? <p className="failure-path"><span>Path</span><code>{String(payload.path)}</code></p> : null}{Object.keys(details).length ? <dl>{Object.entries(details).map(([key, value]) => <div key={key}><dt>{key.replace(/([A-Z])/g, " $1")}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl> : null}</article>; })}</div></section>;
}

function DiaryInspector({ entry }: { entry?: DiaryEntry }) {
  if (!entry) return <aside className="diary-inspector"><div className="quiet-state"><ListTree size={22} /><strong>Select an activity</strong><p>Its executed actions and source identifiers will appear here.</p></div></aside>;
  return <aside className="diary-inspector"><div className="inspector-heading"><div><p className="eyebrow">Execution evidence</p><h2>{entry.intent.replaceAll("_", " ")}</h2></div><StatusBadge status={entry.status} /></div><dl className="definition-list compact"><div><dt>Resident</dt><dd>{entry.actorId}</dd></div><div><dt>Planned</dt><dd>{formatTime(entry.plannedStart)}–{formatTime(entry.plannedEnd)}</dd></div><div><dt>Actual</dt><dd>{formatTime(entry.actualStart)}–{formatTime(entry.actualEnd)}</dd></div><div><dt>Source activity</dt><dd><code>{entry.sourceActivityId}</code></dd></div><div><dt>Process model</dt><dd><code>{entry.processModelId}</code></dd></div><div><dt>Execution</dt><dd><code>{entry.activityExecutionId}</code></dd></div></dl><div className="action-sequence"><h3>Executed actions</h3>{entry.actions.map((action, index) => <div key={action.actionExecutionId}><span>{String(index + 1).padStart(2, "0")}</span><i /><div><strong>{action.actionType.replaceAll("_", " ")}</strong><small>{formatTime(action.startedAt)} · node {action.nodeId}</small><code>{action.actionExecutionId}</code></div></div>)}</div><div className="digest-block"><ShieldCheck size={16} /><span><strong>Trace provenance</strong><code>{entry.traceSemanticDigest}</code></span></div></aside>;
}

function ReplayPlan({ runId, activeMovement }: { runId: string; activeMovement?: TimelineEvent }) {
  const models = useResource<{ homeModel?: HomeModel; sensorModel?: SensorModel }>(`/runs/${runId}/models`);
  return <div className="replay-plan">{models.data?.homeModel ? <PlanCanvas home={models.data.homeModel} sensors={models.data.sensorModel} activeMovement={activeMovement} /> : models.error ? <ErrorPanel message={models.error.message} /> : <Skeleton lines={6} />}</div>;
}

function ExportsPage() {
  const jobs = useResource<JobRecord[]>("/jobs?limit=500");
  const completed = jobs.data?.filter((job) => job.status === "completed") ?? [];
  return <div className="page"><PageHeader eyebrow="Portable datasets" title="Exports" description="Streaming JSONL, CSV and XES projections with versions, seeds, digests and source relations." actions={<button className="button secondary" onClick={() => void download("/workspace/archive", "smart-home-workspace.shw")}><Download size={16} /> Archive workspace</button>} />{jobs.loading ? <Skeleton lines={6} /> : jobs.error ? <ErrorPanel message={jobs.error.message} /> : completed.length ? <div className="export-run-list">{completed.map((job) => <Link key={job.jobId} to={`/simulations/${job.jobId}`} className="export-run"><span className="object-symbol"><Download size={18} /></span><span><strong>{job.jobId}</strong><small>Build or verify an export from the run detail.</small></span><StatusBadge status="completed" /><span>Open export builder</span></Link>)}</div> : <EmptyState title="No completed run to export" icon={<Download size={25} />}><p>Exports are always derived from persisted, digest-verified execution artifacts.</p></EmptyState>}<section className="format-notes"><div><p className="eyebrow">JSONL</p><h2>Streaming records</h2><p>One canonical record per line, suited to large datasets and incremental tools.</p></div><div><p className="eyebrow">CSV</p><h2>Stable columns</h2><p>Separate files per artifact family. Nested values remain canonical JSON cells.</p></div><div><p className="eyebrow">XES</p><h2>Process mining</h2><p>Explicit trace and event mappings preserve source identifiers and timestamps.</p></div></section></div>;
}

function promptWithCase(template: string, caseDescription: string): string {
  const description = caseDescription.trim() || "[DESCRIVI QUI PERSONA, ABITUDINI, VINCOLI, DATE E OBIETTIVO DELLO STUDIO]";
  return template
    .replace("{{PERSON_AND_CASE_DESCRIPTION}}", description)
    .replace("[PERSON_AND_CASE_DESCRIPTION]", description)
    .replaceAll("[GENERATION_TIMESTAMP]", new Date().toISOString());
}

function PromptCard({ title, label, description, template, caseDescription }: { title: string; label: string; description: string; template: string; caseDescription: string }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const prompt = promptWithCase(template, caseDescription);
  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard access is unavailable");
      await navigator.clipboard.writeText(prompt);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch {
      setCopyState("error");
    }
  };
  return <div className="prompt-card"><div className="prompt-card-heading"><div><span>{label}</span><h3>{title}</h3><p>{description}</p></div><button className="button secondary" onClick={() => void copy()}>{copyState === "copied" ? <Check size={15} /> : <Copy size={15} />}{copyState === "copied" ? "Copied" : copyState === "error" ? "Copy failed" : "Copy prompt"}</button></div><details><summary>Preview the complete prompt</summary><pre>{prompt}</pre></details></div>;
}

function HelpPage() {
  const [caseDescription, setCaseDescription] = useState("");
  return <div className="page guide-page"><PageHeader eyebrow="Integrated guide" title="From a case description to inspectable evidence" description="Everything required to generate, import, run and verify a simulation—offline and without manual JSON authoring." /><div className="guide-layout"><nav aria-label="Guide contents"><a href="#authoring">Generate the bundle</a><a href="#first-run">Import and run</a><a href="#artifacts">Which file to use</a><a href="#truth">Truth and observation</a><a href="#recovery">Recovery</a><a href="#keyboard">Keyboard</a></nav><article><section id="authoring"><span>01</span><div><h2>Generate one authoring bundle</h2><p>Describe the person or people in ordinary language. Include dates, habits, constraints, health information and the research objective only when relevant. The prompt asks the external LLM to return one pure JSON object containing both the scenario and its personal process package.</p><label className="case-description"><span>Person and case description</span><textarea aria-label="Person and case description" value={caseDescription} onChange={(event) => setCaseDescription(event.target.value)} placeholder="Example: Lucia Rossi, 68, lives alone in Rome. Simulate August 2026…" /><small>This text is inserted locally into both prompts; the simplified prompt also receives a current ISO generation timestamp. Nothing is sent by this application.</small></label><div className="prompt-grid"><PromptCard title="Complete prompt" label="Recommended · Advanced 1.2.0" description="The authoritative path: full frozen schemas and catalogs for strict reproducibility and detailed diagnostics." template={authoringPrompts.advanced.text} caseDescription={caseDescription} /><PromptCard title="Simplified prompt" label="Corrected · compact 1.2.2" description="Preserves the requested duration and adds exact catalog references, end-exclusive dates and a chronological state ledger. Application validation remains mandatory." template={authoringPrompts.simplified.text} caseDescription={caseDescription} /></div><div className="guide-callout"><ShieldCheck size={19} /><p><strong>Save only the model response as JSON.</strong> It must start with <code>{"{"}</code>, end with <code>{"}"}</code>, and contain no Markdown fence or explanation.</p></div></div></section><section id="first-run"><span>02</span><div><h2>Import and run</h2><ol><li>Create a home from the Homes page.</li><li>Select the complete <code>authoring-bundle.json</code> in Resident context.</li><li>Resolve every reported validation issue; rejected bundles publish no authoring revision.</li><li>Start materialization. The worker compiles, builds the home, binds behavior, deploys sensors, executes and projects observations.</li><li>Open the completed run and verify its replay digest.</li></ol></div></section><section id="artifacts"><span>03</span><div><h2>Source, canonical and runtime files</h2><p><strong>Import the source bundle in the ordinary workflow.</strong> It has <code>documentType: simulation_authoring_bundle</code> and contains <code>scenario</code> plus <code>personalProcessPackage</code>. Canonical split files are internal validated projections. Runtime inputs may reference upgraded execution catalogs and are not a substitute for the researcher-authored source.</p><p>The collapsed Advanced importer accepts the two canonical documents separately for debugging or controlled migration. It does not silently repair or upgrade them.</p></div></section><section id="truth"><span>04</span><div><h2>Ground truth is not a sensor field</h2><p>The diary is derived from the authoritative execution trace. The Observable view contains only device fields. Oracle mode opens a separate mapping from a sensor record to its simulated cause, resident and activity.</p><div className="concept-pair"><div><Radar size={20} /><strong>Observable</strong><p>Sensor, timestamp, measurement, value and quality.</p></div><div><ShieldCheck size={20} /><strong>Oracle</strong><p>Movement, action or transition that produced the observation.</p></div></div></div></section><section id="recovery"><span>05</span><div><h2>Safe interruption and recovery</h2><p>Closing the browser leaves the backend and worker active. Cancelling a run discards staging. If the backend stops unexpectedly, active work becomes interrupted and the next start verifies every registered artifact before enabling publication.</p></div></section><section id="keyboard"><span>06</span><div><h2>Keyboard and structured alternatives</h2><p>Use Tab to reach plan objects, Enter or Space to select, and the inspector controls for precise movement. Every spatial object also appears in a structured list. Motion respects your reduced-motion preference.</p></div></section></article></div></div>;
}

function NotFound() {
  return <div className="page"><EmptyState title="This workspace view does not exist" icon={<FolderOpen size={25} />} action={<Link className="button primary" to="/"><ArrowLeft size={16} /> Back to dashboard</Link>}><p>The URL may refer to a home or run that has been removed from navigation.</p></EmptyState></div>;
}
