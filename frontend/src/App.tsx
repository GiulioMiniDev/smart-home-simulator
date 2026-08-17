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
  FolderInput,
  FolderOpen,
  Gauge,
  HardDrive,
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
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Trees,
  Upload,
  UserRound,
  Users,
  Wrench,
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from "lucide-react";
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clearSession, download, eventSourceUrl, health } from "./api";
import {
  Breadcrumbs,
  ConfirmAction,
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
import { useResource, useStoredState, type ResourceState } from "./hooks";
import {
  addObstacle,
  addRoom,
  addSensor,
  dwellingRegionIds,
  movePlanObject,
  pirRange,
  removeSelection,
  resizePlanObject,
  setPirRange,
} from "./editor";
import type { ResizeHandle } from "./editor";
import { authoringPrompts } from "./prompts";
import type {
  BehaviourSlice,
  Configuration,
  DestinationCheck,
  DiaryEntry,
  ExportManifest,
  ExportRecord,
  HomeDetail,
  HomeModel,
  HomeSummary,
  JobEvent,
  JobRecord,
  MaintenanceSummary,
  Observation,
  Overview,
  PathSource,
  ResidentProfile,
  SensorModel,
  StorageReport,
  TimelineEvent,
  VolumeUsage,
  WorkspaceIntegrity,
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

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(size < 10 ? 1 : 0)} ${units[unit]}`;
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
  // Collapsing the navigation is a preference about this workspace, so it outlives the tab.
  const [navCollapsed, setNavCollapsed] = useStoredState("habitat-lab-nav-collapsed", false);
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
      navCollapsed={navCollapsed}
      onNavCollapse={() => setNavCollapsed(!navCollapsed)}
    >
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/generate" element={<GeneratePage />} />
        <Route path="/homes" element={<HomesPage />} />
        <Route path="/homes/:homeId" element={<HomePage />} />
        <Route path="/residents" element={<ResidentsPage />} />
        <Route path="/simulations" element={<SimulationsPage />} />
        <Route path="/simulations/:runId" element={<RunPage />} />
        <Route path="/exports" element={<ExportsPage />} />
        <Route path="/maintenance" element={<MaintenancePage />} />
        <Route path="/settings" element={<SettingsPage />} />
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
  const active = jobs.filter((job) => Boolean(job.homeId) && (job.status === "queued" || job.status === "running"));
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
          <div><strong>Workspace opened in diagnostic mode</strong><p>One or more files are still in the folder but hold content the catalogue does not vouch for, so what a run executed can no longer be established. New publication is paused until that is resolved — files you deleted yourself are not the cause and are reconciled automatically.</p></div>
          <Link className="button secondary" to="/maintenance"><Wrench size={16} /> Open maintenance</Link>
        </div>
      )}
      {!workspace.diagnosticMode && resource.data.lastRepair && (
        <div className="notice" role="status">
          <Wrench size={18} />
          <span>
            <strong>The workspace folder changed since the last session.</strong>{" "}
            {resource.data.lastRepair.details.join("; ")}.
            {resource.data.lastRepair.bytesFreed > 0 && ` ${formatBytes(resource.data.lastRepair.bytesFreed)} reclaimed.`}
          </span>
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

interface GenerationReview {
  name: string;
  age: number;
  city: string;
  recurringActivities: number;
  days: number;
  traceEntries: number;
}

async function loadGenerationReview(jobId: string): Promise<GenerationReview> {
  const base = `/generation/${encodeURIComponent(jobId)}/artifact`;
  const persona = await api<{ name: string; age: number; city: string }>(`${base}/persona.json`);
  const profile = await api<{ recurringActivities: unknown[] }>(`${base}/behavioral-profile.json`);
  const manifest = await api<{ runs: unknown[] }>(`${base}/batch-manifest.json`);
  const trace = await api<{ entries: unknown[] }>(`${base}/planned-activity-trace.json`);
  return {
    name: persona.name,
    age: persona.age,
    city: persona.city,
    recurringActivities: profile.recurringActivities.length,
    days: manifest.runs.length,
    traceEntries: trace.entries.length,
  };
}

function useJobStream(jobId: string | undefined, active: boolean, reload: () => Promise<void>) {
  useEffect(() => {
    if (!jobId || !active) return;
    let disposed = false;
    let source: EventSource | undefined;
    void eventSourceUrl(jobId).then((url) => {
      if (disposed) return;
      source = new EventSource(url);
      const refresh = () => void reload();
      source.addEventListener("progress", refresh);
      source.addEventListener("status", refresh);
      source.addEventListener("done", () => {
        refresh();
        source?.close();
      });
    });
    return () => {
      disposed = true;
      source?.close();
    };
  }, [jobId, active, reload]);
}

function GeneratePage() {
  const [brief, setBrief] = useState("");
  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [months, setMonths] = useState(1);
  const [useLlmDays, setUseLlmDays] = useState(true);
  const [useLlmPackage, setUseLlmPackage] = useState(false);
  const [focusId, setFocusId] = useState<string>();
  const [starting, setStarting] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string>();
  const [review, setReview] = useState<GenerationReview>();
  const navigate = useNavigate();

  const generations = useResource<JobRecord[]>("/generations");
  const genDetail = useResource<{ job: JobRecord }>(focusId ? `/jobs/${focusId}` : undefined);
  const job = genDetail.data?.job;
  const genActive = job ? !terminal.has(job.status) : false;
  // Only homeId identifies the published home: a generation from before the home workflow carries
  // its own job id in resultReference, which would link to a home that does not exist.
  const homeId = job?.status === "completed" ? job.homeId : undefined;
  // The generated home is where the planimetry lives; reviewing it here saves the researcher from
  // discovering the house they are about to simulate only after opening another page.
  const homeDetail = useResource<HomeDetail>(homeId ? `/homes/${homeId}` : undefined);
  const plan = homeDetail.data?.models.homeModel;
  const planApproved = homeDetail.data?.planApproval?.approved ?? false;

  useJobStream(focusId, genActive, genDetail.reload);

  useEffect(() => {
    if (!focusId || job?.status !== "completed") {
      setReview(undefined);
      return;
    }
    void loadGenerationReview(focusId).then(setReview).catch(() => setReview(undefined));
  }, [focusId, job?.status]);

  const start = async () => {
    setStarting(true);
    setError(undefined);
    try {
      const created = await api<JobRecord>("/generation", {
        method: "POST",
        body: JSON.stringify({
          brief,
          start_date: startDate,
          months,
          use_llm_days: useLlmDays,
          use_llm_package: useLlmPackage,
        }),
      });
      setFocusId(created.jobId);
      await generations.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setStarting(false);
    }
  };

  const openGeneration = (id: string) => {
    setFocusId(id);
    setError(undefined);
  };

  const confirmPlan = async () => {
    if (!homeId) return;
    setConfirming(true);
    setError(undefined);
    try {
      await api(`/homes/${homeId}/plan-approval`, { method: "POST" });
      await homeDetail.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setConfirming(false);
    }
  };

  // Generations made before the home workflow kept their artifacts; publishing them is a
  // recovery path, not a second way of working.
  const publish = async () => {
    if (!focusId) return;
    setPublishing(true);
    setError(undefined);
    try {
      const result = await api<{ homeId: string }>(`/generation/${focusId}/publish`, { method: "POST" });
      navigate(`/homes/${result.homeId}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPublishing(false);
    }
  };

  const past = (generations.data ?? []).filter((item) => item.status === "completed");

  return (
    <div className="page">
      <PageHeader
        eyebrow="Local generation"
        title="Generate a home input from a brief"
        description="Invent a person, their habits and a horizon of simulatable days — entirely on your machine. Generation never simulates: it publishes a home whose inputs you can review, edit and then run like any other."
      />
      <div className="generate-grid">
        <section className="panel generate-form">
          <label className="case-description">
            <span>Person and case brief</span>
            <textarea
              aria-label="Person and case brief"
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              placeholder="Example: an elderly woman living alone in Bologna, a former teacher with arthritis."
            />
          </label>
          <div className="generate-fields">
            <label>
              <span>Start date</span>
              <input type="date" aria-label="Start date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </label>
            <label>
              <span>Horizon</span>
              <select aria-label="Horizon" value={months} onChange={(event) => setMonths(Number(event.target.value))}>
                {[1, 3, 6, 12].map((value) => (
                  <option key={value} value={value}>{value} month{value > 1 ? "s" : ""}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="generate-toggle">
            <input type="checkbox" checked={useLlmDays} onChange={(event) => setUseLlmDays(event.target.checked)} />
            <span>Arrange days with the local LLM — varied and richer, but slower.</span>
          </label>
          <label className="generate-toggle">
            <input type="checkbox" checked={useLlmPackage} onChange={(event) => setUseLlmPackage(event.target.checked)} />
            <span>Author the process package with the LLM (optional; low mining value).</span>
          </label>
          <button className="button primary" disabled={!brief.trim() || starting || genActive} onClick={() => void start()}>
            <Sparkles size={16} /> {starting || genActive ? "Generating…" : "Generate"}
          </button>
          {error && <ErrorPanel message={error} />}
          {past.length > 0 && (
            <div className="past-generations">
              <p className="eyebrow">Past generations</p>
              <ul>
                {past.map((item) => (
                  <li key={item.jobId}>
                    <button
                      type="button"
                      className={`ghost-row ${item.jobId === focusId ? "is-active" : ""}`}
                      onClick={() => openGeneration(item.jobId)}
                    >
                      <Clock3 size={15} />
                      <span>{formatDate(item.finishedAt ?? item.requestedAt)}</span>
                      <small>{item.jobId}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
        <section className="panel">
          {!job && (
            <EmptyState title="No generation selected" icon={<Sparkles size={25} />}>
              <p>Describe a person and start, or open a past generation. Nothing is simulated until you run it from its home.</p>
            </EmptyState>
          )}
          {job && (
            <div className="generate-status">
              <div className="section-heading">
                <div><p className="eyebrow">Generation job</p><h2>{job.progress.phase.replaceAll("_", " ")}</h2></div>
                <StatusBadge status={job.status} />
              </div>
              <ProgressBar value={job.progress.percent} label={job.progress.message} />
              {job.status === "failed" && <ErrorPanel message={job.errorMessage ?? job.progress.message} />}
              {review && (
                <div className="generate-review">
                  <div className="metric-row">
                    <Metric label="Resident" value={review.name} detail={`${review.age} · ${review.city}`} />
                    <Metric label="Recurring activities" value={review.recurringActivities} detail="ground truth" />
                    <Metric label="Days" value={review.days} detail="simulatable" />
                    <Metric label="Trace entries" value={review.traceEntries} detail="planned" />
                  </div>
                  {homeId ? (
                    <>
                      {plan && (
                        <div className="plan-preview">
                          <div className="plan-preview-heading">
                            <div>
                              <p className="eyebrow">{planApproved ? "Approved plan" : "Recommended plan"}</p>
                              <h3>{plan.regions.length} rooms, {plan.entities.length} providers, {homeDetail.data?.models.sensorModel?.sensors.length ?? 0} sensors</h3>
                            </div>
                            {!planApproved && <span className="recommended-badge"><Sparkles size={13} aria-hidden="true" /> Recommended</span>}
                          </div>
                          <PlanCanvas home={plan} sensors={homeDetail.data?.models.sensorModel} />
                          <p className="hint">
                            {planApproved
                              ? "This is the plan the runs of this home execute."
                              : "Rooms, furniture and sensors proposed by the deterministic policies. Confirm it, or open the home to move walls, furniture and PIRs before simulating."}
                          </p>
                          <div className="button-row">
                            {!planApproved && (
                              <button
                                className="button primary"
                                disabled={confirming}
                                onClick={() => void confirmPlan()}
                              >
                                <ShieldCheck size={16} /> {confirming ? "Confirming…" : "Confirm plan"}
                              </button>
                            )}
                            <Link className={`button ${planApproved ? "primary" : "secondary"}`} to={`/homes/${homeId}`}>
                              <HomeIcon size={16} /> {planApproved ? "Open the home and run the simulation" : "Edit the plan"}
                            </Link>
                          </div>
                        </div>
                      )}
                      {!plan && (
                        <>
                          <div className="guide-callout">
                            <ShieldCheck size={19} />
                            <p><strong>Published as a home input.</strong> The persona, its process package and the whole horizon of days are now an ordinary workspace home, with its executable plan and sensor field already validated.</p>
                          </div>
                          <Link className="button primary" to={`/homes/${homeId}`}>
                            <HomeIcon size={16} /> Open the home and run the simulation
                          </Link>
                        </>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="guide-callout">
                        <AlertCircle size={19} />
                        <p><strong>This generation published no home yet.</strong> It was produced before generations became home inputs. Its days are still on disk, so it can be published now without generating again.</p>
                      </div>
                      <button className="button primary" disabled={publishing} onClick={() => void publish()}>
                        <HomeIcon size={16} /> {publishing ? "Publishing…" : "Publish as a home"}
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/**
 * What the browser knows about a request it has sent and not yet got back.
 *
 * `reading` and `sending` are local facts. `working` is the server confirming it still holds the
 * operation, and is the only phase that can report a stage. `lost` is the case that used to be
 * indistinguishable from the others: the request is gone and nothing is ever coming back.
 */
type OperationProgress = {
  operationId: string;
  label: string;
  phase: "reading" | "sending" | "working" | "lost";
  startedAt: number;
  elapsed: number;
  stage?: string;
  serverElapsed?: number;
  reason?: string;
};

const HEALTH_POLL_MS = 3000;
// A finished handler leaves the in-flight table before its reply has finished being written, so a
// single miss means nothing. Three consecutive ones, six seconds apart from the answer, do.
const MISSES_BEFORE_LOST = 3;

function useOperationWatch(
  progress: OperationProgress | undefined,
  setProgress: Dispatch<SetStateAction<OperationProgress | undefined>>,
) {
  const misses = useRef(0);
  const operationId = progress?.operationId;
  const settled = progress?.phase === "lost";
  useEffect(() => {
    if (!operationId || settled) return;
    misses.current = 0;
    let cancelled = false;
    let sincePoll = 0;
    const patch = (change: Partial<OperationProgress>) =>
      setProgress((current) => (current?.operationId === operationId ? { ...current, ...change } : current));

    const timer = window.setInterval(() => {
      patch({ elapsed: Math.round((Date.now() - (progress?.startedAt ?? Date.now())) / 1000) });
      sincePoll += 1000;
      if (sincePoll < HEALTH_POLL_MS) return;
      sincePoll = 0;
      void health(operationId).then((state) => {
        if (cancelled) return;
        if (state === null) {
          patch({ phase: "lost", reason: "The server is not answering at all — the process is gone." });
          return;
        }
        if (state.operation) {
          misses.current = 0;
          patch({ phase: "working", stage: state.operation.stage, serverElapsed: state.operation.elapsedSeconds });
          return;
        }
        misses.current += 1;
        if (misses.current >= MISSES_BEFORE_LOST) {
          patch({
            phase: "lost",
            reason: "The server is answering but is no longer working on this request, so no reply is coming.",
          });
        }
      });
    }, 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [operationId, settled, progress?.startedAt, setProgress]);
}

function OperationPanel({ progress }: { progress: OperationProgress }) {
  const spent = `${progress.elapsed}s`;
  const description =
    progress.phase === "reading" ? "Reading the file in the browser"
      : progress.phase === "sending" ? "Sent to the server, waiting for it to pick the request up"
        : progress.phase === "working" ? (progress.stage ?? "The server is working on it")
          : (progress.reason ?? "The request was lost.");
  return (
    <section className={`operation-panel${progress.phase === "lost" ? " operation-panel-lost" : ""}`} role="status" aria-live="polite">
      <div>
        {progress.phase === "lost" ? <AlertCircle size={18} /> : <Clock3 size={18} />}
        <strong>{progress.label}</strong>
        <span className="operation-elapsed">{spent}</span>
      </div>
      <p>{description}</p>
      {progress.phase !== "lost" && <div className="operation-track" aria-hidden="true"><i /></div>}
      {progress.phase === "working" && <small>The server confirmed it is alive and {progress.serverElapsed ?? progress.elapsed}s into this request.</small>}
      {progress.phase === "lost" && <p className="operation-hint">Check the console window the simulator was started from, and <code>server-errors.log</code> in the workspace folder. Nothing was imported.</p>}
    </section>
  );
}

function HomePage() {
  const { homeId = "" } = useParams();
  const navigate = useNavigate();
  const resource = useResource<HomeDetail>(`/homes/${homeId}`);
  const [tab, setTab] = useState<"overview" | "home" | "sensors" | "runs">("overview");
  const [selectedId, setSelectedId] = useState<string>();
  const [bundleFile, setBundleFile] = useState<File>();
  const [outlineFile, setOutlineFile] = useState<File>();
  const [scenarioFile, setScenarioFile] = useState<File>();
  const [behaviorFile, setBehaviorFile] = useState<File>();
  const [working, setWorking] = useState(false);
  const [progress, setProgress] = useState<OperationProgress>();
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string }>();
  useOperationWatch(progress, setProgress);
  const [homeDraft, setHomeDraft] = useState<HomeModel>();
  const [sensorDraft, setSensorDraft] = useState<SensorModel>();
  const [history, setHistory] = useState<Array<{ home?: HomeModel; sensor?: SensorModel }>>([]);
  const [future, setFuture] = useState<Array<{ home?: HomeModel; sensor?: SensorModel }>>([]);
  const [viewport, setViewport] = useState({ zoom: 1, x: 0, y: 0 });
  // Every edit passes through `snapshot`, so it is also where the drafts start diverging from what
  // the workspace holds. Publishing is what makes them agree again.
  const [unsaved, setUnsaved] = useState(false);
  // The plan is the house. Supermarket, bar and the relative's flat exist in the model so the
  // resident has somewhere to be when they are out; they are shown only when explicitly asked for.
  const [showExternalPlaces, setShowExternalPlaces] = useState(false);
  useJobRefresh(resource.data?.jobs ?? [], resource.reload);
  const sourceHome = resource.data?.models.homeModel;
  const sourceSensor = resource.data?.models.sensorModel;
  useEffect(() => {
    // Anything that reloads the home reseeds the drafts from the server — and a run in progress
    // reloads it on every progress event. Reseeding over unpublished edits threw away the wall
    // somebody had just moved, silently, while they were still looking at it.
    if (unsaved) return;
    if (sourceHome) setHomeDraft(structuredClone(sourceHome));
    if (sourceSensor) setSensorDraft(structuredClone(sourceSensor));
  }, [sourceHome, sourceSensor, unsaved]);
  if (resource.loading) return <div className="page"><Skeleton lines={8} /></div>;
  if (resource.error || !resource.data) return <div className="page"><ErrorPanel message={resource.error?.message ?? "Home not found"} onRetry={() => void resource.reload()} /></div>;
  const detail = resource.data;
  const activeJob = detail.jobs.find((job) => !terminal.has(job.status));
  const inputResident = detail.residents.find((resident) => resident.scenarioArtifactId && resident.behaviorArtifactId);

  const submitAuthoring = async (path: string, body: () => Promise<Record<string, unknown>>, label: string) => {
    const operationId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    setWorking(true); setNotice(undefined);
    setProgress({ operationId, label, phase: "reading", startedAt: Date.now(), elapsed: 0 });
    try {
      const payload = JSON.stringify(await body());
      setProgress((current) => current?.operationId === operationId ? { ...current, phase: "sending" } : current);
      const result = await api<{ valid: boolean; issues?: ImportIssue[]; message?: string; expansion?: { dayCount: number; activityCount: number; habitBandCount: number }; bundleArtifact?: { artifactId: string } }>(`/homes/${homeId}/${path}`, {
        method: "POST",
        body: payload,
        headers: { "X-Operation-Id": operationId },
      });
      // An outline can be refused before any day exists, and then there are no per-activity
      // issues to summarize — only one sentence saying what the structure got wrong.
      if (!result.valid) setNotice({ kind: "error", text: result.message ?? summarizeIssues(result.issues ?? []) });
      else {
        const expanded = result.expansion
          ? ` Expanded into ${result.expansion.dayCount} days, ${result.expansion.activityCount} activities and ${result.expansion.habitBandCount} habit bands.`
          : "";
        setNotice({ kind: "success", text: `The complete authoring bundle passed validation, compilation and behavior compatibility gates.${expanded}` });
        await resource.reload();
      }
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); setProgress(undefined); }
  };
  const importBundle = async () => {
    if (!bundleFile) return;
    await submitAuthoring("authoring-bundle", () => readJson(bundleFile), "Validating the authoring bundle");
  };
  const importOutline = async () => {
    if (!outlineFile) return;
    await submitAuthoring("horizon-outline?seed=1", () => readJson(outlineFile), "Expanding and importing the outline");
  };
  const importAdvancedInputs = async () => {
    if (!scenarioFile || !behaviorFile) return;
    await submitAuthoring("authoring", async () => ({
      scenario: await readJson(scenarioFile),
      personal_process_package: await readJson(behaviorFile),
    }), "Validating the Advanced import");
  };
  const start = async (path: "runs" | "environment", message: string) => {
    if (!inputResident?.scenarioArtifactId || !inputResident.behaviorArtifactId) return;
    setWorking(true); setNotice(undefined);
    try {
      await api(`/homes/${homeId}/${path}`, { method: "POST", body: JSON.stringify({ scenario_artifact_id: inputResident.scenarioArtifactId, behavior_artifact_id: inputResident.behaviorArtifactId }) });
      setNotice({ kind: "success", text: message });
      await resource.reload();
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  const startRun = () => start("runs", "The run was queued in an isolated local worker.");
  // Building the environment on its own is what makes the plan reviewable before it is executed.
  const startEnvironment = () => start("environment", "Building the home and its sensor field. Nothing is executed until you start a run.");
  const currentSnapshot = () => ({ home: homeDraft ? structuredClone(homeDraft) : undefined, sensor: sensorDraft ? structuredClone(sensorDraft) : undefined });
  const snapshot = () => { setHistory((items) => [...items.slice(-49), currentSnapshot()]); setFuture([]); setUnsaved(true); };
  // Pointer and keyboard move the same objects through the same geometry: dragging the bed and
  // nudging it with the arrows must not leave the plan in two different shapes.
  const moveSelected = (id: string | undefined, dx: number, dy: number) => {
    if (!homeDraft || !id) return;
    const result = movePlanObject(homeDraft, sensorDraft, id, dx, dy);
    setHomeDraft(result.home);
    if (result.sensors) setSensorDraft(result.sensors);
  };
  const nudgeSelected = (dx: number, dy: number) => {
    snapshot();
    moveSelected(selectedId, dx, dy);
  };
  const resizeSelected = (id: string, handle: ResizeHandle, dx: number, dy: number) => {
    if (!homeDraft) return;
    const result = resizePlanObject(homeDraft, sensorDraft, id, handle, dx, dy);
    setHomeDraft(result.home);
    if (result.sensors) setSensorDraft(result.sensors);
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
      else { setNotice({ kind: "success", text: `${kind === "home" ? "Plan" : "Sensor field"} validated and published. Every run of this home now executes it.` }); setHistory([]); setFuture([]); setUnsaved(false); await resource.reload(); }
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  // Accepting the proposal untouched is a decision like any edit: from here on the runs execute
  // this plan instead of asking the policy for a new one.
  const confirmPlan = async () => {
    setWorking(true); setNotice(undefined);
    try {
      await api(`/homes/${homeId}/plan-approval`, { method: "POST" });
      setNotice({ kind: "success", text: "Plan confirmed. Every run of this home now executes it as it stands." });
      await resource.reload();
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setWorking(false); }
  };
  const removeHome = async () => {
    setWorking(true); setNotice(undefined);
    try {
      const summary = await api<MaintenanceSummary>(`/homes/${homeId}`, { method: "DELETE" });
      navigate("/homes", { state: { removed: summary } });
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); setWorking(false); }
  };
  const recommended = !!homeDraft && detail.planApproval?.approved === false;
  return (
    <div className="page home-page">
      <Breadcrumbs items={[{ label: "Homes", to: "/homes" }, { label: detail.home.name }]} />
      <PageHeader eyebrow="Environment workspace" title={detail.home.name} description={detail.home.description || "Executable spatial model and resident context"} actions={<><StatusBadge status={activeJob?.status ?? (homeDraft ? "valid" : "draft")} /><button className="button primary" disabled={!inputResident || !!activeJob || working} onClick={() => void startRun()}><Play size={16} /> Run simulation</button><ConfirmAction label="Delete home" title={`Delete “${detail.home.name}”?`} consequence={`Its ${detail.residents.length} resident context(s), ${detail.jobs.length} run(s), every export built from them and the stored inputs only this home uses are deleted from the workspace folder. This cannot be undone.`} busy={working} disabled={!!activeJob} onConfirm={removeHome} /></>} />
      {notice && <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.kind === "success" ? <Check size={18} /> : <AlertCircle size={18} />}<span>{notice.text}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice(undefined)}><X size={16} /></button></div>}
      {progress && <OperationPanel progress={progress} />}
      {recommended && (
        <section className="plan-review" aria-labelledby="plan-review-title">
          <div>
            <p className="eyebrow"><Sparkles size={14} aria-hidden="true" /> Recommended</p>
            <h2 id="plan-review-title">This planimetry is a proposal</h2>
            <p>
              Rooms, furniture and sensors were derived from the scenario by the deterministic
              policies. Confirm it as it stands, or open the plan and move walls, furniture and PIRs
              — either way, what you accept is what every run of this home executes.
            </p>
          </div>
          <div className="button-row">
            <button className="button primary" disabled={working} onClick={() => void confirmPlan()}>
              <ShieldCheck size={16} /> Confirm this plan
            </button>
            <button className="button secondary" onClick={() => setTab("home")}>
              <RouteIcon size={16} /> Edit the plan
            </button>
          </div>
        </section>
      )}
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
            <Link className="import-guide-link" to="/help#authoring"><BookOpen size={18} /><span><strong>Need to generate the file?</strong><small>Open the integrated guide and copy the horizon outline prompt.</small></span></Link>
            <label className="file-picker bundle-picker"><FileJson size={22} /><span><strong>Simulation authoring bundle</strong><small>{bundleFile?.name ?? "Choose the complete authoring-bundle.json"}</small></span><input type="file" accept="application/json,.json" onChange={(event) => setBundleFile(event.target.files?.[0])} /></label>
            <label className="file-picker bundle-picker"><FileJson size={22} /><span><strong>Horizon outline</strong><small>{outlineFile?.name ?? "A structure for a long horizon; the days are computed here"}</small></span><input type="file" accept="application/json,.json" aria-label="Horizon outline" onChange={(event) => setOutlineFile(event.target.files?.[0])} /></label>
            <button className="button secondary" disabled={!outlineFile || working} onClick={() => void importOutline()}>Expand and import outline</button>
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
          </div>}
        </section>
        <section className="surface evidence-sheet">
          <div className="section-heading"><div><p className="eyebrow">Environment state</p><h2>Authoritative revisions</h2></div><ShieldCheck size={21} /></div>
          <dl className="definition-list"><div><dt>Home model</dt><dd>{detail.home.currentHomeArtifactId ? <><StatusBadge status="valid" /><code>{detail.home.currentHomeArtifactId}</code></> : <StatusBadge status="draft" />}</dd></div><div><dt>Sensor model</dt><dd>{detail.home.currentSensorArtifactId ? <><StatusBadge status="valid" /><code>{detail.home.currentSensorArtifactId}</code></> : <StatusBadge status="draft" />}</dd></div>{detail.generation && <div><dt>Generated horizon</dt><dd><StatusBadge status="valid" /><span>{detail.generation.dayCount} days, each compiled and bundled separately</span></dd></div>}<div><dt>Runs</dt><dd>{detail.jobs.length}</dd></div></dl>
          {detail.generation && <p className="hint">Running this home simulates every generated day and publishes them as one run: a single trace, one observable sensor log and one oracle mapping to export whole.</p>}
          {!homeDraft && inputResident && <>
            <p className="hint">The plan and the sensor field come from the deterministic policies, not from the execution. Building them first lets you move a wall or a PIR before anything is simulated — and what you approve is what the run then executes.</p>
            <div className="button-row">
              <button className="button primary" disabled={working || !!activeJob} onClick={() => void startEnvironment()}><HomeIcon size={16} /> Generate home and sensors</button>
              <button className="button secondary" disabled={working || !!activeJob} onClick={() => void startRun()}><RouteIcon size={16} /> Generate and run in one step</button>
            </div>
          </>}
        </section>
      </div>}
      {(tab === "home" || tab === "sensors") && <div className="editor-layout">
        <section className="editor-stage">
          <div className="editor-toolbar"><div><button className="tool-button" disabled={!history.length} onClick={undo}><RotateCcw size={16} /> Undo</button><button className="tool-button" disabled={!future.length} onClick={redo}><RotateCw size={16} /> Redo</button><button className="tool-button" aria-pressed="true"><Square size={15} /> Select</button>{tab === "home" ? <><button className="tool-button" disabled={!homeDraft} onClick={() => addEditorObject("room")}><Plus size={15} /> Room</button><button className="tool-button" disabled={!homeDraft} onClick={() => addEditorObject("obstacle")}><Plus size={15} /> Obstacle</button></> : <>{(["pir", "contact", "temperature"] as const).map((kind) => <button key={kind} className="tool-button" disabled={!homeDraft || !sensorDraft} onClick={() => addEditorObject(kind)}><Plus size={15} /> {kind}</button>)}</>}<label className="tool-button file-tool"><Upload size={15} /> Import {tab === "home" ? "home" : "sensors"}<input type="file" accept="application/json,.json" onChange={(event) => void importModel(tab === "home" ? "home" : "sensor", event.target.files?.[0])} /></label></div><div className="viewport-tools" aria-label="Plan viewport"><button className="tool-button" aria-pressed={showExternalPlaces} onClick={() => setShowExternalPlaces(!showExternalPlaces)} title="The places the resident travels to are regions of the model, not rooms of the house."><Trees size={15} /> External places</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, zoom: Math.max(.4, item.zoom / 1.25) }))} aria-label="Zoom out"><ZoomOut size={15} /></button><button className="tool-button" onClick={() => setViewport({ zoom: 1, x: 0, y: 0 })} aria-label="Fit plan"><Maximize2 size={15} /></button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, zoom: Math.min(12, item.zoom * 1.25) }))} aria-label="Zoom in"><ZoomIn size={15} /></button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, x: item.x - 1 }))} aria-label="Pan left">←</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, y: item.y - 1 }))} aria-label="Pan up">↑</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, y: item.y + 1 }))} aria-label="Pan down">↓</button><button className="tool-button" onClick={() => setViewport((item) => ({ ...item, x: item.x + 1 }))} aria-label="Pan right">→</button><span>{Math.round(viewport.zoom * 100)}%</span></div></div>
          {homeDraft ? <PlanCanvas home={homeDraft} sensors={tab === "sensors" ? sensorDraft : undefined} selectedId={selectedId} onSelect={setSelectedId} viewport={viewport} editing={{ onDragStart: snapshot, onMove: moveSelected, onResize: resizeSelected }} showExternalPlaces={showExternalPlaces} onViewport={setViewport} /> : <EmptyState title="No spatial model yet" icon={<RouteIcon size={25} />}><p>Run scenario-first materialization or import a valid home model to open the editor.</p></EmptyState>}
        </section>
        <aside className="inspector" aria-label="Selection inspector">
          <div className="inspector-heading"><div><p className="eyebrow">Inspector</p><h2>{selectedId ?? "Nothing selected"}</h2></div>{selectedId && <button className="icon-button" onClick={() => setSelectedId(undefined)} aria-label="Clear selection"><X size={16} /></button>}</div>
          {selectedId ? <><p className="inspector-help">Use precise keyboard-compatible controls. Publishing creates a new immutable revision and runs authoritative validation.</p><fieldset><legend>Position adjustment</legend><div className="nudge-grid"><span /><button onClick={() => nudgeSelected(0, -0.1)} aria-label="Move up">↑</button><span /><button onClick={() => nudgeSelected(-0.1, 0)} aria-label="Move left">←</button><b>0.1 m</b><button onClick={() => nudgeSelected(0.1, 0)} aria-label="Move right">→</button><span /><button onClick={() => nudgeSelected(0, 0.1)} aria-label="Move down">↓</button><span /></div></fieldset><EditorFields tab={tab} selectedId={selectedId} home={homeDraft} sensors={sensorDraft} onHome={(model) => { snapshot(); setHomeDraft(model); }} onSensors={(model) => { snapshot(); setSensorDraft(model); }} /><div className="inspector-section"><h3>Identity and provenance</h3><code>{selectedId}</code><p>Selection is preserved between the plan, structured tree and validation report.</p><button className="button danger" onClick={removeEditorObject}><Trash2 size={15} /> Remove selected object</button></div></> : <div className="quiet-state"><CircleDot size={22} /><strong>Select an object on the plan</strong><p>Rooms, providers, obstacles and sensors are also reachable with Tab, Enter and Space.</p></div>}
          <div className="inspector-footer">{unsaved && <p className="unsaved-note"><AlertCircle size={14} /> Unpublished edits. Publishing covers this tab only — the plan and the sensor field are separate revisions.</p>}<button className="button primary" disabled={working || !(tab === "home" ? homeDraft : sensorDraft)} onClick={() => void publish(tab === "home" ? "home" : "sensor")}><Save size={16} /> Validate and publish {tab === "home" ? "plan" : "sensors"}{unsaved ? " •" : ""}</button></div>
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
    return <div className="inspector-section editor-fields"><h3>Sensor configuration</h3><div className="field-grid"><label><span>X position</span><input type="number" step="0.1" value={sensor.position.x} onChange={(event) => update({ position: { ...sensor.position, x: event.target.valueAsNumber } })} /></label><label><span>Y position</span><input type="number" step="0.1" value={sensor.position.y} onChange={(event) => update({ position: { ...sensor.position, y: event.target.valueAsNumber } })} /></label><label><span>Latency ms</span><input type="number" min="0" value={sensor.timing.latencyMilliseconds} onChange={(event) => timing("latencyMilliseconds", event.target.valueAsNumber)} /></label><label><span>Jitter ms</span><input type="number" min="0" value={sensor.timing.clockJitterMilliseconds} onChange={(event) => timing("clockJitterMilliseconds", event.target.valueAsNumber)} /></label><label><span>Cooldown ms</span><input type="number" min="0" value={sensor.timing.cooldownMilliseconds} onChange={(event) => timing("cooldownMilliseconds", event.target.valueAsNumber)} /></label><label><span>Dropout 0–1</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.dropoutProbability} onChange={(event) => error("dropoutProbability", event.target.valueAsNumber)} /></label><label><span>False negative 0–1</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.falseNegativeProbability} onChange={(event) => error("falseNegativeProbability", event.target.valueAsNumber)} /></label><label><span>False positives/day</span><input type="number" min="0" max="1" step="0.001" value={sensor.errorModel.falsePositiveProbabilityPerDay} onChange={(event) => error("falsePositiveProbabilityPerDay", event.target.valueAsNumber)} /></label><label><span>Noise σ</span><input type="number" min="0" step="0.01" value={sensor.errorModel.measurementNoiseStandardDeviation} onChange={(event) => error("measurementNoiseStandardDeviation", event.target.valueAsNumber)} /></label>{sensor.sensorType === "pir" && <><label><span>Range m</span><input type="number" min="0.2" max="12" step="0.1" value={pirRange(sensor)} onChange={(event) => onSensors(setPirRange(sensors, home, sensor.sensorId, event.target.valueAsNumber))} /></label><label><span>Hold ms</span><input type="number" min="1" step="100" value={Number(sensor.holdMilliseconds ?? 30000)} onChange={(event) => update({ holdMilliseconds: event.target.valueAsNumber })} /></label></>}{sensor.sensorType === "temperature" && <><label><span>Region</span><select value={String(sensor.regionId)} onChange={(event) => update({ regionId: event.target.value })}>{home.regions.map((item) => <option key={item.regionId}>{item.regionId}</option>)}</select></label><label><span>Baseline °C</span><input type="number" step="0.1" value={Number(sensor.baselineCelsius)} onChange={(event) => update({ baselineCelsius: event.target.valueAsNumber })} /></label></>}{sensor.sensorType === "contact" && <label><span>Entity</span><select value={String(sensor.entityId)} onChange={(event) => update({ entityId: event.target.value })}>{home.entities.map((item) => <option key={item.entityId}>{item.entityId}</option>)}</select></label>}</div><div className="failure-editor"><div><h4>Failure windows</h4><button className="button secondary" onClick={addFailure}><Plus size={14} /> Add window</button></div>{sensor.failureWindows.length ? sensor.failureWindows.map((window, index) => <div className="failure-window" key={`${window.startsAt}-${index}`}><label><span>Starts</span><input type="datetime-local" value={window.startsAt.slice(0, 16)} onChange={(event) => setFailure(index, "startsAt", event.target.value)} /></label><label><span>Ends</span><input type="datetime-local" value={window.endsAt.slice(0, 16)} onChange={(event) => setFailure(index, "endsAt", event.target.value)} /></label><button className="icon-button" aria-label={`Remove failure window ${index + 1}`} onClick={() => update({ failureWindows: sensor.failureWindows.filter((_, itemIndex) => itemIndex !== index) })}><Trash2 size={14} /></button></div>) : <p>No planned dropout interval. Random dropout remains controlled by the probability above.</p>}</div></div>;
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
  const jobs = resource.data?.filter((job) => Boolean(job.homeId) && (filter === "all" || job.status === filter)) ?? [];
  return <div className="page"><PageHeader eyebrow="Execution centre" title="Simulations" description="Persistent local jobs, actual backend phases and independently verified artifacts." actions={<div className="select-wrap"><Filter size={15} /><select aria-label="Filter by status" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All statuses</option>{["queued", "running", "completed", "failed", "cancelled", "interrupted"].map((status) => <option value={status} key={status}>{status}</option>)}</select><ChevronDown size={14} /></div>} />{resource.loading ? <Skeleton lines={7} /> : resource.error ? <ErrorPanel message={resource.error.message} onRetry={() => void resource.reload()} /> : <RunTable jobs={jobs} empty={filter === "all" ? "Create a home and start its first deterministic simulation." : `No ${filter} runs.`} />}</div>;
}

