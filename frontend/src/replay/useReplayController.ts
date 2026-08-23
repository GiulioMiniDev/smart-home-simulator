import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { ReplayEvent, ReplayEventWindow, ReplayFilters, ReplayFrame, ReplaySessionState, ReplayStatus, ReplayVerification } from "../types";
import { advanceTime } from "./replay-clock";

const DEFAULT_WINDOW_SPAN_MS = 15 * 60 * 1000;
const MIN_WINDOW_SPAN_MS = 60 * 1000;
const WINDOW_REFRESH_MARGIN_MS = 5 * 60 * 1000;
const WINDOW_LIMIT = 5_000;
// Seven days needs fourteen halvings to reach the one-minute safe lower bound.
const MAX_DENSITY_REQUERIES = 16;
const SESSION_DEBOUNCE_MS = 400;
const FRAME_CADENCE_MS = 100;

const defaultFilters = (): ReplayFilters => ({
  eventKinds: [], actorIds: [], sensorIds: [], statuses: [], detailMode: "presentation",
  visibilityMode: "observable", speed: 1, selectedResidentId: undefined,
});

const timestamp = (value: string | null | undefined): number | undefined => {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const apiError = (reason: unknown): ApiError => reason instanceof ApiError
  ? reason
  : new ApiError(reason instanceof Error ? reason.message : String(reason), 0);

const isAbort = (reason: unknown): boolean => reason instanceof DOMException && reason.name === "AbortError";

/** Normalize the deliberately smaller Observable session shape into the controller's full shape. */
function normalizeFilters(filters: Partial<ReplayFilters> | undefined): ReplayFilters {
  const visibilityMode = filters?.visibilityMode === "oracle" ? "oracle" : "observable";
  const normalized: ReplayFilters = {
    ...defaultFilters(), ...filters,
    eventKinds: filters?.eventKinds ?? [], actorIds: filters?.actorIds ?? [],
    sensorIds: filters?.sensorIds ?? [], statuses: filters?.statuses ?? [], visibilityMode,
  };
  return visibilityMode === "observable"
    ? { ...normalized, actorIds: [], selectedResidentId: undefined }
    : normalized;
}

function normalizeSession(session: ReplaySessionState): ReplaySessionState {
  return { ...session, filters: normalizeFilters(session.filters) };
}

type SelectionAnchor = Pick<ReplayEvent, "kind" | "at" | "end" | "sensorId" | "status"> & { occurrence: number };

function anchorFor(event: ReplayEvent, items: ReplayEvent[]): SelectionAnchor {
  const alike = items.filter((candidate) => candidate.kind === event.kind && candidate.at === event.at && candidate.end === event.end && candidate.sensorId === event.sensorId && candidate.status === event.status);
  return {
    kind: event.kind, at: event.at, end: event.end, sensorId: event.sensorId,
    status: event.status,
    occurrence: Math.max(0, alike.findIndex((candidate) => candidate.eventId === event.eventId)),
  };
}

function remapAnchor(anchor: SelectionAnchor, items: ReplayEvent[]): ReplayEvent | undefined {
  const candidates = items.filter((candidate) => candidate.kind === anchor.kind
    && candidate.at === anchor.at && candidate.end === anchor.end && candidate.sensorId === anchor.sensorId
    && candidate.status === anchor.status);
  return candidates[anchor.occurrence] ?? candidates[0];
}

function matchesFilters(event: ReplayEvent, filters: ReplayFilters): boolean {
  return (!filters.eventKinds.length || filters.eventKinds.includes(event.kind))
    && (!filters.sensorIds.length || Boolean(event.sensorId && filters.sensorIds.includes(event.sensorId)))
    && (!filters.actorIds.length || Boolean(event.actorId && filters.actorIds.includes(event.actorId)))
    && (!filters.statuses.length || Boolean(event.status && filters.statuses.includes(event.status)));
}

function sameFilters(left: ReplayFilters, right: ReplayFilters): boolean {
  const same = (first: string[], second: string[]) => first.length === second.length && first.every((value, index) => value === second[index]);
  return left.detailMode === right.detailMode
    && left.visibilityMode === right.visibilityMode
    && left.speed === right.speed
    && left.selectedResidentId === right.selectedResidentId
    && same(left.eventKinds, right.eventKinds)
    && same(left.actorIds, right.actorIds)
    && same(left.sensorIds, right.sensorIds)
    && same(left.statuses, right.statuses);
}

export interface ReplayController {
  status: ReplayStatus;
  verification?: ReplayVerification;
  session?: ReplaySessionState;
  positionMs: number;
  traceStartMs?: number;
  traceEndMs?: number;
  playing: boolean;
  filters: ReplayFilters;
  selectedEventId?: string;
  events?: ReplayEventWindow;
  frame?: ReplayFrame;
  error?: ApiError;
  windowSpanMs: number;
  evidenceIncomplete: boolean;
  evidenceLoading: boolean;
  windowNotice?: string;
  filterOptions: { sensorIds: string[]; actorIds: string[]; statuses: string[] };
  play(): void;
  pause(): void;
  seek(positionMs: number): void;
  step(direction: -1 | 1): void;
  selectEvent(eventId?: string): void;
  updateFilters(patch: Partial<ReplayFilters>): void;
  setWindowSpan(windowSpanMs: number): void;
}

export function useReplayController(runId: string, { oracleAvailable = false }: { oracleAvailable?: boolean } = {}): ReplayController {
  const [status, setStatus] = useState<ReplayStatus>("verifying");
  const [verification, setVerification] = useState<ReplayVerification>();
  const [session, setSession] = useState<ReplaySessionState>();
  const [positionMs, setPositionMs] = useState<number>();
  const [positionInitialized, setPositionInitialized] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [filters, setFilters] = useState<ReplayFilters>(defaultFilters);
  const [selectedEventId, setSelectedEventId] = useState<string>();
  const [events, setEvents] = useState<ReplayEventWindow>();
  const [frame, setFrame] = useState<ReplayFrame>();
  const [error, setError] = useState<ApiError>();
  const [windowRequest, setWindowRequest] = useState(0);
  const [frameRequest, setFrameRequest] = useState<{ at: number; version: number }>();
  const [windowSpanMs, setWindowSpanMs] = useState(DEFAULT_WINDOW_SPAN_MS);
  const [narrowedSpanMs, setNarrowedSpanMs] = useState<number>();
  const [evidenceIncomplete, setEvidenceIncomplete] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [windowNotice, setWindowNotice] = useState<string>();
  const [filterOptions, setFilterOptions] = useState<{ sensorIds: string[]; actorIds: string[]; statuses: string[] }>({ sensorIds: [], actorIds: [], statuses: [] });
  const positionRef = useRef<number | undefined>(undefined);
  const restoredPositionRef = useRef<number | undefined>(undefined);
  const rangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowRangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowLoadingRef = useRef(false);
  const refreshedWindowRef = useRef<string | undefined>(undefined);
  const windowVersion = useRef(0);
  const frameVersion = useRef(0);
  const verificationAbort = useRef<AbortController | undefined>(undefined);
  const oracleSessionAbort = useRef<AbortController | undefined>(undefined);
  const windowAbort = useRef<AbortController | undefined>(undefined);
  const catalogAbort = useRef<AbortController | undefined>(undefined);
  const frameAbort = useRef<AbortController | undefined>(undefined);
  const lastFrameSchedule = useRef<{ at: number; scheduledAt: number } | undefined>(undefined);
  const saveTimer = useRef<number | undefined>(undefined);
  const saveRequest = useRef<AbortController | undefined>(undefined);
  const saveVersion = useRef(0);
  const persistenceEnabledRef = useRef(false);
  const oracleSessionAttemptedRef = useRef(false);
  const oracleSessionPendingRef = useRef(false);
  const verifiedDigestRef = useRef<string | undefined>(undefined);
  const statusRef = useRef<ReplayStatus>(status);
  const activeRunId = useRef(runId);
  const runGeneration = useRef(0);
  const verifiedRun = useRef<{ runId: string; generation: number } | undefined>(undefined);
  const checkedRun = useRef<{ runId: string; generation: number } | undefined>(undefined);
  const errorGeneration = useRef<number | undefined>(undefined);
  const selectedEventIdRef = useRef<string | undefined>(undefined);
  const selectionAnchorRef = useRef<SelectionAnchor | undefined>(undefined);
  const oracleAvailableRef = useRef(oracleAvailable);
  const densityAttemptsRef = useRef(0);
  const filtersRef = useRef(filters);
  oracleAvailableRef.current = oracleAvailable;
  filtersRef.current = filters;
  statusRef.current = status;

  // This render-time ref reset makes a prop switch safe before effects get a chance to run.
  if (activeRunId.current !== runId) {
    activeRunId.current = runId;
    runGeneration.current += 1;
    verifiedRun.current = undefined;
    checkedRun.current = undefined;
  }
  const isVerifiedRun = useCallback(() => {
    const verified = verifiedRun.current;
    return verified?.runId === runId && verified.generation === runGeneration.current;
  }, [runId]);
  const setReplayStatus = useCallback((next: ReplayStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);
  const isReplayReady = useCallback(() => statusRef.current === "ready" && isVerifiedRun(), [isVerifiedRun]);
  const verifiedForCurrentRun = isVerifiedRun();
  const setRunError = useCallback((next: ApiError | undefined) => {
    errorGeneration.current = next ? runGeneration.current : undefined;
    setError(next);
  }, []);
  const setSelection = useCallback((eventId?: string) => {
    selectedEventIdRef.current = eventId;
    setSelectedEventId(eventId);
  }, []);
  const invalidateEvidence = useCallback(() => {
    windowVersion.current += 1; frameVersion.current += 1;
    windowAbort.current?.abort(); catalogAbort.current?.abort(); frameAbort.current?.abort();
    lastFrameSchedule.current = undefined;
  }, []);
  const cancelPendingSave = useCallback(() => {
    saveVersion.current += 1;
    if (saveTimer.current !== undefined) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = undefined;
    }
    saveRequest.current?.abort();
    saveRequest.current = undefined;
  }, []);
  const blockReplay = useCallback((reason: unknown) => {
    invalidateEvidence();
    cancelPendingSave();
    windowLoadingRef.current = false;
    setPlaying(false);
    setEvidenceLoading(false);
    setEvents(undefined);
    setFrame(undefined);
    setSelection(undefined);
    setRunError(apiError(reason));
    setReplayStatus("blocked");
  }, [cancelPendingSave, invalidateEvidence, setReplayStatus, setRunError, setSelection]);

  const setClockPosition = useCallback((next: number | undefined) => {
    positionRef.current = next;
    setPositionMs(next);
  }, []);
  const requestFrame = useCallback((at = positionRef.current, immediate = false) => {
    if (!isReplayReady() || at === undefined) return;
    const now = performance.now();
    const previous = lastFrameSchedule.current;
    if (!immediate && previous && now - previous.scheduledAt < FRAME_CADENCE_MS) return;
    if (immediate && previous?.at === at && now - previous.scheduledAt < FRAME_CADENCE_MS) return;
    lastFrameSchedule.current = { at, scheduledAt: now };
    setFrameRequest({ at, version: ++frameVersion.current });
  }, [isReplayReady]);
  const requestWindow = useCallback((force = false) => {
    if (!isReplayReady()) return;
    if (force || !windowLoadingRef.current) {
      windowLoadingRef.current = true;
      setWindowRequest((current) => current + 1);
    }
  }, [isReplayReady]);

  useEffect(() => {
    const controller = new AbortController();
    verificationAbort.current?.abort(); verificationAbort.current = controller;
    oracleSessionAbort.current?.abort(); oracleSessionAbort.current = undefined;
    oracleSessionAttemptedRef.current = false; oracleSessionPendingRef.current = false;
    persistenceEnabledRef.current = false; verifiedDigestRef.current = undefined;
    const generation = runGeneration.current;
    let current = true;
    cancelPendingSave();
    setReplayStatus("verifying"); setVerification(undefined); setSession(undefined); setEvents(undefined); setFrame(undefined);
    const resetFilters = defaultFilters();
    filtersRef.current = resetFilters;
    setRunError(undefined); setPlaying(false); setSelection(undefined); selectionAnchorRef.current = undefined; setFilters(resetFilters);
    setClockPosition(undefined); setPositionInitialized(false); restoredPositionRef.current = undefined; lastFrameSchedule.current = undefined;
    rangeRef.current = undefined; windowRangeRef.current = undefined; windowLoadingRef.current = false; refreshedWindowRef.current = undefined;
    densityAttemptsRef.current = 0; setWindowSpanMs(DEFAULT_WINDOW_SPAN_MS); setNarrowedSpanMs(undefined); setEvidenceIncomplete(false); setEvidenceLoading(false); setWindowNotice(undefined); setFilterOptions({ sensorIds: [], actorIds: [], statuses: [] });
    verifiedRun.current = undefined;
    checkedRun.current = undefined;
    void (async () => {
      try {
        const checked = await api<ReplayVerification>(`/runs/${encodeURIComponent(runId)}/replay/verify`, { method: "POST", signal: controller.signal });
        if (!current || generation !== runGeneration.current || activeRunId.current !== runId) return;
        checkedRun.current = { runId, generation };
        setVerification(checked);
        if (!checked.matches) { cancelPendingSave(); setReplayStatus("blocked"); return; }
        verifiedRun.current = { runId, generation };
        verifiedDigestRef.current = checked.actualSemanticDigest ?? checked.expectedSemanticDigest;
        // Bootstrap from the privacy-safe projection. Oracle session data is requested only
        // after the user deliberately opts into Oracle mode for this controller instance.
        const rawSession = await api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session`, { signal: controller.signal });
        if (!current || generation !== runGeneration.current || !isVerifiedRun()) return;
        const restored = normalizeSession(rawSession);
        if (restored.filters.visibilityMode === "oracle" && !oracleAvailableRef.current) {
          restored.filters = { ...restored.filters, visibilityMode: "observable", actorIds: [], selectedResidentId: undefined };
        }
        const trusted = restored.playable && restored.verifiedDigest === (checked.actualSemanticDigest ?? checked.expectedSemanticDigest);
        restoredPositionRef.current = trusted ? timestamp(restored.positionAt) : undefined;
        const restoredFilters = trusted ? restored.filters : defaultFilters();
        filtersRef.current = restoredFilters;
        setSession(restored);
        setFilters(restoredFilters);
        setClockPosition(undefined);
        setPositionInitialized(false);
      } catch (reason) {
        if (!current || generation !== runGeneration.current || isAbort(reason)) return;
        blockReplay(reason);
      }
    })();
    return () => { current = false; controller.abort(); oracleSessionAbort.current?.abort(); };
  }, [blockReplay, cancelPendingSave, isVerifiedRun, runId, setClockPosition, setReplayStatus, setRunError, setSelection]);

  // No saved instant is trusted before the range is known: clamp it after obtaining the trace.
  useEffect(() => {
    if (!verifiedForCurrentRun || positionInitialized) return;
    const controller = new AbortController();
    windowAbort.current?.abort(); windowAbort.current = controller;
    const version = ++windowVersion.current;
    windowLoadingRef.current = true;
    void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?limit=1`, { signal: controller.signal })
      .then((window) => {
        if (controller.signal.aborted || !isVerifiedRun() || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        if (start === undefined || end === undefined) throw new ApiError("Replay trace timestamps are invalid", 0);
        rangeRef.current = { start, end }; windowRangeRef.current = { start, end };
        const restored = restoredPositionRef.current ?? start;
        setClockPosition(Math.min(end, Math.max(start, restored))); setPositionInitialized(true); windowLoadingRef.current = false; setReplayStatus("ready");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || !isVerifiedRun() || isAbort(reason) || version !== windowVersion.current) return;
        blockReplay(reason);
      });
    return () => controller.abort();
  }, [blockReplay, isVerifiedRun, positionInitialized, runId, setClockPosition, setReplayStatus, verifiedForCurrentRun]);

  // Windows change for navigation and filters, never for every animation tick.
  useEffect(() => {
    if (!verifiedForCurrentRun || status !== "ready" || !positionInitialized || positionRef.current === undefined) return;
    const center = positionRef.current;
    const controller = new AbortController();
    const version = ++windowVersion.current;
    windowLoadingRef.current = true;
    const effectiveSpanMs = narrowedSpanMs ?? windowSpanMs;
    const query = new URLSearchParams({
      start: new Date(center - effectiveSpanMs / 2).toISOString(), end: new Date(center + effectiveSpanMs / 2).toISOString(), limit: String(WINDOW_LIMIT),
    });
    if (filters.eventKinds.length) query.set("kinds", filters.eventKinds.join(","));
    if (filters.statuses.length) query.set("statuses", filters.statuses.join(","));
    if (filters.sensorIds.length) query.set("sensor_id", filters.sensorIds[0] ?? "");
    if (filters.visibilityMode === "oracle") {
      query.set("include_oracle", "true");
      if (filters.actorIds.length) query.set("actor_id", filters.actorIds[0] ?? "");
    }
    const catalogController = new AbortController();
    catalogAbort.current?.abort(); catalogAbort.current = catalogController;
    const needsCatalog = filters.eventKinds.length > 0 || filters.sensorIds.length > 0 || filters.actorIds.length > 0 || filters.statuses.length > 0;
    if (needsCatalog) {
      const catalogQuery = new URLSearchParams({
        start: new Date(center - effectiveSpanMs / 2).toISOString(), end: new Date(center + effectiveSpanMs / 2).toISOString(), limit: String(WINDOW_LIMIT),
      });
      if (filters.visibilityMode === "oracle") catalogQuery.set("include_oracle", "true");
      void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?${catalogQuery.toString()}`, { signal: catalogController.signal })
        .then((catalog) => {
          if (catalogController.signal.aborted || !isVerifiedRun() || version !== windowVersion.current) return;
          setFilterOptions((current) => ({
            sensorIds: [...new Set([...current.sensorIds, ...catalog.items.flatMap((item) => item.sensorId ? [item.sensorId] : []), ...filters.sensorIds])].sort(),
            actorIds: filters.visibilityMode === "oracle" ? [...new Set([...current.actorIds, ...catalog.items.flatMap((item) => item.actorId ? [item.actorId] : []), ...filters.actorIds])].sort() : current.actorIds,
            statuses: [...new Set([...current.statuses, ...catalog.items.flatMap((item) => item.status ? [item.status] : []), ...filters.statuses])].sort(),
          }));
        }).catch(() => undefined);
    }
    requestFrame(center);
    void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?${query.toString()}`, { signal: controller.signal })
      .then((window) => {
        if (controller.signal.aborted || !isVerifiedRun() || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        const windowStart = timestamp(window.windowStart); const windowEnd = timestamp(window.windowEnd);
        if (start !== undefined && end !== undefined) rangeRef.current = { start, end };
        if (windowStart !== undefined && windowEnd !== undefined) windowRangeRef.current = { start: windowStart, end: windowEnd };
        // A truncated raw response is still authoritative enough to offer safe recovery choices.
        setFilterOptions((current) => ({
          sensorIds: [...new Set([...current.sensorIds, ...window.items.flatMap((item) => item.sensorId ? [item.sensorId] : []), ...filters.sensorIds])].sort(),
          actorIds: filters.visibilityMode === "oracle" ? [...new Set([...current.actorIds, ...window.items.flatMap((item) => item.actorId ? [item.actorId] : []), ...filters.actorIds])].sort() : [],
          statuses: [...new Set([...current.statuses, ...window.items.flatMap((item) => item.status ? [item.status] : []), ...filters.statuses])].sort(),
        }));
        if (window.total > window.items.length) {
          const nextSpan = Math.max(MIN_WINDOW_SPAN_MS, Math.floor(effectiveSpanMs / 2));
          if (nextSpan < effectiveSpanMs && densityAttemptsRef.current < MAX_DENSITY_REQUERIES) {
            densityAttemptsRef.current += 1;
            frameVersion.current += 1; lastFrameSchedule.current = undefined;
            setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined); setEvidenceIncomplete(true); setEvidenceLoading(false);
            setNarrowedSpanMs(nextSpan);
            setWindowNotice("Narrowing dense evidence to retrieve a complete window.");
            return;
          }
          windowLoadingRef.current = false;
          frameVersion.current += 1; lastFrameSchedule.current = undefined;
          setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined); setEvidenceIncomplete(true); setEvidenceLoading(false);
          setWindowNotice("Evidence window is incomplete at this density; narrow the evidence filters before inspecting results.");
          return;
        }
        setFilterOptions((current) => ({
          sensorIds: [...new Set([...current.sensorIds, ...window.items.flatMap((item) => item.sensorId ? [item.sensorId] : []), ...filters.sensorIds])].sort(),
          actorIds: [...new Set([...current.actorIds, ...window.items.flatMap((item) => item.actorId ? [item.actorId] : []), ...filters.actorIds])].sort(),
          statuses: [...new Set([...current.statuses, ...window.items.flatMap((item) => item.status ? [item.status] : []), ...filters.statuses])].sort(),
        }));
        const visibleItems = window.items.filter((item) => matchesFilters(item, filters));
        setEvents({ ...window, items: visibleItems }); setRunError(undefined); windowLoadingRef.current = false;
        densityAttemptsRef.current = 0; setEvidenceIncomplete(false); setEvidenceLoading(false);
        requestFrame(center, true);
        const anchor = selectionAnchorRef.current;
        if (anchor) {
          selectionAnchorRef.current = undefined;
          setSelection(remapAnchor(anchor, visibleItems)?.eventId);
        } else if (selectedEventIdRef.current && !visibleItems.some((item) => item.eventId === selectedEventIdRef.current)) {
          setSelection(undefined);
        }
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || !isVerifiedRun() || isAbort(reason) || version !== windowVersion.current) return;
        blockReplay(reason);
      });
    return () => { controller.abort(); catalogController.abort(); };
  }, [blockReplay, filters, isVerifiedRun, narrowedSpanMs, positionInitialized, requestFrame, runId, setRunError, setSelection, status, verifiedForCurrentRun, windowRequest, windowSpanMs]);

  useEffect(() => {
    if (!verifiedForCurrentRun || !frameRequest || !positionInitialized) return;
    const controller = new AbortController();
    frameAbort.current?.abort(); frameAbort.current = controller;
    const includeOracle = filters.visibilityMode === "oracle" ? "&include_oracle=true" : "";
    void api<ReplayFrame>(`/runs/${encodeURIComponent(runId)}/replay/frame?at=${encodeURIComponent(new Date(frameRequest.at).toISOString())}${includeOracle}`, { signal: controller.signal })
      .then((nextFrame) => {
        if (!controller.signal.aborted && isVerifiedRun() && frameRequest.version === frameVersion.current) {
          setFilterOptions((current) => ({ ...current, actorIds: [...new Set([...current.actorIds, ...nextFrame.residents.flatMap((resident) => resident.residentId ? [resident.residentId] : []), ...filters.actorIds])].sort() }));
          setFrame(nextFrame);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && isVerifiedRun() && !isAbort(reason) && frameRequest.version === frameVersion.current) blockReplay(reason);
      });
    return () => controller.abort();
  }, [blockReplay, filters.actorIds, filters.visibilityMode, frameRequest, isVerifiedRun, positionInitialized, runId, verifiedForCurrentRun]);

  useEffect(() => {
    if (!verifiedForCurrentRun || !playing || status !== "ready" || !positionInitialized) return;
    let animationFrame: number | undefined;
    let previous: number | undefined;
    const tick = () => {
      const now = performance.now(); const range = rangeRef.current;
      if (previous !== undefined && range && positionRef.current !== undefined) {
        const next = advanceTime(positionRef.current, now - previous, filters.speed, range.end, range.start);
        setClockPosition(next);
        const window = windowRangeRef.current;
        if (window) {
          const outsideMargin = next <= window.start + WINDOW_REFRESH_MARGIN_MS || next >= window.end - WINDOW_REFRESH_MARGIN_MS;
          const key = `${window.start}:${window.end}`;
          if (outsideMargin && refreshedWindowRef.current !== key) {
            refreshedWindowRef.current = key;
            requestWindow();
          }
          if (!outsideMargin) refreshedWindowRef.current = undefined;
        }
        if (next >= range.end) {
          requestFrame(range.end, true);
          setPlaying(false);
          return;
        }
      }
      previous = now; animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);
    return () => { if (animationFrame !== undefined) cancelAnimationFrame(animationFrame); };
  }, [filters.speed, playing, positionInitialized, requestFrame, requestWindow, setClockPosition, status, verifiedForCurrentRun]);

  useEffect(() => {
    if (!verifiedForCurrentRun || !playing || status !== "ready" || !positionInitialized) return;
    const timer = window.setInterval(() => requestFrame(), FRAME_CADENCE_MS);
    return () => window.clearInterval(timer);
  }, [playing, positionInitialized, requestFrame, status, verifiedForCurrentRun]);

  useEffect(() => {
    if (!verifiedForCurrentRun || statusRef.current !== "ready" || !positionInitialized || positionMs === undefined
      || !persistenceEnabledRef.current || oracleSessionPendingRef.current) return;
    if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current);
    saveRequest.current?.abort();
    const version = ++saveVersion.current;
    const saveRunId = runId;
    const saveGeneration = runGeneration.current;
    const timer = window.setTimeout(() => {
      saveTimer.current = undefined;
      const verified = verifiedRun.current;
      if (
        activeRunId.current !== saveRunId
        || runGeneration.current !== saveGeneration
        || verified?.runId !== saveRunId
        || verified.generation !== saveGeneration
        || statusRef.current !== "ready"
        || version !== saveVersion.current
      ) return;
      const controller = new AbortController(); saveRequest.current = controller;
      const includeOracle = filters.visibilityMode === "oracle" ? "?include_oracle=true" : "";
      void api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session${includeOracle}`, {
        method: "PUT", body: JSON.stringify({ positionAt: new Date(positionMs).toISOString(), filters }), signal: controller.signal,
      }).then((next) => {
        if (!controller.signal.aborted && isReplayReady() && version === saveVersion.current) setSession(normalizeSession(next));
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && isReplayReady() && version === saveVersion.current) setRunError(apiError(reason));
      });
    }, SESSION_DEBOUNCE_MS);
    saveTimer.current = timer;
    return () => { window.clearTimeout(timer); if (saveTimer.current === timer) saveTimer.current = undefined; saveRequest.current?.abort(); };
  }, [filters, isReplayReady, positionInitialized, positionMs, runId, setRunError, status, verifiedForCurrentRun]);

  useEffect(() => () => { if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current); saveRequest.current?.abort(); }, []);

  const seek = useCallback((nextPosition: number) => {
    if (!isReplayReady() || evidenceIncomplete) return;
    persistenceEnabledRef.current = true;
    const range = rangeRef.current;
    const clamped = range ? Math.min(range.end, Math.max(range.start, nextPosition)) : nextPosition;
    densityAttemptsRef.current = 0; setNarrowedSpanMs(undefined); setWindowNotice(undefined);
    setPlaying(false); setClockPosition(clamped);
    if (positionInitialized) { refreshedWindowRef.current = undefined; requestWindow(true); requestFrame(clamped, true); }
  }, [evidenceIncomplete, isReplayReady, positionInitialized, requestFrame, requestWindow, setClockPosition]);

  const pause = useCallback(() => setPlaying(false), []);
  const play = useCallback(() => {
    const range = rangeRef.current;
    if (!isReplayReady() || evidenceIncomplete || !positionInitialized || positionRef.current === undefined || (range && positionRef.current >= range.end)) return;
    persistenceEnabledRef.current = true;
    setPlaying(true);
  }, [evidenceIncomplete, isReplayReady, positionInitialized]);

  const selectEvent = useCallback((eventId?: string) => {
    if (!isReplayReady() || evidenceIncomplete) return;
    setSelection(eventId);
    const at = timestamp(events?.items.find((event) => event.eventId === eventId)?.at);
    if (at !== undefined) seek(at);
  }, [events, evidenceIncomplete, isReplayReady, seek, setSelection]);

  const step = useCallback((direction: -1 | 1) => {
    if (!isReplayReady() || evidenceIncomplete) return;
    const ordered = [...(events?.items ?? [])].sort((left, right) => Date.parse(left.at) - Date.parse(right.at));
    if (ordered.length === 0) return;
    const currentAt = positionRef.current;
    if (currentAt === undefined) return;
    const targetAt = direction === 1
      ? ordered.find((event) => (timestamp(event.at) ?? Number.POSITIVE_INFINITY) > currentAt)
      : [...ordered].reverse().find((event) => (timestamp(event.at) ?? Number.NEGATIVE_INFINITY) < currentAt);
    const at = timestamp(targetAt?.at);
    const candidate: ReplayEvent | undefined = at === undefined
      ? undefined
      : ordered.find((event) => timestamp(event.at) === at);
    if (!candidate) return;
    setSelection(candidate.eventId);
    if (at !== undefined) seek(at);
  }, [events, evidenceIncomplete, isReplayReady, seek, setSelection]);

  const applyFilters = useCallback((requested: ReplayFilters) => {
    if (!isReplayReady()) return;
    const current = filtersRef.current;
    const next = normalizeFilters(requested);
    if (sameFilters(current, next)) return;
    persistenceEnabledRef.current = true;
    // An already-due timer can run before React commits this state change, so fence it here.
    cancelPendingSave();
    const visibilityWillChange = current.visibilityMode !== next.visibilityMode;
    if (visibilityWillChange) {
      const selected = events?.items.find((event) => event.eventId === selectedEventIdRef.current);
      selectionAnchorRef.current = selected ? anchorFor(selected, events?.items ?? []) : undefined;
    }
    const evidenceFiltersChanged = current.eventKinds.join("\0") !== next.eventKinds.join("\0")
      || current.actorIds.join("\0") !== next.actorIds.join("\0")
      || current.sensorIds.join("\0") !== next.sensorIds.join("\0")
      || current.statuses.join("\0") !== next.statuses.join("\0");
    // Cancel obsolete evidence before React can commit a projection at another privacy level.
    if (evidenceFiltersChanged || visibilityWillChange) invalidateEvidence();
    densityAttemptsRef.current = 0; setNarrowedSpanMs(undefined);
    if (evidenceIncomplete) {
      setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined);
      setWindowNotice("Narrowing dense evidence to retrieve a complete window.");
    } else if (evidenceFiltersChanged) {
      setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined); setEvidenceLoading(true); setWindowNotice(undefined);
    } else {
      setEvidenceIncomplete(false); setWindowNotice(undefined);
    }
    if (visibilityWillChange) {
      setEvents(undefined);
      setFrame(undefined);
      if (next.visibilityMode === "observable") setFilterOptions((options) => ({ ...options, actorIds: [] }));
      setSelection(undefined);
      setSession((existing) => existing ? { ...existing, filters: next } : existing);
    }
    const selected = events?.items.find((event) => event.eventId === selectedEventIdRef.current);
    if (selected && !matchesFilters(selected, next)) {
      selectionAnchorRef.current = undefined;
      setSelection(undefined);
    }
    filtersRef.current = next;
    setFilters(next);
  }, [cancelPendingSave, events, evidenceIncomplete, invalidateEvidence, isReplayReady, setSelection]);
  const updateFilters = useCallback((patch: Partial<ReplayFilters>) => {
    if (!isReplayReady()) return;
    if (patch.visibilityMode === "oracle" && !oracleAvailableRef.current) return;
    const current = filtersRef.current;
    const next = normalizeFilters({ ...current, ...patch });

    if (oracleSessionPendingRef.current && patch.visibilityMode === "observable") {
      oracleSessionAbort.current?.abort(); oracleSessionAbort.current = undefined;
      oracleSessionPendingRef.current = false; oracleSessionAttemptedRef.current = false;
    }
    if (sameFilters(current, next)) return;
    const firstOracleOptIn = current.visibilityMode === "observable"
      && next.visibilityMode === "oracle"
      && !oracleSessionAttemptedRef.current;
    if (!firstOracleOptIn) {
      if (oracleSessionPendingRef.current && next.visibilityMode === "oracle") return;
      applyFilters(next);
      return;
    }

    // The first Oracle transition is two-phase: keep Observable evidence mounted while the
    // durable Oracle projection is fetched, then commit exactly one privacy-level change.
    oracleSessionAttemptedRef.current = true;
    oracleSessionPendingRef.current = true;
    cancelPendingSave();
    const controller = new AbortController();
    oracleSessionAbort.current?.abort(); oracleSessionAbort.current = controller;
    const requestRunId = runId;
    const requestGeneration = runGeneration.current;
    const expectedDigest = verifiedDigestRef.current;
    const isCurrentRequest = () => !controller.signal.aborted
      && activeRunId.current === requestRunId
      && runGeneration.current === requestGeneration
      && isVerifiedRun();
    const explicitOracle = () => normalizeFilters({ ...filtersRef.current, ...patch, visibilityMode: "oracle" });
    void api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session?include_oracle=true`, { signal: controller.signal })
      .then((rawSession) => {
        if (!isCurrentRequest()) return;
        oracleSessionAbort.current = undefined; oracleSessionPendingRef.current = false;
        const restored = normalizeSession(rawSession);
        const trusted = Boolean(expectedDigest)
          && restored.runId === requestRunId
          && restored.playable
          && restored.verifiedDigest === expectedDigest
          && restored.filters.visibilityMode === "oracle";
        const restoredFilters = trusted ? restored.filters : explicitOracle();
        if (trusted) {
          const currentPosition = positionRef.current;
          setSession({
            ...restored,
            positionAt: currentPosition === undefined ? restored.positionAt : new Date(currentPosition).toISOString(),
            filters: restoredFilters,
          });
        }
        applyFilters(restoredFilters);
      })
      .catch((reason: unknown) => {
        if (isAbort(reason) || !isCurrentRequest()) return;
        oracleSessionAbort.current = undefined; oracleSessionPendingRef.current = false;
        // Oracle evidence itself remains usable when only session restoration is unavailable.
        // Continue with the user's explicit patch and never borrow identities from the failure.
        applyFilters(explicitOracle());
      });
  }, [applyFilters, cancelPendingSave, isReplayReady, isVerifiedRun, runId]);
  const setWindowSpan = useCallback((nextSpan: number) => {
    if (!Number.isFinite(nextSpan) || nextSpan < MIN_WINDOW_SPAN_MS || !isReplayReady()) return;
    invalidateEvidence(); densityAttemptsRef.current = 0; setNarrowedSpanMs(undefined);
    if (evidenceIncomplete) {
      setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined);
      setWindowNotice("Narrowing dense evidence to retrieve a complete window.");
    } else {
      setPlaying(false); setEvents(undefined); setFrame(undefined); setSelection(undefined); setEvidenceLoading(true);
      setEvidenceIncomplete(false); setWindowNotice(undefined);
    }
    setWindowSpanMs(nextSpan); requestWindow(true);
  }, [evidenceIncomplete, invalidateEvidence, isReplayReady, requestWindow, setSelection]);

  const visibleStatus = verifiedForCurrentRun
    ? status
    : (errorGeneration.current === runGeneration.current || checkedRun.current?.generation === runGeneration.current) && status === "blocked"
      ? "blocked"
      : "verifying";
  return {
    status: visibleStatus,
    verification: verifiedForCurrentRun || checkedRun.current?.generation === runGeneration.current ? verification : undefined,
    session: verifiedForCurrentRun ? session : undefined,
    positionMs: verifiedForCurrentRun ? positionMs ?? 0 : 0,
    traceStartMs: verifiedForCurrentRun ? rangeRef.current?.start : undefined,
    traceEndMs: verifiedForCurrentRun ? rangeRef.current?.end : undefined,
    playing: verifiedForCurrentRun && playing,
    filters: verifiedForCurrentRun ? filters : defaultFilters(),
    selectedEventId: verifiedForCurrentRun ? selectedEventId : undefined,
    events: verifiedForCurrentRun ? events : undefined,
    frame: verifiedForCurrentRun ? frame : undefined,
    error: errorGeneration.current === runGeneration.current ? error : undefined,
    windowSpanMs, evidenceIncomplete, evidenceLoading, windowNotice, filterOptions,
    play, pause, seek, step, selectEvent, updateFilters, setWindowSpan,
  };
}
