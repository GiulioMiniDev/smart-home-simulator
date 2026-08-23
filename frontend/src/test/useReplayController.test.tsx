import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useReplayController } from "../replay/useReplayController";

const start = "2026-08-23T08:00:00.000Z";
const end = "2026-08-23T09:00:00.000Z";
const digest = "a".repeat(64);

function payload(path: string): unknown {
  if (path.includes("/verify")) return {
    runId: "run_1", verifiedAt: start, matches: true,
    expectedSemanticDigest: digest, actualSemanticDigest: digest,
  };
  if (path.includes("/session")) return {
    runId: "run_1", verifiedDigest: digest, playable: true, positionAt: "2026-08-23T08:15:00.000Z",
    filters: { detailMode: "presentation", visibilityMode: "observable", speed: 2, eventKinds: [], sensorIds: [], statuses: [] },
  };
  if (path.includes("/events")) return {
    items: [{ at: "2026-08-23T08:20:00.000Z", kind: "movement", eventId: "move", label: "Walk", waypoints: [], details: {} }],
    total: 1, traceStart: start, traceEnd: end, windowStart: start, windowEnd: end,
  };
  if (path.includes("/frame")) return {
    runId: "run_1", at: "2026-08-23T08:15:00.000Z", traceStart: start, traceEnd: end,
    residents: [], sensorStates: [], entityStates: {}, environmentFacts: {}, resourceAvailableUnits: {}, activeEventIds: [],
  };
  throw new Error(`Unexpected request ${path}`);
}

async function settleController(): Promise<void> {
  await act(async () => {
    for (let tick = 0; tick < 12; tick += 1) await Promise.resolve();
  });
}