interface JobDetail { job: JobRecord; events: JobEvent[]; artifacts: Record<string, { artifactId: string; role: string; sha256: string; sizeBytes: number }> }

function RunPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const detail = useResource<JobDetail>(`/jobs/${runId}`);
  useJobRefresh(detail.data ? [detail.data.job] : [], detail.reload);
  const [tab, setTab] = useState<"summary" | "diary" | "profile" | "observations" | "replay" | "artifacts">("summary");
  const [oracle, setOracle] = useState(false);
  const [selectedDiary, setSelectedDiary] = useState<string>();
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent>();
  const [playing, setPlaying] = useState(false);
  const [exportNotice, setExportNotice] = useState<string>();
  const [exportManifest, setExportManifest] = useState<ExportManifest>();
  // An environment job publishes a plan and a sensor field and executes nothing, so it completes
  // without a trace: offering the diary or the replay for it would open empty views.
  const evidenceAvailable = detail.data?.job.status === "completed" && detail.data.job.kind !== "environment";
  const diary = useResource<{ items: DiaryEntry[]; total: number }>(evidenceAvailable ? `/runs/${runId}/diary?limit=500` : undefined);
  // Only once the tab is opened: profiling a long horizon is real work, and most visits to a run
  // never ask for it.
  const profile = useResource<ResidentProfile>(evidenceAvailable && tab === "profile" ? `/runs/${runId}/profile` : undefined);
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
  const removeRun = async () => {
    try { await api<MaintenanceSummary>(`/jobs/${runId}`, { method: "DELETE" }); navigate("/simulations"); }
    catch (reason) { setExportNotice(reason instanceof Error ? reason.message : String(reason)); }
  };
  const verify = async () => { try { const result = await api<{ matches: boolean; actualSemanticDigest: string }>(`/runs/${runId}/replay/verify`, { method: "POST" }); setExportNotice(result.matches ? `Replay verified: ${result.actualSemanticDigest}` : "Replay digest did not match"); } catch (reason) { setExportNotice(reason instanceof Error ? reason.message : String(reason)); } };
  const createExport = async () => { try { const result = await api<ExportManifest>(`/runs/${runId}/exports`, { method: "POST", body: JSON.stringify({ runId, formats: ["jsonl", "csv", "xes"], roles: ["observable", "oracle", "activities", "actions", "movements", "state_transitions", "resources", "runtime_events", "plan_deviations", "final_state", "habit_ground_truth", "resident_profile"] }) }); setExportManifest(result); setExportNotice(`Export ${result.exportId} published with ${result.files.length} verified files.`); } catch (reason) { setExportNotice(reason instanceof Error ? reason.message : String(reason)); } };
  return <div className="page run-page">
    <Breadcrumbs items={[{ label: "Simulations", to: "/simulations" }, { label: runId }]} />
    <PageHeader eyebrow="Run evidence" title={runId} description={job.progress.message} actions={<><StatusBadge status={job.status} />{!terminal.has(job.status) ? <button className="button danger" onClick={() => void cancel()}><Square size={15} /> Cancel safely</button> : <ConfirmAction label="Delete run" title="Delete this run and its evidence?" consequence="The execution trace, observable log, oracle mapping and every export built from this run are deleted from the workspace folder. The home and its inputs are untouched." onConfirm={removeRun} />}</>} />
    {!terminal.has(job.status) && <section className="active-run-detail"><div className="phase-orbit" aria-hidden="true"><i /><span>{Math.round(job.progress.percent)}%</span></div><div><p className="eyebrow">Current backend phase</p><h2>{job.progress.phase}</h2><p>{job.progress.message}</p><ProgressBar value={job.progress.percent} label="Overall progress" /></div><ol>{detail.data.events.slice(-6).map((event) => <li key={event.sequence}><time>{formatTime(event.occurredAt)}</time><span>{event.message}</span></li>)}</ol></section>}
    <div className="tabs" role="tablist" aria-label="Run detail sections">{(["summary", "diary", "profile", "observations", "replay", "artifacts"] as const).map((item) => <button key={item} role="tab" aria-selected={tab === item} disabled={!evidenceAvailable && !["summary", "artifacts"].includes(item)} onClick={() => setTab(item)}>{item}</button>)}</div>
    {exportNotice && <div className="notice notice-success" role="status"><Check size={17} /><span>{exportNotice}</span><button className="icon-button" aria-label="Dismiss" onClick={() => setExportNotice(undefined)}><X size={15} /></button></div>}
    {tab === "summary" && <>{job.status === "failed" && <FailureDiagnostics job={job} events={issueEvents} />}<div className="run-summary-grid"><section className="surface"><div className="section-heading"><div><p className="eyebrow">Execution</p><h2>Persistent state</h2></div><Clock3 size={20} /></div><dl className="definition-list"><div><dt>Status</dt><dd><StatusBadge status={job.status} /></dd></div><div><dt>Requested</dt><dd>{formatDate(job.requestedAt)}</dd></div><div><dt>Started</dt><dd>{formatDate(job.startedAt)}</dd></div><div><dt>Finished</dt><dd>{formatDate(job.finishedAt)}</dd></div><div><dt>Worker PID</dt><dd><code>{job.processId ?? "n/a"}</code></dd></div></dl></section><section className="surface"><div className="section-heading"><div><p className="eyebrow">Scientific output</p><h2>{Object.keys(detail.data.artifacts).length} verified artifacts</h2></div><ShieldCheck size={20} /></div><p>{evidenceAvailable ? "Bundle, trace, observations and oracle remain separate and digest-addressable." : job.kind === "environment" ? "This job built the home and its sensor field and executed nothing. Review the plan on the home, then start a run to produce evidence from exactly these models." : "Execution evidence was not published. Diary, observations and replay become available only after a completed run."}</p><div className="button-row"><button className="button primary" disabled={!evidenceAvailable} onClick={() => setTab("diary")}><ListTree size={16} /> Open ground-truth diary</button><button className="button secondary" disabled={!evidenceAvailable} onClick={() => setTab("profile")}><UserRound size={16} /> Read the resident profile</button><button className="button secondary" disabled={!evidenceAvailable} onClick={() => void createExport()}><Download size={16} /> Export complete dataset</button></div></section></div>{exportManifest && <section className="surface export-manifest"><div className="section-heading"><div><p className="eyebrow">Verified export manifest</p><h2>{exportManifest.files.length} files across observable and oracle roles</h2></div><div className="button-row" style={{ margin: 0 }}><button className="button primary" onClick={() => void download(`/exports/${exportManifest.exportId}/zip`, `${exportManifest.exportId}.zip`)}><Download size={15} /> Download ZIP</button><StatusBadge status="valid" /></div></div><p><code>{exportManifest.exportId}</code> · seed {exportManifest.seed} · trace {exportManifest.sourceTraceSemanticDigest.slice(0, 16)}…</p><div className="artifact-table"><div className="artifact-head"><span>Role</span><span>Format</span><span>Records</span><span>Download</span></div>{exportManifest.files.map((file) => <div className="artifact-row" key={file.relativePath}><span>{file.role.replaceAll("_", " ")}</span><code>{file.format}</code><span>{file.recordCount}</span><button className="row-link" onClick={() => void download(`/exports/${exportManifest.exportId}/files/${file.relativePath.split("/").at(-1)}`, file.relativePath.split("/").at(-1) ?? "dataset")}><Download size={15} /> Download</button></div>)}</div></section>}</>}
    {tab === "diary" && <section className="diary-layout"><div className="diary-list"><div className="section-heading"><div><p className="eyebrow">Authoritative execution trace</p><h2>Ground-truth diary</h2></div><span>{diary.data?.total ?? 0} activities</span></div>{diary.loading ? <Skeleton lines={8} /> : diary.error ? <ErrorPanel message={diary.error.message} /> : diary.data?.items?.map((entry) => <button key={entry.activityExecutionId} className={`diary-entry ${selectedDiary === entry.activityExecutionId ? "is-selected" : ""}`} onClick={() => setSelectedDiary(entry.activityExecutionId)}><time>{formatTime(entry.actualStart)}</time><span><strong>{entry.intent.replaceAll("_", " ")}</strong><small>{entry.actorId} · {duration(entry.actualStart, entry.actualEnd)} · {entry.actions.length} actions</small></span><StatusBadge status={entry.status} /></button>)}</div><DiaryInspector entry={diary.data?.items?.find((item) => item.activityExecutionId === selectedDiary) ?? diary.data?.items?.[0]} /></section>}
    {tab === "observations" && <section><div className="observable-toolbar"><div><p className="eyebrow">Sensor projection</p><h2>{oracle ? "Oracle-linked observations" : "Observable device log"}</h2></div><div className="mode-switch" role="group" aria-label="Data visibility"><button aria-pressed={!oracle} onClick={() => setOracle(false)}>Observable</button><button aria-pressed={oracle} onClick={() => setOracle(true)}>Oracle links</button></div></div><p className="mode-explanation">{oracle ? "Identity and activity appear only through the separate oracle mapping." : "This view contains only fields a physical device could expose."}</p>{observations.loading ? <Skeleton lines={8} /> : observations.error ? <ErrorPanel message={observations.error.message} /> : <div className="observation-table"><div className="observation-head"><span>Time</span><span>Sensor</span><span>Measurement</span><span>Value</span><span>Quality</span>{oracle && <span>Ground-truth cause</span>}</div>{observations.data?.items?.map((record) => <div className="observation-row" key={record.observationId}><time>{formatTime(record.observedAt)}</time><span><code>{record.sensorId}</code><small>{record.sensorType}</small></span><span>{record.measurement}</span><strong>{String(record.value)}{record.unit ? ` ${record.unit}` : ""}</strong><StatusBadge status={record.quality} />{oracle && <span className="cause-cell">{record.oracleCause ? <><b>{record.oracleCause.origin.replaceAll("_", " ")}</b><small>{record.oracleCause.residentIds.join(", ") || "No resident identity"} · {record.oracleCause.causeType}</small></> : "No oracle link"}</span>}</div>)}</div>}</section>}
    {tab === "replay" && <section className="replay-workbench"><div className="replay-toolbar"><button className="button secondary" onClick={() => setPlaying(!playing)}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause" : "Play movements"}</button><button className="button secondary" onClick={() => void verify()}><ShieldCheck size={15} /> Verify semantic digest</button><span>{selectedEvent ? `${formatTime(selectedEvent.at)} · ${selectedEvent.label}` : "Select an event on the timeline"}</span></div><div className="replay-stage">{homeModelArtifact ? <ReplayPlan runId={runId} activeMovement={selectedEvent} /> : <EmptyState title="Home artifact unavailable"><p>The plan cannot be reconstructed without the persisted home model.</p></EmptyState>}<aside className="timeline-panel"><div className="section-heading"><div><p className="eyebrow">Synchronized trace</p><h2>Timeline</h2></div><Activity size={19} /></div>{timeline.loading ? <Skeleton lines={7} /> : timeline.error ? <ErrorPanel message={timeline.error.message} /> : timeline.data?.slice(0, 800).map((event) => <button key={event.id} className={`timeline-event kind-${event.kind} ${selectedEvent?.id === event.id ? "is-selected" : ""}`} onClick={() => setSelectedEvent(event)}><time>{formatTime(event.at)}</time><i /><span><strong>{event.label.replaceAll("_", " ")}</strong><small>{event.kind} · {event.actorId}</small></span></button>)}</aside></div></section>}
    {tab === "profile" && <section>{profile.loading ? <Skeleton lines={8} /> : profile.error ? <ErrorPanel message={profile.error.message} /> : profile.data ? <ProfileView runId={runId} profile={profile.data} /> : null}</section>}
    {tab === "artifacts" && <div className="artifact-table"><div className="artifact-head"><span>Role</span><span>Artifact</span><span>Size</span><span>SHA-256</span></div>{Object.entries(detail.data.artifacts).map(([role, artifact]) => <div className="artifact-row" key={artifact.artifactId}><span>{role.replaceAll("_", " ")}</span><code>{artifact.artifactId}</code><span>{new Intl.NumberFormat(undefined, { style: "unit", unit: "megabyte", maximumFractionDigits: 2 }).format(artifact.sizeBytes / 1_000_000)}</span><code title={artifact.sha256}>{artifact.sha256.slice(0, 16)}…</code></div>)}</div>}
  </div>;
}

