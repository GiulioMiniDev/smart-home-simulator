import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type {
  ReplayEvent,
  ReplayEventWindow,
  ReplayFilters,
  ReplayFrame,
  ReplaySessionState,
  ReplayStatus,
  ReplayVerification,
} from "../types";
import { advanceTime } from "./replay-clock";

const WINDOW_RADIUS_MS = 15 * 60 * 1000;
const WINDOW_LIMIT = 2_000;
const SESSION_DEBOUNCE_MS = 400;

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
  const [positionMs, setPositionMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [filters, setFilters] = useState<ReplayFilters>(defaultFilters);
  const [selectedEventId, setSelectedEventId] = useState<string>();
  const [events, setEvents] = useState<ReplayEventWindow>();
  const [frame, setFrame] = useState<ReplayFrame>();
  const [error, setError] = useState<ApiError>();
  const positionRef = useRef(positionMs);
  const rangeRef = useRef<{ start: number; end: number } | undefined>(undefined);
  const requestVersion = useRef(0);
  const saveTimer = useRef<number | undefined>(undefined);
  const saveRequest = useRef<AbortController | undefined>(undefined);
  const saveVersion = useRef(0);

  useEffect(() => { positionRef.current = positionMs; }, [positionMs]);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setStatus("verifying");
    setVerification(undefined);
    setSession(undefined);
    setEvents(undefined);
    setFrame(undefined);
    setError(undefined);
    setPlaying(false);
    setSelectedEventId(undefined);
    setFilters(defaultFilters());
    rangeRef.current = undefined;
    void (async () => {
      try {
        const checked = await api<ReplayVerification>(`/runs/${encodeURIComponent(runId)}/replay/verify`, {
          method: "POST", signal: controller.signal,
        });
        if (!current) return;
        setVerification(checked);
        if (!checked.matches) {
          setStatus("blocked");
          return;
        }
        const restored = await api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session`, {
          signal: controller.signal,
        });
        if (!current) return;
        const verifiedDigest = checked.actualSemanticDigest ?? checked.expectedSemanticDigest;
        const canRestore = restored.playable && restored.verifiedDigest === verifiedDigest;
        const restoredPosition = canRestore ? timestamp(restored.positionAt) : undefined;
        setSession(restored);
        setFilters(canRestore ? { ...defaultFilters(), ...restored.filters } : defaultFilters());
        setPositionMs(restoredPosition ?? 0);
        setStatus("ready");
      } catch (reason) {
        if (!current || isAbort(reason)) return;
        setError(apiError(reason));
        setStatus("blocked");
      }
    })();
    return () => {
      current = false;
      controller.abort();
    };
  }, [runId]);

  useEffect(() => {
    if (status !== "ready") return;
    const controller = new AbortController();
    const version = ++requestVersion.current;
    const query = new URLSearchParams({
      start: new Date(positionMs - WINDOW_RADIUS_MS).toISOString(),
      end: new Date(positionMs + WINDOW_RADIUS_MS).toISOString(),
      limit: String(WINDOW_LIMIT),
    });
    if (filters.eventKinds.length) query.set("kinds", filters.eventKinds.join(","));
    if (filters.sensorIds.length) query.set("sensor_id", filters.sensorIds[0] ?? "");
    if (filters.visibilityMode === "oracle") {
      query.set("include_oracle", "true");
      if (filters.actorIds.length) query.set("actor_id", filters.actorIds[0] ?? "");
    }
    const base = `/runs/${encodeURIComponent(runId)}/replay`;
    void (async () => {
      try {
        const [window, nextFrame] = await Promise.all([
          api<ReplayEventWindow>(`${base}/events?${query.toString()}`, { signal: controller.signal }),
          api<ReplayFrame>(`${base}/frame?at=${encodeURIComponent(new Date(positionMs).toISOString())}${filters.visibilityMode === "oracle" ? "&include_oracle=true" : ""}`, { signal: controller.signal }),
        ]);
        if (controller.signal.aborted || version !== requestVersion.current) return;
        const start = timestamp(window.traceStart);
        const end = timestamp(window.traceEnd);
        if (start !== undefined && end !== undefined) {
          rangeRef.current = { start, end };
          const clamped = Math.min(end, Math.max(start, positionRef.current));
          if (clamped !== positionRef.current) setPositionMs(clamped);
        }
        const visibleItems = window.items.filter((item) =>
          filters.statuses.length === 0 || (item.status !== null && item.status !== undefined && filters.statuses.includes(item.status)),
        );
        setEvents({ ...window, items: visibleItems });
        setFrame(nextFrame);
        setError(undefined);
      } catch (reason) {
        if (controller.signal.aborted || isAbort(reason) || version !== requestVersion.current) return;
        setError(apiError(reason));
      }
    })();
    return () => controller.abort();
  }, [filters, positionMs, runId, status]);

  useEffect(() => {
    if (!playing || status !== "ready") return;
    let animationFrame: number | undefined;
    let previous: number | undefined;
    const tick = () => {
      const now = performance.now();
      const range = rangeRef.current;
      if (previous !== undefined && range) {
        const next = advanceTime(positionRef.current, now - previous, filters.speed, range.end, range.start);
        setPositionMs(next);
        if (next >= range.end) {
          setPlaying(false);
          return;
        }
      }
      previous = now;
      animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);
    return () => { if (animationFrame !== undefined) cancelAnimationFrame(animationFrame); };
  }, [filters.speed, playing, status]);

  useEffect(() => {
    if (status !== "ready") return;
    if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current);
    saveRequest.current?.abort();
    const version = ++saveVersion.current;
    const timer = window.setTimeout(() => {
      saveTimer.current = undefined;
      const controller = new AbortController();
      saveRequest.current = controller;
      const includeOracle = filters.visibilityMode === "oracle" ? "?include_oracle=true" : "";
      void api<ReplaySessionState>(`/runs/${encodeURIComponent(runId)}/replay/session${includeOracle}`, {
        method: "PUT",
        body: JSON.stringify({ positionAt: new Date(positionMs).toISOString(), filters }),
        signal: controller.signal,
      }).then((next) => {
        if (!controller.signal.aborted && version === saveVersion.current) setSession(next);
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && version === saveVersion.current) setError(apiError(reason));
      });
    }, SESSION_DEBOUNCE_MS);
    saveTimer.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (saveTimer.current === timer) saveTimer.current = undefined;
      saveRequest.current?.abort();
    };
  }, [filters, positionMs, runId, status]);

  useEffect(() => () => {
    if (saveTimer.current !== undefined) window.clearTimeout(saveTimer.current);
    saveRequest.current?.abort();
  }, []);

  const seek = useCallback((nextPosition: number) => {
    const range = rangeRef.current;
    const clamped = range ? Math.min(range.end, Math.max(range.start, nextPosition)) : nextPosition;
    setPlaying(false);
    setPositionMs(clamped);
  }, []);

  const pause = useCallback(() => setPlaying(false), []);
  const play = useCallback(() => {
    const range = rangeRef.current;
    if (status !== "ready" || (range && positionRef.current >= range.end)) return;
    setPlaying(true);
  }, [status]);

  const selectEvent = useCallback((eventId?: string) => {
    setSelectedEventId(eventId);
    const selected = events?.items.find((event) => event.eventId === eventId);
    const at = timestamp(selected?.at);
    if (at !== undefined) seek(at);
  }, [events, seek]);

  const step = useCallback((direction: -1 | 1) => {
    const ordered = [...(events?.items ?? [])].sort((left, right) => Date.parse(left.at) - Date.parse(right.at));
    if (ordered.length === 0) return;
    const selectedIndex = ordered.findIndex((event) => event.eventId === selectedEventId);
    const candidate: ReplayEvent | undefined = selectedIndex >= 0
      ? ordered[selectedIndex + direction]
      : direction === 1
        ? ordered.find((event) => (timestamp(event.at) ?? Number.POSITIVE_INFINITY) > positionRef.current)
        : ordered.filter((event) => (timestamp(event.at) ?? Number.NEGATIVE_INFINITY) < positionRef.current).at(-1);
    if (!candidate) return;
    setSelectedEventId(candidate.eventId);
    const at = timestamp(candidate.at);
    if (at !== undefined) seek(at);
  }, [events, seek, selectedEventId]);

  const updateFilters = useCallback((patch: Partial<ReplayFilters>) => {
    setFilters((current) => ({ ...current, ...patch }));
  }, []);

  return { status, verification, session, positionMs, playing, filters, selectedEventId, events, frame, error, play, pause, seek, step, selectEvent, updateFilters };
}
