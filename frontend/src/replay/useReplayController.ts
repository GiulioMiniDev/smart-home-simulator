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
  const rangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowRangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const windowLoadingRef = useRef(false);
  const refreshedWindowRef = useRef<string | undefined>(undefined);
  const windowVersion = useRef(0);
  const frameVersion = useRef(0);
  const saveTimer = useRef<number | undefined>(undefined);
  const saveRequest = useRef<AbortController | undefined>(undefined);
  const saveVersion = useRef(0);

  const setClockPosition = useCallback((next: number | undefined) => {
    positionRef.current = next;
    setPositionMs(next);
  }, []);
  const requestFrame = useCallback((at = positionRef.current) => {
    if (at !== undefined) setFrameRequest({ at, version: ++frameVersion.current });
  }, []);
  const requestWindow = useCallback((force = false) => {
    if (force || !windowLoadingRef.current) {
      windowLoadingRef.current = true;
      setWindowRequest((current) => current + 1);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setStatus("verifying"); setVerification(undefined); setSession(undefined); setEvents(undefined); setFrame(undefined);
    setError(undefined); setPlaying(false); setSelectedEventId(undefined); setFilters(defaultFilters());
    setClockPosition(undefined); setPositionInitialized(false);
    rangeRef.current = undefined; windowRangeRef.current = undefined; windowLoadingRef.current = false; refreshedWindowRef.current = undefined;
    void (async () => {
      try {
        const checked = await api<ReplayVerification>(`/runs/${encodeURIComponent(runId)}/replay/verify`, { method: "POST", signal: controller.signal });
        if (!current) return;
        setVerification(checked);
        if (!checked.matches) { setStatus("blocked"); return; }
        const rawSession = await api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session`, { signal: controller.signal });
        if (!current) return;
        const restored = normalizeSession(rawSession);
        const trusted = restored.playable && restored.verifiedDigest === (checked.actualSemanticDigest ?? checked.expectedSemanticDigest);
        const restoredPosition = trusted ? timestamp(restored.positionAt) : undefined;
        setSession(restored);
        setFilters(trusted ? restored.filters : defaultFilters());
        setClockPosition(restoredPosition);
        setPositionInitialized(restoredPosition !== undefined);
        setStatus("ready");
      } catch (reason) {
        if (!current || isAbort(reason)) return;
        setError(apiError(reason)); setStatus("blocked");
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [runId, setClockPosition]);

  // No saved instant is not midnight 1970: obtain only the range, then begin at its trace start.
  useEffect(() => {
    if (status !== "ready" || positionInitialized) return;
    const controller = new AbortController();
    const version = ++windowVersion.current;
    windowLoadingRef.current = true;
    void api<ReplayEventWindow>(`/runs/${encodeURIComponent(runId)}/replay/events?limit=1`, { signal: controller.signal })
      .then((window) => {
        if (controller.signal.aborted || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        if (start === undefined || end === undefined) throw new ApiError("Replay trace timestamps are invalid", 0);
        rangeRef.current = { start, end }; windowRangeRef.current = { start, end };
        setClockPosition(start); setPositionInitialized(true); windowLoadingRef.current = false;
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || isAbort(reason) || version !== windowVersion.current) return;
        windowLoadingRef.current = false; setError(apiError(reason));
      });
    return () => controller.abort();
  }, [positionInitialized, runId, setClockPosition, status]);

  // Windows change for navigation and filters, never for every animation tick.
  useEffect(() => {
    if (status !== "ready" || !positionInitialized || positionRef.current === undefined) return;
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
        if (controller.signal.aborted || version !== windowVersion.current) return;
        const start = timestamp(window.traceStart); const end = timestamp(window.traceEnd);
        const windowStart = timestamp(window.windowStart); const windowEnd = timestamp(window.windowEnd);
        if (start !== undefined && end !== undefined) rangeRef.current = { start, end };
        if (windowStart !== undefined && windowEnd !== undefined) windowRangeRef.current = { start: windowStart, end: windowEnd };
        const visibleItems = window.items.filter((item) => filters.statuses.length === 0 || (item.status !== null && item.status !== undefined && filters.statuses.includes(item.status)));
        setEvents({ ...window, items: visibleItems }); setError(undefined); windowLoadingRef.current = false;
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || isAbort(reason) || version !== windowVersion.current) return;
        windowLoadingRef.current = false; setError(apiError(reason));
      });
    return () => controller.abort();
  }, [filters, positionInitialized, requestFrame, runId, status, windowRequest]);

  useEffect(() => {
    if (!frameRequest || !positionInitialized) return;
    const controller = new AbortController();
    const includeOracle = filters.visibilityMode === "oracle" ? "&include_oracle=true" : "";
    void api<ReplayFrame>(`/runs/${encodeURIComponent(runId)}/replay/frame?at=${encodeURIComponent(new Date(frameRequest.at).toISOString())}${includeOracle}`, { signal: controller.signal })
      .then((nextFrame) => {
        if (!controller.signal.aborted && frameRequest.version === frameVersion.current) setFrame(nextFrame);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && !isAbort(reason) && frameRequest.version === frameVersion.current) setError(apiError(reason));
      });
    return () => controller.abort();
  }, [filters.visibilityMode, frameRequest, positionInitialized, runId]);

  useEffect(() => {
    if (!playing || status !== "ready" || !positionInitialized) return;
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
        if (next >= range.end) { setPlaying(false); return; }
      }
      previous = now; animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);
    return () => { if (animationFrame !== undefined) cancelAnimationFrame(animationFrame); };
  }, [filters.speed, playing, positionInitialized, requestWindow, setClockPosition, status]);

  useEffect(() => {
    if (!playing || status !== "ready" || !positionInitialized) return;
    const timer = window.setInterval(() => requestFrame(), FRAME_CADENCE_MS);
    return () => window.clearInterval(timer);
  }, [playing, positionInitialized, requestFrame, status]);

  useEffect(() => {
    if (status !== "ready" || !positionInitialized || positionMs === undefined) return;
    if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current);
    saveRequest.current?.abort();
    const version = ++saveVersion.current;
    const timer = window.setTimeout(() => {
      saveTimer.current = undefined;
      const controller = new AbortController(); saveRequest.current = controller;
      const includeOracle = filters.visibilityMode === "oracle" ? "?include_oracle=true" : "";
      void api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session${includeOracle}`, {
        method: "PUT", body: JSON.stringify({ positionAt: new Date(positionMs).toISOString(), filters }), signal: controller.signal,
      }).then((next) => {
        if (!controller.signal.aborted && version === saveVersion.current) setSession(normalizeSession(next));
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && version === saveVersion.current) setError(apiError(reason));
      });
    }, SESSION_DEBOUNCE_MS);
    saveTimer.current = timer;
    return () => { window.clearTimeout(timer); if (saveTimer.current === timer) saveTimer.current = undefined; saveRequest.current?.abort(); };
  }, [filters, positionInitialized, positionMs, runId, status]);

  useEffect(() => () => { if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current); saveRequest.current?.abort(); }, []);

  const seek = useCallback((nextPosition: number) => {
    const range = rangeRef.current;
    const clamped = range ? Math.min(range.end, Math.max(range.start, nextPosition)) : nextPosition;
    setPlaying(false); setClockPosition(clamped);
    if (positionInitialized) { refreshedWindowRef.current = undefined; requestWindow(true); requestFrame(clamped); }
  }, [positionInitialized, requestFrame, requestWindow, setClockPosition]);

  const pause = useCallback(() => setPlaying(false), []);
  const play = useCallback(() => {
    const range = rangeRef.current;
    if (status !== "ready" || !positionInitialized || positionRef.current === undefined || (range && positionRef.current >= range.end)) return;
    setPlaying(true);
  }, [positionInitialized, status]);

  const selectEvent = useCallback((eventId?: string) => {
    setSelectedEventId(eventId);
    const at = timestamp(events?.items.find((event) => event.eventId === eventId)?.at);
    if (at !== undefined) seek(at);
  }, [events, seek]);

  const step = useCallback((direction: -1 | 1) => {
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
  }, [events, seek, selectedEventId]);

  const updateFilters = useCallback((patch: Partial<ReplayFilters>) => {
    setFilters((current) => normalizeFilters({ ...current, ...patch }));
  }, []);

  return { status, verification, session, positionMs: positionMs ?? 0, playing, filters, selectedEventId, events, frame, error, play, pause, seek, step, selectEvent, updateFilters };
}