describe("useReplayController", () => {
  beforeEach(() => {
    sessionStorage.setItem("habitat-lab-session", "token");
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(
      new Response(JSON.stringify(payload(String(input))), { status: 200 }),
    )));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("verifies automatically, restores a matching session and requests a bounded window", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("ready");
    expect(result.current.positionMs).toBe(Date.parse("2026-08-23T08:15:00.000Z"));
    const paths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input));
    expect(paths).toContain("/api/runs/run_1/replay/verify");
    expect(paths).toContain("/api/runs/run_1/replay/session");
    const events = paths.find((path) => path.includes("/replay/events"));
    expect(events).toContain("limit=2000");
    expect(events).not.toContain("include_oracle=true");
  });

  it("bootstraps a playable session without a saved position from trace start, never epoch zero", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        runId: "run_1", verifiedDigest: digest, playable: true, positionAt: null,
        filters: { detailMode: "presentation", visibilityMode: "observable", speed: 1, eventKinds: [], sensorIds: [], statuses: [] },
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const paths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input));
    const bootstrap = paths.find((path) => path.includes("/replay/events"));
    expect(bootstrap).toContain("limit=1");
    expect(bootstrap).not.toContain("start=");
    expect(bootstrap).not.toContain("end=");
    expect(paths.some((path) => path.includes("1970-"))).toBe(false);
    expect(result.current.positionMs).toBe(Date.parse(start));
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    const saved = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(String((saved?.[1] as RequestInit).body)).not.toContain("1970-");
  });

  it("normalizes an observable session into complete safe filters", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.filters.actorIds).toEqual([]);
    expect(result.current.filters.selectedResidentId).toBeUndefined();
    expect(result.current.session?.filters.actorIds).toEqual([]);
    expect(result.current.session?.filters.selectedResidentId).toBeUndefined();
  });

  it("treats an invalid saved timestamp as an uninitialized session", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, positionAt: "not-a-time",
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.positionMs).toBe(Date.parse(start));
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.some(([input]) => String(input).includes("1970-"))).toBe(false);
  });

  it("clears Oracle-only identity filters before an observable request or save", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.updateFilters({ visibilityMode: "oracle", actorIds: ["resident"], selectedResidentId: "resident" }));
    await settleController();
    act(() => result.current.updateFilters({ visibilityMode: "observable" }));
    expect(result.current.filters).toMatchObject({ visibilityMode: "observable", actorIds: [], selectedResidentId: undefined });
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    const save = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    ).at(-1);
    expect(String(save?.[0])).not.toContain("include_oracle=true");
    expect(String((save?.[1] as RequestInit).body)).toContain('"actorIds":[]');
    expect(String((save?.[1] as RequestInit).body)).not.toContain("selectedResidentId");
  });

  it("keeps RAF playback local while bounding frame requests to ten per second", async () => {
    const callbacks: Array<() => void> = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => { callbacks.push(callback); return callbacks.length; }));
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const initialFrames = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/frame")).length;
    act(() => result.current.play());
    for (let frame = 0; frame < 60; frame += 1) {
      now += 1000 / 60;
      const callback = callbacks.shift();
      await act(async () => { callback?.(); await Promise.resolve(); });
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    await settleController();
    const requests = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/frame")).length;
    expect(requests - initialFrames).toBeLessThanOrEqual(10);
  });

  it("aborts an obsolete event window when a newer seek supersedes it", async () => {
    const signals: AbortSignal[] = [];
    let deferWindows = false;
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/events") && deferWindows) {
        signals.push(init?.signal as AbortSignal);
        return new Promise<Response>(() => undefined);
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    deferWindows = true;
    act(() => result.current.seek(Date.parse("2026-08-23T08:20:00.000Z")));
    await settleController();
    act(() => result.current.seek(Date.parse("2026-08-23T08:30:00.000Z")));
    await settleController();
    expect(signals).toHaveLength(2);
    expect(signals[0]?.aborted).toBe(true);
  });

  it("refreshes a window boundary once rather than once per animation frame", async () => {
    const callbacks: Array<() => void> = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => { callbacks.push(callback); return callbacks.length; }));
    let now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, positionAt: start,
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const initialWindows = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/events")).length;
    act(() => result.current.play());
    for (let frame = 0; frame < 20; frame += 1) {
      now += 1000 / 60;
      const callback = callbacks.shift();
      await act(async () => { callback?.(); await Promise.resolve(); });
    }
    await settleController();
    const windows = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/events")).length;
    expect(windows - initialWindows).toBeLessThanOrEqual(1);
  });

  it("blocks playback when verification does not match", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(new Response(JSON.stringify({
      ...payload(String(input)) as object, matches: false, actualSemanticDigest: "b".repeat(64),
    }), { status: 200 }))));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("blocked");
    act(() => result.current.play());
    expect(result.current.playing).toBe(false);
  });

  it("seeks forward and backward stably, preserves the instant across detail mode, and persists after debounce", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("ready");
    const target = Date.parse("2026-08-23T08:30:00.000Z");
    act(() => result.current.seek(target));
    act(() => result.current.seek(Date.parse("2026-08-23T08:15:00.000Z")));
    act(() => result.current.seek(target));
    act(() => result.current.updateFilters({ detailMode: "analysis" }));
    expect(result.current.positionMs).toBe(target);
    expect(result.current.filters.detailMode).toBe("analysis");
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    const saves = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(saves).toHaveLength(1);
  });

  it("does not let an older debounced session save overwrite a newer seek", async () => {
    let putCount = 0;
    let resolveFirst: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      if (String(input).includes("/replay/session") && init?.method === "PUT") {
        const saved = JSON.parse(String(init.body)) as { positionAt: string; filters: object };
        const response = new Response(JSON.stringify({
          runId: "run_1", verifiedDigest: digest, playable: true, positionAt: saved.positionAt, filters: saved.filters,
        }), { status: 200 });
        putCount += 1;
        if (putCount === 1) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
        return Promise.resolve(response);
      }
      return Promise.resolve(new Response(JSON.stringify(payload(String(input))), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const first = Date.parse("2026-08-23T08:25:00.000Z");
    const second = Date.parse("2026-08-23T08:35:00.000Z");
    act(() => result.current.seek(first));
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    act(() => result.current.seek(second));
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    await settleController();
    resolveFirst?.(new Response(JSON.stringify({
      runId: "run_1", verifiedDigest: digest, playable: true, positionAt: new Date(first).toISOString(), filters: result.current.filters,
    }), { status: 200 }));
    await settleController();
    expect(result.current.session?.positionAt).toBe(new Date(second).toISOString());
  });

  it("invalidates a stale session and sends identity filters only after Oracle is chosen", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/session") && !path.includes("?")) return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, verifiedDigest: "b".repeat(64), positionAt: "2026-08-23T08:15:00.000Z",
        filters: { eventKinds: [], actorIds: ["resident"], sensorIds: [], statuses: [], detailMode: "analysis", visibilityMode: "oracle", speed: 8 },
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.positionMs).toBe(Date.parse(start));
    expect(result.current.filters).toMatchObject({ speed: 1, detailMode: "presentation", visibilityMode: "observable" });
    act(() => result.current.updateFilters({
      visibilityMode: "oracle", actorIds: ["resident"], sensorIds: ["sensor"], eventKinds: ["movement"],
    }));
    await settleController();
    const oraclePaths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input))
      .filter((path) => path.includes("/replay/events") || path.includes("/replay/frame"));
    expect(oraclePaths.some((path) => path.includes("include_oracle=true") && path.includes("actor_id=resident"))).toBe(true);
    expect(oraclePaths.some((path) => path.includes("sensor_id=sensor") && path.includes("kinds=movement"))).toBe(true);
  });

  it("selects and steps individual events in timestamp order", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events")) return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object,
        items: [
          { at: "2026-08-23T08:10:00.000Z", kind: "action", eventId: "first", label: "First", waypoints: [], details: {} },
          { at: "2026-08-23T08:20:00.000Z", kind: "action", eventId: "second", label: "Second", waypoints: [], details: {} },
        ],
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.selectEvent("first"));
    act(() => result.current.step(1));
    expect(result.current.selectedEventId).toBe("second");
    expect(result.current.positionMs).toBe(Date.parse("2026-08-23T08:20:00.000Z"));
    act(() => result.current.step(-1));
    expect(result.current.selectedEventId).toBe("first");
  });

  it("uses request-animation-frame deltas and pauses at the trace end", async () => {
    const callbacks: Array<(at: number) => void> = [];
    const raf = vi.fn((callback: (at: number) => void) => { callbacks.push(callback); return callbacks.length; });
    const now = vi.spyOn(performance, "now").mockReturnValueOnce(0).mockReturnValueOnce(10_000_000);
    vi.stubGlobal("requestAnimationFrame", raf);
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.play());
    const first = callbacks[0];
    act(() => first?.(0));
    const second = callbacks[1];
    act(() => second?.(10_000_000));
    expect(result.current.positionMs).toBe(Date.parse(end));
    expect(result.current.playing).toBe(false);
    expect(now).toHaveBeenCalledTimes(2);
  });

  it("blocks with an actionable error when verification cannot be requested", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("blocked");
    expect(result.current.error?.message).toContain("stopped responding");
  });

  it("handles an empty filtered event window without changing the clock", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events")) return Promise.resolve(new Response(JSON.stringify({ ...payload(path) as object, items: [] }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const before = result.current.positionMs;
    act(() => result.current.step(1));
    expect(result.current.positionMs).toBe(before);
  });

  it("keeps only status-filtered events and safely ignores unavailable steps", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events")) return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object,
        items: [
          { at: "2026-08-23T08:10:00.000Z", kind: "action", eventId: "complete", label: "Complete", status: "completed", waypoints: [], details: {} },
          { at: "2026-08-23T08:20:00.000Z", kind: "action", eventId: "pending", label: "Pending", status: "pending", waypoints: [], details: {} },
        ],
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.updateFilters({ statuses: ["completed"] }));
    await settleController();
    expect(result.current.events?.items.map((event) => event.eventId)).toEqual(["complete"]);
    const before = result.current.positionMs;
    act(() => result.current.selectEvent());
    act(() => result.current.step(1));
    expect(result.current.positionMs).toBe(before);
  });

  it("keeps transport ready while exposing an event-window request failure", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events")) return Promise.reject(new Error("window unavailable"));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("ready");
    expect(result.current.error?.message).toContain("stopped responding");
  });
});
