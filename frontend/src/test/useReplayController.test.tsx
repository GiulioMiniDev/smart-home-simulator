import { StrictMode } from "react";
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
    expect(paths).toContain("/api/runs/run_1/replay/session?include_oracle=true");
    expect(paths.find((path) => path.includes("/replay/events"))).toContain("limit=1");
    const events = paths.find((path) => path.includes("/replay/events") && path.includes("limit=5000"));
    expect(events).toContain("limit=5000");
    expect(events).not.toContain("include_oracle=true");
  });

  it("restores a digest-verified Oracle session before requesting Oracle evidence", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/replay/session") && !path.includes("?include_oracle=true")) {
        return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
      }
      if (path.includes("/replay/session?include_oracle=true")) {
        return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object,
          filters: { detailMode: "analysis", visibilityMode: "oracle", speed: 1, eventKinds: [], sensorIds: [], statuses: [], actorIds: ["resident"], selectedResidentId: "resident" },
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1", { oracleAvailable: true }));
    await settleController();
    expect(result.current.filters).toMatchObject({ visibilityMode: "oracle", actorIds: ["resident"], selectedResidentId: "resident" });
    const paths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input));
    expect(paths).toContain("/api/runs/run_1/replay/session?include_oracle=true");
    expect(paths.some((path) => path.includes("include_oracle=true") && path.includes("actor_id=resident"))).toBe(true);
  });

  it("uses the chosen temporal span for centered event-window requests", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const windowPaths = () => (fetch as ReturnType<typeof vi.fn>).mock.calls
      .map(([input]) => String(input))
      .filter((path) => path.includes("/replay/events?") && path.includes("limit=5000"));
    const spanFor = (path: string) => {
      const query = new URL(path, "http://localhost").searchParams;
      return Date.parse(query.get("end") ?? "") - Date.parse(query.get("start") ?? "");
    };
    act(() => result.current.setWindowSpan(5 * 60 * 1000));
    await settleController();
    expect(spanFor(windowPaths().at(-1)!)).toBe(5 * 60 * 1000);
    act(() => result.current.setWindowSpan(24 * 60 * 60 * 1000));
    await settleController();
    expect(spanFor(windowPaths().at(-1)!)).toBe(24 * 60 * 60 * 1000);
  });

  it("narrows a dense event window before exposing evidence, then retains the complete response", async () => {
    let denseResponses = 0;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/replay/events") && !path.includes("limit=1") && denseResponses++ === 0) {
        return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object, total: 2_001,
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(denseResponses).toBeGreaterThan(1);
    expect(result.current.evidenceIncomplete).toBe(false);
    expect(result.current.events?.items).toHaveLength(1);
    expect(result.current.windowNotice).toMatch(/Narrowing dense evidence/);
  });

  it("blocks inspection instead of rendering a permanently truncated minimum-span window", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/replay/events") && !path.includes("limit=1")) {
        return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object, total: 5_001,
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.setWindowSpan(5 * 60 * 1000));
    await act(async () => {
      for (let tick = 0; tick < 30; tick += 1) await Promise.resolve();
    });
    expect(result.current.evidenceIncomplete).toBe(true);
    expect(result.current.events).toBeUndefined();
    expect(result.current.windowNotice).toMatch(/incomplete/);
  });

  it("keeps dense-window recovery catalogs available without retaining Oracle residents after downgrade", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/replay/events") && !path.includes("limit=1")) {
        return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object, total: 5_001,
          items: [{ at: "2026-08-23T08:20:00.000Z", kind: "observation", eventId: "sensor", label: "Observation event", sensorId: "door", status: "pending", actorId: path.includes("include_oracle=true") ? "resident" : undefined, waypoints: [], details: {} }],
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1", { oracleAvailable: true }));
    await settleController();
    act(() => result.current.setWindowSpan(5 * 60 * 1000));
    await act(async () => { for (let tick = 0; tick < 30; tick += 1) await Promise.resolve(); });
    expect(result.current.filterOptions).toMatchObject({ sensorIds: ["door"], statuses: ["pending"], actorIds: [] });
    act(() => result.current.updateFilters({ visibilityMode: "oracle" }));
    await act(async () => { for (let tick = 0; tick < 30; tick += 1) await Promise.resolve(); });
    expect(result.current.filterOptions.actorIds).toContain("resident");
    act(() => result.current.updateFilters({ visibilityMode: "observable" }));
    expect(result.current.filterOptions.actorIds).toEqual([]);
  });

  it("recovers complete replay evidence when a narrower filter changes an incomplete window", async () => {
    let dense = true;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (dense && path.includes("/replay/events") && !path.includes("limit=1")) {
        return Promise.resolve(new Response(JSON.stringify({ ...payload(path) as object, total: 5_001 }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.setWindowSpan(5 * 60 * 1000));
    await act(async () => { for (let tick = 0; tick < 30; tick += 1) await Promise.resolve(); });
    expect(result.current.evidenceIncomplete).toBe(true);
    expect(result.current.playing).toBe(false);
    expect(result.current.frame).toBeUndefined();
    dense = false;
    act(() => result.current.updateFilters({ eventKinds: ["movement"] }));
    await settleController();
    expect(result.current.evidenceIncomplete).toBe(false);
    expect(result.current.events?.items).toHaveLength(1);
  });

  it("fences a replaced run behind its own verification generation", async () => {
    let resolveRunBVerification: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/runs/run_b/replay/verify")) {
        return new Promise<Response>((resolve) => { resolveRunBVerification = resolve; });
      }
      const run = path.includes("/runs/run_b/") ? "run_b" : "run_a";
      return Promise.resolve(new Response(JSON.stringify({ ...payload(path) as object, runId: run }), { status: 200 }));
    }));
    const { result, rerender } = renderHook(({ runId }: { runId: string }) => useReplayController(runId), {
      initialProps: { runId: "run_a" },
    });
    await settleController();
    act(() => result.current.updateFilters({ visibilityMode: "oracle", actorIds: ["mario"] }));
    await settleController();
    act(() => result.current.selectEvent("move"));
    expect(result.current.selectedEventId).toBe("move");
    rerender({ runId: "run_b" });
    await settleController();
    expect(result.current.status).toBe("verifying");
    expect(result.current.session).toBeUndefined();
    expect(result.current.events).toBeUndefined();
    expect(result.current.frame).toBeUndefined();
    expect(result.current.selectedEventId).toBeUndefined();
    expect(result.current.filters).toMatchObject({ visibilityMode: "observable", actorIds: [] });
    act(() => result.current.updateFilters({ visibilityMode: "oracle", actorIds: ["mario"] }));
    expect(result.current.filters).toMatchObject({ visibilityMode: "observable", actorIds: [] });
    const beforeVerification = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/runs/run_b/"));
    expect(beforeVerification).toHaveLength(1);
    expect(String(beforeVerification[0]?.[0])).toContain("/runs/run_b/replay/verify");
    resolveRunBVerification?.(new Response(JSON.stringify({
      ...payload("/verify") as object, runId: "run_b",
    }), { status: 200 }));
    await settleController();
    const runBPaths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input)).filter((path) => path.includes("/runs/run_b/"));
    expect(runBPaths).toContain("/api/runs/run_b/replay/session?include_oracle=true");
    expect(runBPaths.filter((path) => path.includes("/replay/events") || path.includes("/replay/frame")).some((path) => path.includes("include_oracle=true"))).toBe(false);
  });

  it("rejects an already-due save after rerender replaces its run", async () => {
    let resolveRunBVerification: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/runs/run_b/replay/verify")) {
        return new Promise<Response>((resolve) => { resolveRunBVerification = resolve; });
      }
      const run = path.includes("/runs/run_b/") ? "run_b" : "run_a";
      if (path.includes("/session") && init?.method === "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, runId: run,
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ ...payload(path) as object, runId: run }), { status: 200 }));
    }));
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const { result, rerender } = renderHook(({ runId }: { runId: string }) => useReplayController(runId), {
      initialProps: { runId: "run_a" },
    });
    await settleController();
    act(() => result.current.seek(Date.parse("2026-08-23T08:20:00.000Z")));
    const dueSave = setTimeoutSpy.mock.calls.filter(([, delay]) => delay === 400).at(-1)?.[0];
    expect(dueSave).toBeTypeOf("function");
    rerender({ runId: "run_b" });
    // Model a debounce task that became due just before React cleaned up the old effect.
    act(() => { if (typeof dueSave === "function") dueSave(); });
    await settleController();
    const saves = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(saves).toHaveLength(0);
    expect(result.current.status).toBe("verifying");
    resolveRunBVerification?.(new Response(JSON.stringify({ ...payload("/verify") as object, runId: "run_b" }), { status: 200 }));
    await settleController();
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
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, filters: {},
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
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

  it.each([
    ["past", "2026-08-22T08:00:00.000Z", Date.parse(start)],
    ["future", "2026-08-24T08:00:00.000Z", Date.parse(end)],
  ])("clamps a %s restored position only after loading the trace range", async (_label, positionAt, expected) => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, positionAt,
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.positionMs).toBe(expected);
    const paths = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input]) => String(input));
    expect(paths.find((path) => path.includes("/replay/events"))).toContain("limit=1");
    expect(paths.filter((path) => path.includes("/replay/events") || path.includes("/replay/frame")).some((path) => path.includes(encodeURIComponent(positionAt)))).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    const saved = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    ).at(-1);
    expect(String((saved?.[1] as RequestInit).body)).toContain(new Date(expected).toISOString());
  });

  it("coalesces the window-triggered frame behind one immediate seek frame", async () => {
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const initial = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/frame")).length;
    act(() => result.current.seek(Date.parse("2026-08-23T08:30:00.000Z")));
    await settleController();
    const frames = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input]) => String(input).includes("/replay/frame")).length;
    expect(frames - initial).toBe(1);
  });

  it("clears Oracle evidence immediately and ignores a stale Oracle response", async () => {
    let oracle = false;
    let deferOracle = false;
    const delayed: Array<(response: Response) => void> = [];
    const oracleSignals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/events") || path.includes("/frame")) {
        if (oracle && deferOracle) {
          oracleSignals.push(init?.signal as AbortSignal);
          return new Promise<Response>((resolve) => delayed.push(resolve));
        }
        if (oracle && path.includes("/events")) return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object, items: [{ at: start, kind: "action", eventId: "oracle", actorId: "mario", label: "Oracle", waypoints: [], details: {} }],
        }), { status: 200 }));
        if (oracle && path.includes("/frame")) return Promise.resolve(new Response(JSON.stringify({
          ...payload(path) as object, residents: [{ residentId: "mario", executionState: "active", heldResourceIds: [], facts: {} }],
        }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1", { oracleAvailable: true }));
    await settleController();
    oracle = true;
    act(() => result.current.updateFilters({ visibilityMode: "oracle", actorIds: ["mario"] }));
    await settleController();
    expect(result.current.events?.items[0]?.actorId).toBe("mario");
    expect(result.current.frame?.residents[0]?.residentId).toBe("mario");
    act(() => result.current.selectEvent("oracle"));
    expect(result.current.selectedEventId).toBe("oracle");
    deferOracle = true;
    act(() => result.current.seek(Date.parse("2026-08-23T08:20:00.000Z")));
    await settleController();
    oracle = false;
    act(() => result.current.updateFilters({ visibilityMode: "observable" }));
    expect(result.current.events).toBeUndefined();
    expect(result.current.frame).toBeUndefined();
    expect(result.current.selectedEventId).toBeUndefined();
    expect(oracleSignals.every((signal) => signal.aborted)).toBe(true);
    delayed.forEach((resolve) => resolve(new Response(JSON.stringify({
      ...payload("/events") as object, items: [{ at: start, kind: "action", eventId: "oracle", actorId: "mario", label: "Oracle", waypoints: [], details: {} }],
    }), { status: 200 })));
    await settleController();
    expect(result.current.events?.items[0]?.actorId).not.toBe("mario");
    expect(result.current.frame?.residents).toEqual([]);
  });

  it("cleans deferred StrictMode work without saving after unmount", async () => {
    let resolveVerify: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      if (String(input).includes("/verify")) return new Promise<Response>((resolve) => { resolveVerify = resolve; });
      return Promise.resolve(new Response(JSON.stringify(payload(String(input))), { status: 200 }));
    }));
    const { unmount } = renderHook(() => useReplayController("run_1"), { wrapper: StrictMode });
    unmount();
    resolveVerify?.(new Response(JSON.stringify(payload("/verify")), { status: 200 }));
    await settleController();
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    const requests = (fetch as ReturnType<typeof vi.fn>).mock.calls.map(([input, init]) => ({ path: String(input), init: init as RequestInit | undefined }));
    expect(requests.some((request) => request.path.includes("/replay/session") && request.init?.method === "PUT")).toBe(false);
    expect(requests.filter((request) => request.path.includes("/replay/session"))).toHaveLength(0);
  });

  it("aborts deferred StrictMode window, frame, and session-save work on unmount", async () => {
    let defer = false;
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (defer && (path.includes("/replay/events") || path.includes("/replay/frame") || (path.includes("/replay/session") && init?.method === "PUT"))) {
        signals.push(init?.signal as AbortSignal);
        return new Promise<Response>(() => undefined);
      }
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result, unmount } = renderHook(() => useReplayController("run_1"), { wrapper: StrictMode });
    await settleController();
    defer = true;
    act(() => result.current.seek(Date.parse("2026-08-23T08:20:00.000Z")));
    await settleController();
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    unmount();
    expect(signals.length).toBeGreaterThanOrEqual(3);
    expect(signals.every((signal) => signal.aborted)).toBe(true);
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

  it("rejects an already-due same-run save after a newer seek and filter update", async () => {
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.seek(Date.parse("2026-08-23T08:20:00.000Z")));
    const oldSave = setTimeoutSpy.mock.calls.filter(([, delay]) => delay === 400).at(-1)?.[0];
    expect(oldSave).toBeTypeOf("function");
    act(() => result.current.seek(Date.parse("2026-08-23T08:30:00.000Z")));
    act(() => result.current.updateFilters({ detailMode: "analysis" }));
    act(() => { if (typeof oldSave === "function") oldSave(); });
    await settleController();
    const saves = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(saves).toHaveLength(0);
  });

  it("rejects an already-due Oracle save after visibility is revoked", async () => {
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.updateFilters({ visibilityMode: "oracle", actorIds: ["resident"] }));
    const oldSave = setTimeoutSpy.mock.calls.filter(([, delay]) => delay === 400).at(-1)?.[0];
    expect(oldSave).toBeTypeOf("function");
    act(() => result.current.updateFilters({ visibilityMode: "observable" }));
    act(() => { if (typeof oldSave === "function") oldSave(); });
    await settleController();
    const saves = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session") && (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(saves).toHaveLength(0);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([input, init]) =>
      String(input).includes("/replay/session?include_oracle=true") && (init as RequestInit | undefined)?.method === "PUT",
    )).toHaveLength(0);
  });

  it("invalidates a stale session and sends identity filters only after Oracle is chosen", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/session?include_oracle=true")) return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, verifiedDigest: "b".repeat(64), positionAt: "2026-08-23T08:15:00.000Z",
        filters: { eventKinds: [], actorIds: ["resident"], sensorIds: [], statuses: [], detailMode: "analysis", visibilityMode: "oracle", speed: 8 },
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1", { oracleAvailable: true }));
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
    let time = 0;
    const now = vi.spyOn(performance, "now").mockImplementation(() => time);
    vi.stubGlobal("requestAnimationFrame", raf);
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    act(() => result.current.play());
    const first = callbacks[0];
    act(() => first?.(0));
    time = 10_000_000;
    const second = callbacks[1];
    act(() => second?.(10_000_000));
    expect(result.current.positionMs).toBe(Date.parse(end));
    expect(result.current.playing).toBe(false);
    expect(now.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("requests the exact terminal frame once when RAF clamps playback to the trace end", async () => {
    const callbacks: Array<(at: number) => void> = [];
    const raf = vi.fn((callback: (at: number) => void) => { callbacks.push(callback); return callbacks.length; });
    let time = 0;
    vi.spyOn(performance, "now").mockImplementation(() => time);
    vi.stubGlobal("requestAnimationFrame", raf);
    vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/session") && init?.method !== "PUT") return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, positionAt: "2026-08-23T08:55:00.000Z",
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    const endFrame = `/replay/frame?at=${encodeURIComponent(end)}`;
    const endFrames = () => (fetch as ReturnType<typeof vi.fn>).mock.calls
      .map(([input]) => String(input)).filter((path) => path.includes(endFrame));
    expect(endFrames()).toHaveLength(0);
    act(() => result.current.play());
    act(() => callbacks[0]?.(0));
    time = 60_000;
    act(() => callbacks[1]?.(60_000));
    await settleController();
    // The boundary refresh has already been coalesced for this window, so a terminal
    // frame cannot rely on another event-window request to make it to the server.
    time = 10_000_000;
    act(() => callbacks[2]?.(10_000_000));
    await settleController();
    expect(result.current.playing).toBe(false);
    expect(endFrames()).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    await settleController();
    expect(endFrames()).toHaveLength(1);
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

  it("blocks transport when an event-window request fails", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events")) return Promise.reject(new Error("window unavailable"));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.status).toBe("blocked");
    expect(result.current.error?.message).toContain("stopped responding");
  });

  it("reports invalid trace bounds before using a restored position", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/events") && path.includes("limit=1")) return Promise.resolve(new Response(JSON.stringify({
        ...payload(path) as object, traceStart: "not-a-time",
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    expect(result.current.positionMs).toBe(0);
    expect(result.current.error?.message).toContain("timestamps are invalid");
  });

  it("blocks transport when a frame request fails", async () => {
    let rejectFrame: ((reason: Error) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: string | URL) => {
      const path = String(input);
      if (path.includes("/frame")) return new Promise<Response>((_resolve, reject) => { rejectFrame = reject; });
      return Promise.resolve(new Response(JSON.stringify(payload(path)), { status: 200 }));
    }));
    const { result } = renderHook(() => useReplayController("run_1"));
    await settleController();
    rejectFrame?.(new Error("frame unavailable"));
    await settleController();
    expect(result.current.status).toBe("blocked");
    expect(result.current.error?.message).toContain("stopped responding");
  });
});
