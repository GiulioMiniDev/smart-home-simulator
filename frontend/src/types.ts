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
  kind: "materialization" | "simulation" | "export" | "integrity" | "generation";
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

export interface Overview {
  workspace: WorkspaceSummary;
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

export interface HomeDetail {
  home: HomeSummary;
  residents: ResidentSummary[];
  models: { homeModel?: HomeModel; sensorModel?: SensorModel };
  jobs: JobRecord[];
  issues?: ApplicationIssue[];
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
  id: string;
  actorId: string;
  label: string;
  status: string;
  waypoints?: Array<{ at: string; regionId: string; position: Point }>;
}

export interface ExportManifestFile {
  role: string;
  format: "jsonl" | "csv" | "xes";
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
