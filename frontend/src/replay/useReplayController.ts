import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { ReplayEvent, ReplayEventWindow, ReplayFilters, ReplayFrame, ReplaySessionState, ReplayStatus, ReplayVerification } from "../types";
import { advanceTime } from "./replay-clock";

const WINDOW_RADIUS_MS = 15 * 60 * 1000;
const WINDOW_REFRESH_MARGIN_MS = 5 * 60 * 1000;
const WINDOW_LIMIT = 2_000;
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

export interface ReplayController {
  status: ReplayStatus;
  verification?: ReplayVerification;
  session?: ReplaySessionState;
  positionMs: number;
  playing: boolean;
  filters: ReplayFilters;
  selectedEventId?: string;
  events?: ReplayEventWindow;
  frame?: ReplayFrame;
  error?: ApiError;
  play(): void;
  pause(): void;
  seek(positionMs: number): void;
  step(direction: -1 | 1): void;
  selectEvent(eventId?: string): void;
  updateFilters(patch: Partial<ReplayFilters>): void;
}

export function useReplayController(runId: string): ReplayController {
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
  const positionRef = useRef<number | undefined>(undefined);
  const restoredPositionRef = useRef<number | undefined>(undefined);
  const rangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowRangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowLoadingRef = useRef(false);
  const refreshedWindowRef = useRef<string | undefined>(undefined);
  const windowVersion = useRef(0);
  const frameVersion = useRef(0);
  const lastFrameSchedule = useRef<{ at: number; scheduledAt: number } | undefined>(undefined);
  const saveTimer = useRef<number | undefined>(undefined);
  const saveRequest = useRef<AbortController | undefined>(undefined);
  const saveVersion = useRef(0);
  const activeRunId = useRef(runId);
  const runGeneration = useRef(0);
  const verifiedRun = useRef<{ runId: string; generation: number } | undefined>(undefined);
  const checkedRun = useRef<{ runId: string; generation: number } | undefined>(undefined);
  const errorGeneration = useRef<number | undefined>(undefined);

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
  const verifiedForCurrentRun = isVerifiedRun();
  const setRunError = useCallback((next: ApiError | undefined) => {
    errorGeneration.current = next ? runGeneration.current : undefined;
    setError(next);
  }, []);

  const setClockPosition = useCallback((next: number | undefined) => {
    positionRef.current = next;
    setPositionMs(next);
  }, []);
  const requestFrame = useCallback((at = positionRef.current, immediate = false) => {
    if (!isVerifiedRun() || at === undefined) return;
    const now = performance.now();
    const previous = lastFrameSchedule.current;
    if (!immediate && previous && now - previous.scheduledAt < FRAME_CADENCE_MS) return;
    if (immediate && previous?.at === at && now - previous.scheduledAt < FRAME_CADENCE_MS) return;
    lastFrameSchedule.current = { at, scheduledAt: now };
    setFrameRequest({ at, version: ++frameVersion.current });
  }, [isVerifiedRun]);
  const requestWindow = useCallback((force = false) => {
    if (!isVerifiedRun()) return;
    if (force || !windowLoadingRef.current) {
      windowLoadingRef.current = true;
      setWindowRequest((current) => current + 1);
    }
  }, [isVerifiedRun]);

  useEffect(() => {
    const controller = new AbortController();
    const generation = runGeneration.current;
    let current = true;
    setStatus("verifying"); setVerification(undefined); setSession(undefined); setEvents(undefined); setFrame(undefined);
    setRunError(undefined); setPlaying(false); setSelectedEventId(undefined); setFilters(defaultFilters());
    setClockPosition(undefined); setPositionInitialized(false); restoredPositionRef.current = undefined; lastFrameSchedule.current = undefined;
    rangeRef.current = undefined; windowRangeRef.current = undefined; windowLoadingRef.current = false; refreshedWindowRef.current = undefined;
    verifiedRun.current = undefined;
    checkedRun.current = undefined;
    void (async () => {
      try {
        const checked = await api<ReplayVerification>(`/runs/${encodeURIComponent(runId)}/replay/verify`, { method: "POST", signal: controller.signal });
        if (!current || generation !== runGeneration.current || activeRunId.current !== runId) return;
        checkedRun.current = { runId, generation };
        setVerification(checked);
        if (!checked.matches) { setStatus("blocked"); return; }
        verifiedRun.current = { runId, generation };
        const rawSession = await api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session`, { signal: controller.signal });
        if (!current || generation !== runGeneration.current || !isVerifiedRun()) return;
        const restored = normalizeSession(rawSession);
        const trusted = restored.playable && restored.verifiedDigest === (checked.actualSemanticDigest ?? checked.expectedSemanticDigest);
        restoredPositionRef.current = trusted ? timestamp(restored.positionAt) : undefined;
        setSession(restored);
        setFilters(trusted ? restored.filters : defaultFilters());
        setClockPosition(undefined);
        setPositionInitialized(false);
        setStatus("ready");
      } catch (reason) {
        if (!current || generation !== runGeneration.current || isAbort(reason)) return;
        setRunError(apiError(reason)); setStatus("blocked");
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [isVerifiedRun, runId, setClockPosition, setRunError]);

  // No saved instant is trusted before the range is known: clamp it after obtaining the trace.
  useEffect(() => {
    if (!verifiedForCurrentRun || status !== "ready" || positionInitialized) return;
    const controller = new AbortController();
    const version = ++windowVersion.current;
    windowLoadingRef.current = true;
    void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?limit=1`, { signal: controller.signal })
      .then((window) => {
        if (controller.signal.aborted || !isVerifiedRun() || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        if (start === undefined || end === undefined) throw new ApiError("Replay trace timestamps are invalid", 0);
        rangeRef.current = { start, end }; windowRangeRef.current = { start, end };
        const restored = restoredPositionRef.current ?? start;
        setClockPosition(Math.min(end, Math.max(start, restored))); setPositionInitialized(true); windowLoadingRef.current = false;
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || !isVerifiedRun() || isAbort(reason) || version !== windowVersion.current) return;
        windowLoadingRef.current = false; setRunError(apiError(reason));
      });
    return () => controller.abort();
  }, [isVerifiedRun, positionInitialized, runId, setClockPosition, setRunError, status, verifiedForCurrentRun]);

  // Windows change for navigation and filters, never for every animation tick.
  useEffect(() => {
    if (!verifiedForCurrentRun || status !== "ready" || !positionInitialized || positionRef.current === undefined) return;
    const center = positionRef.current;
    const controller = new AbortController();
    const version = ++windowVersion.current;
    windowLoadingRef.current = true;
    const query = new URLSearchParams({
      start: new Date(center - WINDOW_RADIUS_MS).toISOString(), end: new Date(center + WINDOW_RADIUS_MS).toISOString(), limit: String(WINDOW_LIMIT),
    });
    if (filters.eventKinds.length) query.set("kinds", filters.eventKinds.join(","));
    if (filters.sensorIds.length) query.set("sensor_id", filters.sensorIds[0] ?? "");
    if (filters.visibilityMode === "oracle") {
      query.set("include_oracle", "true");
      if (filters.actorIds.length) query.set("actor_id", filters.actorIds[0] ?? "");
    }
    requestFrame(center);
    void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?${query.toString()}`, { signal: controller.signal })
      .then((window) => {
        if (controller.signal.aborted || !isVerifiedRun() || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        const windowStart = timestamp(window.windowStart); const windowEnd = timestamp(window.windowEnd);
        if (start !== undefined && end !== undefined) rangeRef.current = { start, end };
        if (windowStart !== undefined && windowEnd !== undefined) windowRangeRef.current = { start: windowStart, end: windowEnd };
        const visibleItems = window.items.filter((item) => filters.statuses.length === 0 || (item.status !== null && item.status !== undefined && filters.statuses.includes(item.status)));
        setEvents({ ...window, items: visibleItems }); setRunError(undefined); windowLoadingRef.current = false;
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || !isVerifiedRun() || isAbort(reason) || version !== windowVersion.current) return;
        windowLoadingRef.current = false; setRunError(apiError(reason));
      });
    return () => controller.abort();
  }, [filters, isVerifiedRun, positionInitialized, requestFrame, runId, setRunError, status, verifiedForCurrentRun, windowRequest]);

  useEffect(() => {
    if (!verifiedForCurrentRun || !frameRequest || !positionInitialized) return;
    const controller = new AbortController();
    const includeOracle = filters.visibilityMode === "oracle" ? "&include_oracle=true" : "";
    void api<ReplayFrame>(`/runs/${encodeURIComponent(runId)}/replay/frame?at=${encodeURIComponent(new Date(frameRequest.at).toISOString())}${includeOracle}`, { signal: controller.signal })
      .then((nextFrame) => {
        if (!controller.signal.aborted && isVerifiedRun() && frameRequest.version === frameVersion.current) setFrame(nextFrame);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && isVerifiedRun() && !isAbort(reason) && frameRequest.version === frameVersion.current) setRunError(apiError(reason));
      });
    return () => controller.abort();
  }, [filters.visibilityMode, frameRequest, isVerifiedRun, positionInitialized, runId, setRunError, verifiedForCurrentRun]);

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
    if (!verifiedForCurrentRun || status !== "ready" || !positionInitialized || positionMs === undefined) return;
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
        || version !== saveVersion.current
      ) return;
      const controller = new AbortController(); saveRequest.current = controller;
      const includeOracle = filters.visibilityMode === "oracle" ? "?include_oracle=true" : "";
      void api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session${includeOracle}`, {
        method: "PUT", body: JSON.stringify({ positionAt: new Date(positionMs).toISOString(), filters }), signal: controller.signal,
      }).then((next) => {
        if (!controller.signal.aborted && isVerifiedRun() && version === saveVersion.current) setSession(normalizeSession(next));
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && isVerifiedRun() && version === saveVersion.current) setRunError(apiError(reason));
      });
    }, SESSION_DEBOUNCE_MS);
    saveTimer.current = timer;
    return () => { window.clearTimeout(timer); if (saveTimer.current === timer) saveTimer.current = undefined; saveRequest.current?.abort(); };
  }, [filters, isVerifiedRun, positionInitialized, positionMs, runId, setRunError, status, verifiedForCurrentRun]);

  useEffect(() => () => { if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current); saveRequest.current?.abort(); }, []);

  const seek = useCallback((nextPosition: number) => {
    if (!isVerifiedRun()) return;
    const range = rangeRef.current;
    const clamped = range ? Math.min(range.end, Math.max(range.start, nextPosition)) : nextPosition;
    setPlaying(false); setClockPosition(clamped);
    if (positionInitialized) { refreshedWindowRef.current = undefined; requestWindow(true); requestFrame(clamped, true); }
  }, [isVerifiedRun, positionInitialized, requestFrame, requestWindow, setClockPosition]);

  const pause = useCallback(() => setPlaying(false), []);
  const play = useCallback(() => {
    const range = rangeRef.current;
    if (!isVerifiedRun() || status !== "ready" || !positionInitialized || positionRef.current === undefined || (range && positionRef.current >= range.end)) return;
    setPlaying(true);
  }, [isVerifiedRun, positionInitialized, status]);

  const selectEvent = useCallback((eventId?: string) => {
    if (!isVerifiedRun()) return;
    setSelectedEventId(eventId);
    const at = timestamp(events?.items.find((event) => event.eventId === eventId)?.at);
    if (at !== undefined) seek(at);
  }, [events, isVerifiedRun, seek]);

  const step = useCallback((direction: -1 | 1) => {
    if (!isVerifiedRun()) return;
    const ordered = [...(events?.items ?? [])].sort((left, right) => Date.parse(left.at) - Date.parse(right.at));
    if (ordered.length === 0) return;
    const selectedIndex = ordered.findIndex((event) => event.eventId === selectedEventId);
    const candidate: ReplayEvent | undefined = selectedIndex >= 0
      ? ordered[selectedIndex + direction]
      : direction === 1
        ? ordered.find((event) => (timestamp(event.at) ?? Number.POSITIVE_INFINITY) > (positionRef.current ?? Number.NEGATIVE_INFINITY))
        : ordered.filter((event) => (timestamp(event.at) ?? Number.NEGATIVE_INFINITY) < (positionRef.current ?? Number.POSITIVE_INFINITY)).at(-1);
    if (!candidate) return;
    setSelectedEventId(candidate.eventId);
    const at = timestamp(candidate.at);
    if (at !== undefined) seek(at);
  }, [events, isVerifiedRun, seek, selectedEventId]);

  const updateFilters = useCallback((patch: Partial<ReplayFilters>) => {
    if (!isVerifiedRun()) return;
    setFilters((current) => {
      const next = normalizeFilters({ ...current, ...patch });
      if (current.visibilityMode === "oracle" && next.visibilityMode === "observable") {
        // Do this in the action, rather than waiting for effects, so Oracle data cannot be painted
        // for even one Observable render. Version bumps also reject responses already in flight.
        windowVersion.current += 1;
        frameVersion.current += 1;
        saveVersion.current += 1;
        // The next Observable window must own a fresh frame, even if an Oracle
        // request was scheduled at this same instant less than one cadence ago.
        lastFrameSchedule.current = undefined;
        saveRequest.current?.abort();
        setEvents(undefined);
        setFrame(undefined);
        setSelectedEventId(undefined);
        setSession((existing) => existing ? { ...existing, filters: next } : existing);
      }
      return next;
    });
  }, [isVerifiedRun]);

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
    playing: verifiedForCurrentRun && playing,
    filters: verifiedForCurrentRun ? filters : defaultFilters(),
    selectedEventId: verifiedForCurrentRun ? selectedEventId : undefined,
    events: verifiedForCurrentRun ? events : undefined,
    frame: verifiedForCurrentRun ? frame : undefined,
    error: errorGeneration.current === runGeneration.current ? error : undefined,
    play, pause, seek, step, selectEvent, updateFilters,
  };
}