/** Twelve hues far enough apart to be told apart in an eleven-pixel cell. */
const RHYTHM_HUES = [25, 200, 145, 70, 300, 185, 340, 110, 260, 45, 320, 90];

function minutesLabel(minutes: number): string {
  const total = Math.round(minutes);
  return total >= 60 ? `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, "0")}m` : `${total} min`;
}

/**
 * A row of the day against the clock, drawn as opacity rather than colour.
 *
 * Opacity carries the share because the same markup then reads on both themes: the cell inherits
 * the surrounding colour and only says how much of the slot it holds. The square root is not
 * decoration — at fifteen-minute slots most shares sit under a fifth, and a linear ramp draws a
 * settled routine as an empty grid.
 */
function HeatmapRows({ rows, slotCount }: { rows: Array<{ label: string; shares: number[] }>; slotCount: number }) {
  const cell = 11, height = 19, gutter = 150;
  if (!rows.length) return <p className="hint">Nothing measured in this slice.</p>;
  return <svg className="profile-heatmap" viewBox={`0 0 ${gutter + slotCount * cell} ${22 + rows.length * height}`} role="img" aria-label="Activity against the clock" preserveAspectRatio="xMinYMin meet">
    {Array.from({ length: Math.ceil(slotCount / 8) }, (_, index) => index * 8).map((slot) => <g key={slot}><text className="profile-tick" x={gutter + slot * cell} y={13}>{String(Math.round((slot * 24) / slotCount)).padStart(2, "0")}</text><line className="profile-rule" x1={gutter + slot * cell} y1={22} x2={gutter + slot * cell} y2={22 + rows.length * height} /></g>)}
    {rows.map((row, index) => <g key={row.label} transform={`translate(0 ${22 + index * height})`}>
      <rect className="profile-track" x={gutter} y={0} width={slotCount * cell} height={height} />
      <text className="profile-row-label" x={gutter - 8} y={13.5}>{row.label.replaceAll("_", " ")}</text>
      {row.shares.map((share, slot) => share > 0 ? <rect key={slot} x={gutter + slot * cell} y={0} width={cell} height={height} fill="currentColor" opacity={Math.sqrt(Math.min(share, 1))}><title>{`${row.label.replaceAll("_", " ")} · ${(share * 100).toFixed(0)}%`}</title></rect> : null)}
    </g>)}
  </svg>;
}

