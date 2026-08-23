export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface WorkspaceSummary {
  workspaceId: string;
  name: string;
  formatVersion: string;
  createdAt: string;
  updatedAt: string;
  diagnosticMode: boolean;
  homeCount: number;
  residentCount: number;
  runCount: number;
  activeJobCount: number;
  artifactCount: number;
}

export interface HomeSummary {
  homeId: string;
  name: string;
  description: string;
  residentCount: number;
  runCount: number;
  issueCount: number;
  currentHomeArtifactId?: string;
  currentSensorArtifactId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ResidentSummary {
  residentId: string;
  homeId: string;
  sourceResidentId: string;
  displayName: string;
  scenarioArtifactId?: string;
  behaviorArtifactId?: string;
  createdAt: string;
}

export interface JobProgress {
  phase: string;
  percent: number;
  completedUnits: number;
  totalUnits?: number;
  message: string;
}

export interface JobRecord {
  jobId: string;
  homeId?: string;
  kind: "materialization" | "simulation" | "export" | "integrity" | "generation" | "environment";
  status: JobStatus;
  progress: JobProgress;
  requestedAt: string;
  startedAt?: string;
  finishedAt?: string;
  processId?: number;
  resultReference?: string;
  errorCode?: string;
  errorMessage?: string;
  seed?: number;
}

export interface JobEvent {
  jobId: string;
  sequence: number;
  occurredAt: string;
  eventType: "status" | "progress" | "log" | "artifact" | "issue";
  level: "debug" | "info" | "warning" | "error";
  message: string;
  payload: Record<string, unknown>;
}

export interface IntegrityFinding {
  kind: "missing" | "corrupt" | "orphan";
  relativePath: string;
  artifactId?: string;
  role?: string;
  sizeBytes: number;
  detail: string;
}

export interface WorkspaceIntegrity {
  checkedAt: string;
  diagnosticMode: boolean;
  missing: IntegrityFinding[];
  corrupt: IntegrityFinding[];
  orphans: IntegrityFinding[];
  reclaimableBytes: number;
}

export interface MaintenanceSummary {
  performedAt: string;
  homesRemoved: number;
  runsRemoved: number;
  exportsRemoved: number;
  artifactsPruned: number;
  artifactsAdopted: number;
  filesRemoved: number;
  bytesFreed: number;
  corruptRemaining: number;
  details: string[];
}

export interface ExportRecord {
  exportId: string;
  runId: string;
  createdAt: string;
  available: boolean;
  archived: boolean;
  fileCount: number;
  sizeBytes: number;
}

export interface Overview {
  workspace: WorkspaceSummary;
  lastRepair?: MaintenanceSummary | null;
  homes: HomeSummary[];
  residents: ResidentSummary[];
  jobs: JobRecord[];
}

export interface Point {
  x: number;
  y: number;
}

export interface Polygon {
  vertices: Point[];
}

export interface HomeRegion {
  regionId: string;
  kind: "room" | "outdoor" | "external" | "transit";
  boundary: Polygon;
  traversable: boolean;
}

export interface HomeConnection {
  connectionId: string;
  regionAId: string;
  regionBId: string;
  kind: "doorway" | "passage" | "transit";
  bidirectional: boolean;
  widthMeters: number;
  portalA?: Point;
  portalB?: Point;
}

export interface HomeObstacle {
  obstacleId: string;
  regionId: string;
  boundary: Polygon;
}

export interface InteractionPoint {
  interactionPointId: string;
  regionId: string;
  position: Point;
  approachRadiusMeters: number;
}

export interface HomeEntity {
  entityId: string;
  entityType: string;
  regionId: string;
  interactionPointId: string;
  capabilities: Array<{
    capability: string;
    roles: string[];
    supportedOperations: string[];
  }>;
  initialState: Record<string, unknown>;
}

export interface HomeModel {
  schemaVersion: "1.0.0";
  documentType: "home_model";
  homeId: string;
  homeVersion: string;
  coordinateSystem: Record<string, unknown>;
  regions: HomeRegion[];
  connections: HomeConnection[];
  obstacles: HomeObstacle[];
  interactionPoints: InteractionPoint[];
  entities: HomeEntity[];
  locationBindings: Array<Record<string, unknown>>;
  resourceBindings: Array<Record<string, unknown>>;
  kinematicDefaults: Record<string, unknown>;
}

export interface SensorBase {
  sensorId: string;
  sensorType: "pir" | "contact" | "temperature";
  position: Point;
  timing: {
    latencyMilliseconds: number;
    clockJitterMilliseconds: number;
    cooldownMilliseconds: number;
  };
  errorModel: {
    dropoutProbability: number;
    falseNegativeProbability: number;
    falsePositiveProbabilityPerDay: number;
    measurementNoiseStandardDeviation: number;
  };
  failureWindows: Array<{ startsAt: string; endsAt: string }>;
  [key: string]: unknown;
}

export interface SensorModel {
  schemaVersion: "1.0.0";
  documentType: "sensor_model";
  sensorModelId: string;
  sensorModelVersion: string;
  sourceBundleId: string;
  sourceBundleSha256: string;
  seed: number;
  regionIds: string[];
  entityIds: string[];
  sensors: SensorBase[];
}

export interface GenerationProvenance {
  generationJobId: string;
  dayCount: number;
  experimentId?: string;
  gate?: string;
}

/**
 * Whether the plan on screen is still only what the policies recommended.
 *
 * `approved` is the one the interface acts on: until the researcher confirms the planimetry or
 * edits it, what they are looking at is a proposal, and the runs regenerate it from the policy.
 */
export interface PlanApproval {
  home: "recommended" | "researcher";
  sensor: "recommended" | "researcher";
  approved: boolean;
}

export interface HomeDetail {
  home: HomeSummary;
  residents: ResidentSummary[];
  models: { homeModel?: HomeModel; sensorModel?: SensorModel };
  jobs: JobRecord[];
  issues?: ApplicationIssue[];
  generation?: GenerationProvenance | null;
  planApproval?: PlanApproval;
}

export interface ApplicationIssue {
  code: string;
  severity: "error" | "warning" | "info";
  stage: string;
  path: string;
  message: string;
  details: Record<string, unknown>;
  graphicalReference?: { surface: string; elementId: string; propertyName?: string };
}

export interface DiaryAction {
  actionExecutionId: string;
  nodeId: string;
  actionType: string;
  startedAt: string;
  endedAt: string;
  status: string;
  providerIds: string[];
}

export interface DiaryEntry {
  activityExecutionId: string;
  sourceActivityId: string;
  actorId: string;
  intent: string;
  processModelId: string;
  plannedStart: string;
  plannedEnd: string;
  actualStart: string;
  actualEnd: string;
  status: string;
  actions: DiaryAction[];
  movementIds: string[];
  deviationIds: string[];
  traceId: string;
  traceSemanticDigest: string;
}

export interface ObservationCause {
  origin: string;
  causeType: string;
  causeIds: string[];
  residentIds: string[];
  activityExecutionIds: string[];
  actionExecutionIds: string[];
}

export interface Observation {
  observationId: string;
  sensorId: string;
  sensorType: string;
  observedAt: string;
  measurement: string;
  value: unknown;
  unit?: string;
  quality: string;
  oracleCause?: ObservationCause;
}

export interface TimelineEvent {
  at: string;
  end: string;
  kind: "activity" | "action" | "movement";
  id?: string;
  actorId?: string;
  label: string;
  status: string;
  waypoints?: Array<{ at: string; regionId: string; position: Point }>;
}

export interface ExportManifestFile {
  role: string;
  // json and html are never requested: they are the two shapes the resident profile takes.
  format: "jsonl" | "csv" | "xes" | "json" | "html";
  relativePath: string;
  mediaType: string;
  recordCount: number;
  sizeBytes: number;
  sha256: string;
}

export interface ExportManifest {
  exportId: string;
  runId: string;
  sourceBundleSha256: string;
  sourceTraceSemanticDigest: string;
  seed: number;
  createdAt: string;
  observableOracleSeparated: true;
  files: ExportManifestFile[];
}

export interface IntentRhythm {
  intent: string;
  occurrences: number;
  daysObserved: number;
  totalMinutes: number;
  meanDurationMinutes: number;
  medianDurationMinutes: number;
  typicalStart: string | null;
  startSpreadMinutes: number | null;
  occupancyMinutes: number[];
  occupancyShare: number[];
  starts: number[];
}

export interface RegionRhythm {
  regionId: string;
  totalMinutes: number;
  occupancyShare: number[];
}

export interface SlotSummary {
  slot: number;
  start: string;
  observedMinutes: number;
  labelledShare: number;
  dominantIntent: string | null;
  dominantShare: number;
  entropyBits: number;
}

export interface BehaviourSlice {
  dayType: "all" | "weekday" | "weekend";
  dayCount: number;
  observedMinutes: number;
  activityCount: number;
  intents: IntentRhythm[];
  regions: RegionRhythm[];
  slots: SlotSummary[];
}

export interface ResidentBehaviour {
  residentId: string;
  activityCount: number;
  droppedActivityCount: number;
  narrative: string[];
  slices: BehaviourSlice[];
}

export interface ResidentProfile {
  profileId: string;
  runId: string | null;
  traceId: string;
  sourceTraceSemanticDigest: string;
  seed: number;
  startDate: string;
  endDate: string;
  dayCount: number;
  slotMinutes: number;
  slotLabels: string[];
  residents: ResidentBehaviour[];
}

export type PathSource = "command-line" | "environment" | "configuration" | "default";

export interface VolumeUsage {
  root: string;
  totalBytes: number;
  freeBytes: number;
}

export interface DirectoryLocation {
  path: string;
  source: PathSource;
  exists: boolean;
  volume: VolumeUsage | null;
}

export interface StorageEntry {
  name: string;
  relativePath: string;
  sizeBytes: number;
  fileCount: number;
  description: string;
}

export interface StorageReport {
  path: string;
  exists: boolean;
  totalBytes: number;
  entries: StorageEntry[];
  volume: VolumeUsage | null;
}

export interface DestinationCheck {
  path: string;
  usable: boolean;
  message: string;
  empty: boolean;
  holdsWorkspace: boolean;
  sameVolume: boolean;
  volume: VolumeUsage | null;
}

export interface PendingRelocation {
  source: string;
  destination: string;
}

export interface Configuration {
  configurationPath: string;
  workspace: DirectoryLocation;
  configuredWorkspace: DirectoryLocation;
  dataDirectory: DirectoryLocation;
  port: number;
  openBrowser: boolean;
  pendingRelocation: PendingRelocation | null;
  restartRequired: boolean;
  supervised: boolean;
  volumes: VolumeUsage[];
}

export type ReplayStatus = "verifying" | "ready" | "blocked";
export type ReplayDetailMode = "presentation" | "analysis";
export type ReplayVisibilityMode = "observable" | "oracle";
export type ReplayEventKind =
  | "activity"
  | "action"
  | "movement"
  | "observation"
  | "state_transition"
  | "resource"
  | "runtime_event"
  | "plan_deviation"
  | "daily_summary";

export interface ReplayWaypoint {
  at: string;
  regionId: string;
  traversalMode: string;
  position: Point;
}

export interface ReplayEvent {
  at: string;
  end?: string | null;
  kind: ReplayEventKind;
  eventId: string;
  label: string;
  status?: string | null;
  actorId?: string | null;
  sensorId?: string | null;
  waypoints: ReplayWaypoint[];
  details: Record<string, unknown>;
}

export interface ReplayEventWindow {
  items: ReplayEvent[];
  total: number;
  traceStart: string;
  traceEnd: string;
  windowStart: string;
  windowEnd: string;
}

export interface ReplayResidentFrame {
  residentId?: string;
  regionId?: string | null;
  position?: Point | null;
  posture?: string | null;
  executionState: string;
  activityActive?: boolean;
  activityLabel?: string | null;
  activityExecutionId?: string | null;
  actionExecutionId?: string | null;
  heldResourceIds: string[];
  facts: Record<string, unknown>;
}

export interface ReplaySensorFrame {
  observationId: string;
  sensorId: string;
  sensorType: string;
  observedAt: string;
  measurement: string;
  value: unknown;
  unit?: string | null;
  quality: string;
  changed: boolean;
  oracleCause?: ObservationCause | null;
}

export interface ReplayFrame {
  runId: string;
  at: string;
  traceStart: string;
  traceEnd: string;
  residents: ReplayResidentFrame[];
  sensorStates: ReplaySensorFrame[];
  entityStates: Record<string, Record<string, unknown>>;
  environmentFacts: Record<string, unknown>;
  resourceAvailableUnits: Record<string, number>;
  activeEventIds?: string[];
}

/** Evidence-derived state for the spatial replay layer; it never supplies a guessed position. */
export interface ReplayOverlay {
  residents: Array<{
    residentId: string;
    label: string;
    marker: string;
    regionId?: string;
    position?: Point;
    executionState: string;
    motion?: "step" | "interpolate" | "none";
  }>;
  activeRegionIds: string[];
  activeSensorIds: string[];
  trajectory: Point[];
  selectedResidentId?: string;
  reducedMotion?: boolean;
}

export interface ReplayFilters {
  eventKinds: ReplayEventKind[];
  actorIds: string[];
  sensorIds: string[];
  statuses: string[];
  detailMode: ReplayDetailMode;
  visibilityMode: ReplayVisibilityMode;
  speed: number;
  selectedResidentId?: string | null;
}

export interface ReplaySessionState {
  replayId?: string | null;
  runId: string;
  verifiedDigest?: string | null;
  playable: boolean;
  positionAt?: string | null;
  filters: ReplayFilters;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface ReplayVerification {
  runId: string;
  verifiedAt: string;
  matches: boolean;
  expectedSemanticDigest: string;
  actualSemanticDigest?: string | null;
}
