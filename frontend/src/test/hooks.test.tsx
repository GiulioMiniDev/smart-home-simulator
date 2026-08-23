import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useResource, useStoredState } from "../hooks";

describe("resource and persistent-state hooks", () => {
  beforeEach(() => { sessionStorage.setItem("habitat-lab-session", "token"); localStorage.clear(); });

  it("loads and reloads a resource", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ value: 4 }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useResource<{ value: number }>("/value"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.value).toBe(4);
    await act(() => result.current.reload());
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("normalizes resource errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { result } = renderHook(() => useResource("/value"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    // A rejected fetch is the server being gone, and says so rather than repeating the browser's
    // own wording for it.
    expect(result.current.error).toMatchObject({ status: 0, code: "SERVER_UNREACHABLE" });
    expect(result.current.error?.message).toContain("stopped responding");
  });

  it("keeps a disabled resource idle without issuing a request", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(
      ({ path }: { path?: string }) => useResource(path),
      { initialProps: { path: undefined as string | undefined } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).not.toHaveBeenCalled();
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ready: true }), { status: 200 }));
    rerender({ path: "/enabled" });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  });

  it("aborts and hides an obsolete URL response while the newer resource wins", async () => {
    const pending: Array<{ signal: AbortSignal; resolve: (response: Response) => void }> = [];
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve) => {
      pending.push({ signal: init?.signal as AbortSignal, resolve });
    })));
    const { result, rerender, unmount } = renderHook(
      ({ path }: { path: string }) => useResource<{ value: string }>(path),
      { initialProps: { path: "/oracle" } },
    );
    await waitFor(() => expect(pending).toHaveLength(1));
    rerender({ path: "/observable" });
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0]?.signal.aborted).toBe(true);
    expect(result.current.data).toBeUndefined();
    await act(async () => { pending[0]?.resolve(new Response(JSON.stringify({ value: "oracle" }))); });
    expect(result.current.data).toBeUndefined();
    await act(async () => { pending[1]?.resolve(new Response(JSON.stringify({ value: "observable" }))); });
    await waitFor(() => expect(result.current.data?.value).toBe("observable"));
    unmount();
    expect(pending[1]?.signal.aborted).toBe(true);
  });

  it("keeps the newest same-URL reload when an aborted earlier reload finishes late", async () => {
    const pending: Array<{ signal: AbortSignal; resolve: (response: Response) => void }> = [];
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve) => {
      pending.push({ signal: init?.signal as AbortSignal, resolve });
    })));
    const { result } = renderHook(() => useResource<{ value: string }>("/same"));
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => { pending[0]?.resolve(new Response(JSON.stringify({ value: "initial" }))); });
    await waitFor(() => expect(result.current.data?.value).toBe("initial"));
    act(() => { void result.current.reload(); });
    await waitFor(() => expect(pending).toHaveLength(2));
    act(() => { void result.current.reload(); });
    await waitFor(() => expect(pending).toHaveLength(3));
    expect(pending[1]?.signal.aborted).toBe(true);
    await act(async () => { pending[2]?.resolve(new Response(JSON.stringify({ value: "newest" }))); });
    await waitFor(() => expect(result.current.data?.value).toBe("newest"));
    await act(async () => { pending[1]?.resolve(new Response(JSON.stringify({ value: "stale" }))); });
    expect(result.current.data?.value).toBe("newest");
  });

  it("reads and writes stored values", () => {
    localStorage.setItem("setting", JSON.stringify("dark"));
    const { result } = renderHook(() => useStoredState("setting", "light"));
    expect(result.current[0]).toBe("dark");
    act(() => result.current[1]("light"));
    expect(result.current[0]).toBe("light");
    expect(localStorage.getItem("setting")).toBe('"light"');
  });
});