/** Which activity owns each slot, and how firmly: the figure a segmentation algorithm is after. */
function RhythmStrip({ slice, order }: { slice: BehaviourSlice; order: Map<string, number> }) {
  const cell = 11;
  return <svg className="profile-rhythm" viewBox={`0 0 ${slice.slots.length * cell} 46`} role="img" aria-label="Dominant activity by slot" preserveAspectRatio="xMinYMin meet">
    {slice.slots.map((slot, index) => <g key={slot.slot}>
      <rect className="profile-track" x={index * cell} y={18} width={cell} height={26} />
      {slot.dominantIntent ? <rect x={index * cell} y={18} width={cell} height={26} fill={`oklch(62% 0.13 ${RHYTHM_HUES[(order.get(slot.dominantIntent) ?? order.size) % RHYTHM_HUES.length]})`} opacity={Math.sqrt(Math.min(slot.dominantShare, 1))}><title>{`${slot.start} · ${slot.dominantIntent.replaceAll("_", " ")} · ${(slot.dominantShare * 100).toFixed(0)}% · ${slot.entropyBits.toFixed(2)} bits`}</title></rect> : null}
    </g>)}
    {slice.slots.filter((_, index) => index % 8 === 0).map((slot) => <text key={slot.slot} className="profile-tick" x={slot.slot * cell} y={12}>{slot.start.slice(0, 2)}</text>)}
  </svg>;
}

