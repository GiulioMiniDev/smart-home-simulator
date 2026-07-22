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
    expect(result.current.error).toMatchObject({ message: "Error: offline", status: 0 });
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

  it("reads and writes stored values", () => {
    localStorage.setItem("setting", JSON.stringify("dark"));
    const { result } = renderHook(() => useStoredState("setting", "light"));
    expect(result.current[0]).toBe("dark");
    act(() => result.current[1]("light"));
    expect(result.current[0]).toBe("light");
    expect(localStorage.getItem("setting")).toBe('"light"');
  });
});