function ProfileView({ runId, profile }: { runId: string; profile: ResidentProfile }) {
  const [residentId, setResidentId] = useState(profile.residents[0]?.residentId);
  const [dayType, setDayType] = useState<"all" | "weekday" | "weekend">("all");
  const resident = profile.residents.find((item) => item.residentId === residentId) ?? profile.residents[0];
  if (!resident) return <EmptyState title="No resident behaviour" icon={<Users size={25} />}><p>This trace records no executed activity to profile.</p></EmptyState>;
  const slice = resident.slices.find((item) => item.dayType === dayType) ?? resident.slices[0];
  if (!slice) return <EmptyState title="No resident behaviour" icon={<Users size={25} />}><p>This trace records no executed activity to profile.</p></EmptyState>;
  const shown = slice.intents.slice(0, 24);
  const order = new Map(shown.map((item, index) => [item.intent, index]));
  return <div className="profile-layout">
    <div className="section-heading"><div><p className="eyebrow">Realized behaviour · {profile.startDate} → {profile.endDate}</p><h2>Who this resident is</h2></div><div className="button-row" style={{ margin: 0 }}><button className="button secondary" onClick={() => void download(`/runs/${runId}/profile/page`, `${runId}-resident-profile.html`)}><Download size={15} /> Download page</button></div></div>
    <p>Aggregated from the authoritative execution trace, not from the plan: this is what the person did, deviations included. Shares are measured against observed time, so a partial first day cannot read as an empty morning.</p>
    <div className="profile-controls">
      {profile.residents.length > 1 && <div className="mode-switch" role="group" aria-label="Resident">{profile.residents.map((item) => <button key={item.residentId} aria-pressed={item.residentId === resident.residentId} onClick={() => setResidentId(item.residentId)}>{item.residentId.replaceAll("_", " ")}</button>)}</div>}
      <div className="mode-switch" role="group" aria-label="Class of day">{(["all", "weekday", "weekend"] as const).map((item) => <button key={item} aria-pressed={dayType === item} disabled={!resident.slices.find((entry) => entry.dayType === item)?.dayCount} onClick={() => setDayType(item)}>{item === "all" ? "Every day" : item === "weekday" ? "Weekdays" : "Weekends"}</button>)}</div>
      <span className="hint">{slice.dayCount} day(s) · {slice.activityCount} activities · {minutesLabel(slice.observedMinutes)} observed · {profile.slotMinutes} min slots</span>
    </div>
    <ul className="profile-narrative">{resident.narrative.map((line) => <li key={line}>{line}</li>)}</ul>
    <h3>Who owns each part of the day</h3>
    <RhythmStrip slice={slice} order={order} />
    <ul className="profile-legend">{shown.slice(0, 12).map((item, index) => <li key={item.intent}><span style={{ background: `oklch(62% 0.13 ${RHYTHM_HUES[index % RHYTHM_HUES.length]})` }} />{item.intent.replaceAll("_", " ")}</li>)}</ul>
    <h3>Activities against the clock</h3>
    <HeatmapRows rows={shown.map((item) => ({ label: item.intent, shares: item.occupancyShare }))} slotCount={profile.slotLabels.length} />
    {slice.intents.length > shown.length && <p className="hint">{slice.intents.length - shown.length} rarer activity row(s) omitted here; the exported document and matrix carry them all.</p>}
    <h3>Where she is</h3>
    <HeatmapRows rows={slice.regions.slice(0, 12).map((item) => ({ label: item.regionId, shares: item.occupancyShare }))} slotCount={profile.slotLabels.length} />
    <div className="artifact-table profile-table">
      <div className="artifact-head"><span>Activity</span><span>Times</span><span>Days</span><span>Typical start</span><span>Spread</span><span>Mean length</span></div>
      {shown.map((item) => <div className="artifact-row" key={item.intent}><span>{item.intent.replaceAll("_", " ")}</span><span>{item.occurrences}</span><span>{item.daysObserved} / {slice.dayCount}</span><span>{item.typicalStart ?? "—"}</span><span>{item.startSpreadMinutes === null ? "—" : `±${Math.round(item.startSpreadMinutes)} min`}</span><span>{minutesLabel(item.meanDurationMinutes)}</span></div>)}
    </div>
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
  const home = models.data?.homeModel;
  // Replay follows the resident. While they are out, the errand is the thing being replayed, so
  // the places they travel to come into view for exactly as long as the trajectory needs them.
  const leavesHome = !!home && !!activeMovement?.waypoints?.some(
    (item) => !dwellingRegionIds(home).has(item.regionId),
  );
  return <div className="replay-plan">{home ? <PlanCanvas home={home} sensors={models.data?.sensorModel} activeMovement={activeMovement} showExternalPlaces={leavesHome} /> : models.error ? <ErrorPanel message={models.error.message} /> : <Skeleton lines={6} />}</div>;
}

function ExportsPage() {
  const jobs = useResource<JobRecord[]>("/jobs?limit=500");
  const completed = jobs.data?.filter((job) => job.status === "completed") ?? [];
  return <div className="page"><PageHeader eyebrow="Portable datasets" title="Exports" description="Streaming JSONL, CSV and XES projections with versions, seeds, digests and source relations." actions={<><Link className="button secondary" to="/maintenance"><Wrench size={16} /> Manage stored exports</Link><button className="button secondary" onClick={() => void download("/workspace/archive", "smart-home-workspace.shw")}><Download size={16} /> Archive workspace</button></>} />{jobs.loading ? <Skeleton lines={6} /> : jobs.error ? <ErrorPanel message={jobs.error.message} /> : completed.length ? <div className="export-run-list">{completed.map((job) => <Link key={job.jobId} to={`/simulations/${job.jobId}`} className="export-run"><span className="object-symbol"><Download size={18} /></span><span><strong>{job.jobId}</strong><small>Build or verify an export from the run detail.</small></span><StatusBadge status="completed" /><span>Open export builder</span></Link>)}</div> : <EmptyState title="No completed run to export" icon={<Download size={25} />}><p>Exports are always derived from persisted, digest-verified execution artifacts.</p></EmptyState>}<section className="format-notes"><div><p className="eyebrow">JSONL</p><h2>Streaming records</h2><p>One canonical record per line, suited to large datasets and incremental tools.</p></div><div><p className="eyebrow">CSV</p><h2>Stable columns</h2><p>Separate files per artifact family. Nested values remain canonical JSON cells.</p></div><div><p className="eyebrow">XES</p><h2>Process mining</h2><p>Explicit trace and event mappings preserve source identifiers and timestamps.</p></div></section></div>;
}

/**
 * Where a researcher sees what the folder and the catalogue disagree about, and reclaims space.
 *
 * The two are deliberately on one page: deleting exports is the ordinary way to get disk back, and
 * doing it in Explorer instead is what produced a divergence worth explaining in the first place.
 */
function MaintenancePage() {
  const integrity = useResource<WorkspaceIntegrity>("/workspace/integrity");
  const catalogue = useResource<ExportRecord[]>("/exports");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string }>();
  const reload = async () => { await Promise.all([integrity.reload(), catalogue.reload()]); };
  const describe = (summary: MaintenanceSummary) =>
    (summary.details.length ? summary.details.join("; ") : "Nothing needed changing")
    + (summary.bytesFreed > 0 ? `. ${formatBytes(summary.bytesFreed)} reclaimed` : "") + ".";
  const run = async (action: () => Promise<MaintenanceSummary>) => {
    setBusy(true); setNotice(undefined);
    try {
      setNotice({ kind: "success", text: describe(await action()) });
      await reload();
    } catch (reason) { setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }); }
    finally { setBusy(false); }
  };
  const repair = (removeOrphans: boolean) => run(async () =>
    (await api<{ summary: MaintenanceSummary }>(`/workspace/repair?remove_orphans=${removeOrphans}`, { method: "POST" })).summary);
  const removeExport = (exportId: string) => run(() => api<MaintenanceSummary>(`/exports/${exportId}`, { method: "DELETE" }));
  const report = integrity.data;
  const findings = report ? [...report.corrupt, ...report.missing, ...report.orphans] : [];
  return <div className="page">
    <PageHeader
      eyebrow="Workspace integrity"
      title="Maintenance"
      description="What the persistent catalogue and the workspace folder currently disagree about, and everything this workspace is holding on disk."
      actions={<button className="button secondary" disabled={busy || integrity.loading} onClick={() => void repair(false)}><Wrench size={16} /> Reconcile now</button>}
    />
    {notice && <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.kind === "success" ? <Check size={18} /> : <AlertCircle size={18} />}<span>{notice.text}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice(undefined)}><X size={16} /></button></div>}
    {integrity.loading && <Skeleton lines={5} />}
    {integrity.error && <ErrorPanel message={integrity.error.message} onRetry={() => void integrity.reload()} />}
    {report && <>
      <section className="metrics-strip" aria-label="Integrity summary">
        <Metric label="Content mismatches" value={report.corrupt.length} detail="Present, but not what the catalogue recorded" />
        <Metric label="Deleted files" value={report.missing.length} detail="Catalogued, no longer in the folder" />
        <Metric label="Uncatalogued files" value={report.orphans.length} detail={`${formatBytes(report.reclaimableBytes)} reclaimable`} />
      </section>
      {report.corrupt.length > 0 && <div className="diagnostic-banner" role="alert"><ShieldCheck size={20} /><div><strong>Publication is paused</strong><p>These files are still in the folder but their content no longer matches the digest recorded when they were published, so the workspace cannot say what they contain. Restore them from a workspace archive, or delete the runs and homes that depend on them.</p></div></div>}
      {findings.length ? <div className="artifact-table">
        <div className="artifact-head"><span>Finding</span><span>Path</span><span>Role</span><span>Size</span></div>
        {findings.slice(0, 200).map((finding) => <div className="artifact-row" key={`${finding.kind}-${finding.relativePath}`}>
          <StatusBadge status={finding.kind === "corrupt" ? "failed" : finding.kind === "missing" ? "interrupted" : "draft"} />
          <code title={finding.detail}>{finding.relativePath}</code>
          <span>{finding.role ?? "uncatalogued"}</span>
          <span>{formatBytes(finding.sizeBytes)}</span>
        </div>)}
      </div> : <EmptyState title="The folder and the catalogue agree" icon={<ShieldCheck size={25} />}><p>Every catalogued artifact is present with the content that was recorded when it was published.</p></EmptyState>}
      {report.orphans.length > 0 && <section className="surface"><div className="section-heading"><div><p className="eyebrow">Uncatalogued files</p><h2>{formatBytes(report.reclaimableBytes)} nothing refers to</h2></div><Trash2 size={20} /></div><p>Files inside the workspace folder that no catalogue entry describes. They are never read by the application; deleting them frees the space and changes no evidence.</p><ConfirmAction label={`Delete ${report.orphans.length} uncatalogued file(s)`} title="Delete every uncatalogued file?" consequence="Only files nothing in the catalogue refers to are removed. Runs, exports and stored inputs are untouched." busy={busy} onConfirm={() => void repair(true)} /></section>}
    </>}
    <section className="surface">
      <div className="section-heading"><div><p className="eyebrow">Stored datasets</p><h2>Exports on disk</h2></div><Download size={20} /></div>
      <p>Exports are reproducible: the same run and the same request rebuild them byte for byte, so deleting one costs only the time to export it again.</p>
      {catalogue.loading ? <Skeleton lines={4} /> : catalogue.error ? <ErrorPanel message={catalogue.error.message} /> : catalogue.data?.length ? <div className="artifact-table">
        <div className="artifact-head"><span>Export</span><span>Run</span><span>Files</span><span>Size</span><span /></div>
        {catalogue.data.map((item) => <div className="artifact-row" key={item.exportId}>
          <code>{item.exportId}</code>
          <RunLink id={item.runId}>{item.runId}</RunLink>
          <span>{item.available ? item.fileCount : "folder deleted"}</span>
          <span>{formatBytes(item.sizeBytes)}</span>
          <ConfirmAction compact label={`Delete export ${item.exportId}`} title="Delete this export?" consequence={`${item.fileCount} file(s), ${formatBytes(item.sizeBytes)}. The run keeps every artifact it was built from.`} busy={busy} onConfirm={() => void removeExport(item.exportId)} />
        </div>)}
      </div> : <EmptyState title="No export has been built" icon={<Download size={25} />}><p>Build one from any completed run to produce JSONL, CSV and XES projections.</p></EmptyState>}
    </section>
  </div>;
}

const sourceNote: Record<PathSource, string> = {
  "command-line": "chosen with the --workspace option when the application was started",
  environment: "chosen by an environment variable",
  configuration: "saved on this page",
  default: "the default location, inside your home folder",
};

function VolumeBar({ volume, occupied, label }: { volume: VolumeUsage; occupied?: number; label: string }) {
  const used = volume.totalBytes - volume.freeBytes;
  const mine = Math.min(occupied ?? 0, used);
  const percent = (value: number) => `${volume.totalBytes ? (value / volume.totalBytes) * 100 : 0}%`;
  const free = volume.freeBytes / volume.totalBytes;
  return (
    <div className="volume">
      <div className="volume-heading">
        <strong>{label}</strong>
        <span className={free < 0.1 ? "volume-critical" : free < 0.2 ? "volume-tight" : undefined}>
          {formatBytes(volume.freeBytes)} free of {formatBytes(volume.totalBytes)}
        </span>
      </div>
      <div
        className="volume-track"
        role="img"
        aria-label={`${label}: ${formatBytes(volume.freeBytes)} free of ${formatBytes(volume.totalBytes)}`}
      >
        <i className="volume-other" style={{ width: percent(used - mine) }} />
        <i className="volume-mine" style={{ width: percent(mine) }} />
      </div>
      {occupied !== undefined && <small>{formatBytes(mine)} of that is this workspace.</small>}
    </div>
  );
}

function StorageSection({ storage, onReveal }: { storage: ResourceState<StorageReport>; onReveal: () => void }) {
  if (storage.loading) return <section className="surface settings-section"><div className="settings-form"><Skeleton lines={5} /></div></section>;
  if (storage.error || !storage.data) {
    return <ErrorPanel message={storage.error?.message ?? "Unknown error"} onRetry={() => void storage.reload()} />;
  }
  const report = storage.data;
  const largest = Math.max(1, ...report.entries.map((entry) => entry.sizeBytes));
  const exports = report.entries.find((entry) => entry.relativePath === "exports");
  return (
    <section className="surface" aria-labelledby="storage-title">
      <div className="section-heading">
        <div><p className="eyebrow">Disk usage</p><h2 id="storage-title">This workspace holds {formatBytes(report.totalBytes)}</h2></div>
        <div className="button-row">
          <button className="button secondary" onClick={onReveal}><FolderOpen size={15} /> Open folder</button>
          <button className="button secondary" onClick={() => void storage.reload()}><RotateCw size={15} /> Measure again</button>
        </div>
      </div>
      {report.volume && (
        <div className="volume-panel">
          <VolumeBar volume={report.volume} occupied={report.totalBytes} label={`Drive ${report.volume.root}`} />
        </div>
      )}
      <div className="storage-table">
        {report.entries.map((entry) => (
          <div className="storage-row" key={entry.relativePath + entry.name}>
            <span><strong>{entry.name}</strong><code>{entry.relativePath}</code></span>
            <span className="storage-size"><b>{formatBytes(entry.sizeBytes)}</b><small>{entry.fileCount} file{entry.fileCount === 1 ? "" : "s"}</small></span>
            <span className="storage-share"><i style={{ width: `${(entry.sizeBytes / largest) * 100}%` }} /></span>
            <small>{entry.description}</small>
          </div>
        ))}
      </div>
      {exports && exports.sizeBytes > 0 && (
        <div className="import-guide-link">
          <Trash2 size={18} />
          <span>
            <strong>Exports are {formatBytes(exports.sizeBytes)} of that, and they can be rebuilt.</strong>
            <small>Deleting one costs only the time to export it again; the run keeps every artifact it was built from.</small>
          </span>
          <Link className="button secondary" to="/maintenance">Open maintenance</Link>
        </div>
      )}
    </section>
  );
}

function RelocationForm({ configuration, total, onDone }: { configuration: Configuration; total: number; onDone: () => Promise<void> }) {
  const [destination, setDestination] = useState("");
  const [check, setCheck] = useState<DestinationCheck>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const separator = configuration.workspace.path.includes("\\") ? "\\" : "/";
  useEffect(() => {
    if (!destination.trim()) { setCheck(undefined); return; }
    const timer = window.setTimeout(() => {
      void api<DestinationCheck>("/configuration/destination", { method: "POST", body: JSON.stringify({ path: destination }) })
        .then(setCheck)
        .catch(() => setCheck(undefined));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [destination]);
  const suggest = (root: string) =>
    setDestination(`${root.endsWith(separator) ? root : root + separator}smart-home-simulator${separator}workspace`);
  const submit = async (path: string, body: RequestInit) => {
    setBusy(true); setError(undefined);
    try {
      await api(path, body);
      setDestination("");
      await onDone();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };
  return (
    <div className="settings-form">
      <label>
        <span>New folder for the workspace</span>
        <input
          value={destination}
          onChange={(event) => setDestination(event.target.value)}
          placeholder={`${configuration.volumes[0]?.root ?? "D:\\"}smart-home-simulator${separator}workspace`}
          spellCheck={false}
        />
      </label>
      {configuration.volumes.length > 0 && (
        <div className="volume-picker">
          <span>Drives on this machine</span>
          <div>
            {configuration.volumes.map((volume) => (
              <button
                key={volume.root}
                type="button"
                className="tool-button"
                onClick={() => suggest(volume.root)}
                disabled={busy}
              >
                <HardDrive size={14} /> {volume.root}
                <small>{formatBytes(volume.freeBytes)} free</small>
              </button>
            ))}
          </div>
        </div>
      )}
      {check && (
        <p className={check.usable ? "settings-hint" : "field-error"} role="status">
          {check.usable ? <Check size={15} /> : <AlertCircle size={15} />} {check.message}
        </p>
      )}
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="button-row">
        <button
          className="button primary"
          disabled={busy || !check?.usable || check.holdsWorkspace}
          onClick={() => void submit("/configuration/relocation", { method: "POST", body: JSON.stringify({ destination }) })}
        >
          <FolderInput size={16} /> Move {formatBytes(total)} here
        </button>
        <button
          className="button secondary"
          disabled={busy || !check?.usable}
          onClick={() => void submit("/configuration", { method: "PUT", body: JSON.stringify({ workspace_directory: destination }) })}
        >
          <FolderOpen size={16} /> Just point here, leave the files
        </button>
      </div>
      <small>
        <strong>Move</strong> happens at the next start, when nothing has the database open: the files are copied
        to the new drive and only then removed from the old one, so an interrupted move leaves the workspace
        exactly where it is. <strong>Point here</strong> changes nothing on disk — use it for a folder that already
        holds a workspace, or to start an empty one somewhere else.
      </small>
    </div>
  );
}

function ApplicationForm({ configuration, onDone }: { configuration: Configuration; onDone: () => Promise<void> }) {
  const [port, setPort] = useState(String(configuration.port));
  const [openBrowser, setOpenBrowser] = useState(configuration.openBrowser);
  const [dataDirectory, setDataDirectory] = useState(configuration.dataDirectory.path);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const parsed = Number(port);
  const validPort = Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535;
  const dirty = String(configuration.port) !== port
    || configuration.openBrowser !== openBrowser
    || configuration.dataDirectory.path !== dataDirectory;
  const save = async () => {
    setBusy(true); setError(undefined);
    try {
      await api("/configuration", {
        method: "PUT",
        body: JSON.stringify({ port: parsed, open_browser: openBrowser, data_directory: dataDirectory }),
      });
      await onDone();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };
  return (
    <div className="settings-form">
      <div className="settings-field">
        <label><span>Local port</span><input value={port} onChange={(event) => setPort(event.target.value)} inputMode="numeric" /></label>
        <small>The application only ever listens on 127.0.0.1. Change this when another program already uses the port.</small>
      </div>
      <label className="settings-toggle">
        <input type="checkbox" checked={openBrowser} onChange={(event) => setOpenBrowser(event.target.checked)} />
        <span>Open the browser when the application starts</span>
      </label>
      <div className="settings-field">
        <label><span>Application folder</span><input value={dataDirectory} onChange={(event) => setDataDirectory(event.target.value)} spellCheck={false} /></label>
        <small>
          Holds the Python environment the application runs from — around 270 MB, and no research data.
          Moving it makes the next start reinstall that environment in the new folder.
        </small>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="button-row">
        <button className="button primary" disabled={busy || !dirty || !validPort} onClick={() => void save()}>
          <Save size={16} /> Save
        </button>
        {!validPort && <span className="field-error">A port is a number between 1 and 65535.</span>}
      </div>
    </div>
  );
}

function SettingsPage() {
  const configuration = useResource<Configuration>("/configuration");
  const storage = useResource<StorageReport>("/configuration/storage");
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string }>();
  const [restarting, setRestarting] = useState(false);
  const reload = async () => { await configuration.reload(); };
  const reveal = (kind: string) => {
    void api("/configuration/reveal", { method: "POST", body: JSON.stringify({ kind }) })
      .catch((reason: unknown) => setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) }));
  };
  const restart = async () => {
    setRestarting(true);
    setNotice(undefined);
    try {
      await api("/configuration/restart", { method: "POST" });
    } catch (reason) {
      setRestarting(false);
      setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) });
      return;
    }
    // The server is on its way down and its supervisor will start it again. Wait for it to answer
    // on the same address before reloading, or the tab lands on a connection error instead.
    clearSession();
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (attempt > 1 && (await health()) !== null) { window.location.reload(); return; }
    }
    setRestarting(false);
    setNotice({ kind: "error", text: "The application did not come back within two minutes. Start it again from its window." });
  };
  const cancelMove = async () => {
    try {
      await api("/configuration/relocation", { method: "DELETE" });
      await reload();
      setNotice({ kind: "success", text: "The move was cancelled. The workspace stays where it is." });
    } catch (reason) {
      setNotice({ kind: "error", text: reason instanceof Error ? reason.message : String(reason) });
    }
  };
  if (configuration.loading) return <div className="page"><Skeleton lines={7} /></div>;
  if (configuration.error || !configuration.data) {
    return <div className="page"><ErrorPanel message={configuration.error?.message ?? "Unknown error"} onRetry={() => void configuration.reload()} /></div>;
  }
  const settings = configuration.data;
  const pending = settings.pendingRelocation;
  const moved = settings.configuredWorkspace.path !== settings.workspace.path;
  const overridden = settings.workspace.source === "command-line" || settings.workspace.source === "environment";
  return (
    <div className="page settings-page">
      <PageHeader
        eyebrow="Installation"
        title="Settings"
        description="Where this application keeps its files, how much of the drive they take, and how to move them somewhere with room."
      />
      {notice && (
        <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.kind === "success" ? <Check size={18} /> : <AlertCircle size={18} />}
          <span>{notice.text}</span>
          <button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice(undefined)}><X size={16} /></button>
        </div>
      )}
      {(settings.restartRequired || restarting) && (
        <div className="diagnostic-banner" role="status">
          <RotateCw size={20} />
          <div>
            <strong>{restarting ? "Restarting…" : "These settings apply at the next start"}</strong>
            <p>
              {pending
                ? `The workspace will be moved to ${pending.destination} before the application opens it.`
                : moved
                  ? `The application will open ${settings.configuredWorkspace.path} instead of the folder currently in use.`
                  : "The saved settings differ from the ones this session is running with."}
            </p>
          </div>
          {settings.supervised
            ? <button className="button primary" disabled={restarting} onClick={() => void restart()}><RotateCw size={16} /> {restarting ? "Restarting" : "Restart now"}</button>
            : <span className="row-meta">Close the application window and start it again.</span>}
        </div>
      )}
      <section className="metrics-strip" aria-label="Storage summary">
        <Metric label="Workspace" value={storage.data ? formatBytes(storage.data.totalBytes) : "…"} detail="Runs, exports and inputs" />
        <Metric
          label="Free on this drive"
          value={settings.workspace.volume ? formatBytes(settings.workspace.volume.freeBytes) : "Unknown"}
          detail={settings.workspace.volume?.root ?? "Volume not readable"}
        />
        <Metric label="Port" value={settings.port} detail="Loopback only" />
        <Metric label="Drives" value={settings.volumes.length} detail="Available for the workspace" />
      </section>

      <StorageSection storage={storage} onReveal={() => reveal("workspace")} />

      <section className="surface settings-section" aria-labelledby="location-title">
        <div className="section-heading">
          <div><p className="eyebrow">Workspace folder</p><h2 id="location-title">Where the research data lives</h2></div>
          <HardDrive size={20} />
        </div>
        <dl className="definition-list">
          <div><dt>In use now</dt><dd><code title={settings.workspace.path}>{settings.workspace.path}</code><small>({sourceNote[settings.workspace.source]})</small></dd></div>
          {moved && <div><dt>From the next start</dt><dd><code title={settings.configuredWorkspace.path}>{settings.configuredWorkspace.path}</code></dd></div>}
          <div><dt>Settings file</dt><dd><code title={settings.configurationPath}>{settings.configurationPath}</code><button className="icon-button" aria-label="Open the settings folder" onClick={() => reveal("configuration")}><FolderOpen size={15} /></button></dd></div>
        </dl>
        {overridden && (
          <div className="notice" role="status" style={{ margin: "0 1.15rem 1rem" }}>
            <AlertCircle size={18} />
            <span>This session was started with an explicit workspace, so it wins over anything saved here. Start the application without that option for these settings to take effect.</span>
          </div>
        )}
        {pending ? (
          <div className="settings-form">
            <div className="confirm-action">
              <div>
                <strong>A move is waiting for the next start</strong>
                <small>{pending.source} → {pending.destination}. Nothing has been copied yet.</small>
              </div>
              <div className="button-row">
                <button className="button secondary" onClick={() => void cancelMove()}>Cancel the move</button>
              </div>
            </div>
          </div>
        ) : (
          <RelocationForm configuration={settings} total={storage.data?.totalBytes ?? 0} onDone={reload} />
        )}
      </section>

      <section className="surface settings-section" aria-labelledby="application-title">
        <div className="section-heading">
          <div><p className="eyebrow">Application</p><h2 id="application-title">How it starts</h2></div>
          <SlidersHorizontal size={20} />
        </div>
        <ApplicationForm configuration={settings} onDone={reload} />
      </section>
    </div>
  );
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
  return <div className="page guide-page"><PageHeader eyebrow="Integrated guide" title="From a case description to inspectable evidence" description="Everything required to generate, import, run and verify a simulation—offline and without manual JSON authoring." /><div className="guide-layout"><nav aria-label="Guide contents"><a href="#authoring">Generate the bundle</a><a href="#first-run">Import and run</a><a href="#artifacts">Which file to use</a><a href="#truth">Truth and observation</a><a href="#recovery">Recovery and disk space</a><a href="#keyboard">Keyboard</a></nav><article><section id="authoring"><span>01</span><div><h2>Generate one authoring bundle</h2><p>Describe the person or people in ordinary language. Include dates, habits, constraints, health information and the research objective only when relevant. The prompt asks the external LLM for the <em>structure</em> of the period—recurring activities, the habit bands of the day, phases and events—and a deterministic expander produces every concrete day from it, computing sleep debt, hunger and fatigue as it goes.</p><p>It does not ask for the days themselves, because that degrades as the horizon grows: measured on this project's own cases, the share of distinct days falls from 1.00 over a week to 0.74 over a month to 0.03 over eight months, where 244 days collapsed into seven templates. An outline costs the same whether it covers a week or a year.</p><label className="case-description"><span>Person and case description</span><textarea aria-label="Person and case description" value={caseDescription} onChange={(event) => setCaseDescription(event.target.value)} placeholder="Example: Lucia Rossi, 68, lives alone in Rome. Simulate August 2026…" /><small>This text is inserted locally into the prompt. Nothing is sent by this application.</small></label><div className="prompt-grid"><PromptCard title="Horizon outline prompt" label="Recommended · outline 1.1.0" description="Returns a horizon outline plus its process package, not days. The expander also publishes the habit ground truth a segmentation algorithm is scored against, and 1.1.0 requires every declared band to be inhabited: an anchor activity, something that occupies a wide band in blocks, and content that differs between two bands sharing a window." template={authoringPrompts.outline.text} caseDescription={caseDescription} /></div><div className="guide-callout"><ShieldCheck size={19} /><p><strong>Save only the model response as JSON.</strong> It must start with <code>{"{"}</code>, end with <code>{"}"}</code>, and contain no Markdown fence or explanation.</p></div><div className="guide-callout"><ShieldCheck size={19} /><p><strong>Its response is expanded, not imported as it stands.</strong> Save it as JSON and choose it under <em>Horizon outline</em> in Resident context: the application computes the days and imports the result in one step. From a terminal the same thing is <code>smart-home-sim expand-outline outline.json --output bundle.json --ground-truth-output truth.json --seed 1</code>, which also writes the habit ground truth beside the bundle.</p></div></div></section><section id="first-run"><span>02</span><div><h2>Import and run</h2><ol><li>Create a home from the Homes page.</li><li>Select the complete <code>authoring-bundle.json</code> in Resident context.</li><li>Resolve every reported validation issue; rejected bundles publish no authoring revision.</li><li>Choose <em>Generate home and sensors</em> to build the environment alone. The worker compiles, builds the home, binds behavior and deploys sensors, and executes nothing — so you can review the plan, move a wall or a PIR and confirm it before a single day is simulated.</li><li>Start the run. It executes the plan and the sensor field you approved, then projects the observations. <em>Generate and run in one step</em> does both at once when the recommended plan needs no review.</li><li>Open the completed run and verify its replay digest.</li></ol></div></section><section id="artifacts"><span>03</span><div><h2>Source, canonical and runtime files</h2><p><strong>Import the source bundle in the ordinary workflow.</strong> It has <code>documentType: simulation_authoring_bundle</code> and contains <code>scenario</code> plus <code>personalProcessPackage</code>. Canonical split files are internal validated projections. Runtime inputs may reference upgraded execution catalogs and are not a substitute for the researcher-authored source.</p><p>The collapsed Advanced importer accepts the two canonical documents separately for debugging or controlled migration. It does not silently repair or upgrade them.</p></div></section><section id="truth"><span>04</span><div><h2>Ground truth is not a sensor field</h2><p>The diary is derived from the authoritative execution trace. The Observable view contains only device fields. Oracle mode opens a separate mapping from a sensor record to its simulated cause, resident and activity.</p><div className="concept-pair"><div><Radar size={20} /><strong>Observable</strong><p>Sensor, timestamp, measurement, value and quality.</p></div><div><ShieldCheck size={20} /><strong>Oracle</strong><p>Movement, action or transition that produced the observation.</p></div></div></div></section><section id="recovery"><span>05</span><div><h2>Safe interruption, recovery and disk space</h2><p>Closing the browser leaves the backend and worker active. Cancelling a run discards staging. If the backend stops unexpectedly, active work becomes interrupted and the next start verifies every registered artifact before enabling publication.</p><p>You can delete files from the workspace folder: the next start forgets the catalogue entries that described them, says what it changed, and keeps working. Publication is only paused when a file is still there holding content that contradicts the digest recorded when it was published, because then what a run executed can no longer be established. <Link to="/maintenance">Maintenance</Link> shows exactly what the folder and the catalogue disagree about, and lets you delete exports, runs and homes from inside the application instead.</p><p>A workspace grows with every run and every export, and the folder it starts in is on the system drive. <Link to="/settings">Settings</Link> weighs each part of it against the space left on that drive, and moves the whole workspace to another one. The move is agreed there and performed by the next start, when nothing has the database open: across drives the files are copied before anything is removed, so an interrupted move leaves the workspace where it was.</p></div></section><section id="keyboard"><span>06</span><div><h2>Keyboard and structured alternatives</h2><p>Use Tab to reach plan objects, Enter or Space to select, and the inspector controls for precise movement. Every spatial object also appears in a structured list. Motion respects your reduced-motion preference.</p></div></section></article></div></div>;
}

function NotFound() {
  return <div className="page"><EmptyState title="This workspace view does not exist" icon={<FolderOpen size={25} />} action={<Link className="button primary" to="/"><ArrowLeft size={16} /> Back to dashboard</Link>}><p>The URL may refer to a home or run that has been removed from navigation.</p></EmptyState></div>;
}
