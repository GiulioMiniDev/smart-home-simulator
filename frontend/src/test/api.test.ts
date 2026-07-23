import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clearSession, download, eventSourceUrl } from "../api";

describe("local API client", () => {
  beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });

  it("creates and reuses a session for JSON and SSE requests", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "secret" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(api<{ ok: boolean }>("/overview", { method: "POST", body: "{}" })).resolves.toEqual({ ok: true });
    expect((fetcher.mock.calls[1][1]?.headers as Headers).get("X-Workspace-Token")).toBe("secret");
    expect((fetcher.mock.calls[1][1]?.headers as Headers).get("Content-Type")).toBe("application/json");
    await expect(eventSourceUrl("job / 1", 4)).resolves.toContain("job%20%2F%201");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("refreshes a stale session after a 401 and retries once", async () => {
    sessionStorage.setItem("habitat-lab-session", "stale");
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "SESSION_TOKEN_INVALID", message: "Invalid local session" } }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: "fresh" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(api<{ ok: boolean }>("/overview")).resolves.toEqual({ ok: true });
    expect(sessionStorage.getItem("habitat-lab-session")).toBe("fresh");
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect((fetcher.mock.calls[0][1]?.headers as Headers).get("X-Workspace-Token")).toBe("stale");
    expect((fetcher.mock.calls[2][1]?.headers as Headers).get("X-Workspace-Token")).toBe("fresh");
  });

  it("reports session, structured, plain and empty responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("no", { status: 503 })));
    await expect(api("/overview")).rejects.toMatchObject({ status: 503 });
    sessionStorage.setItem("habitat-lab-session", "token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "BROKEN", message: "Broken" } }), { status: 409 })));
    await expect(api("/bad")).rejects.toEqual(new ApiError("Broken", 409, "BROKEN"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "Detailed" } }), { status: 422, statusText: "Invalid" })));
    await expect(api("/detail")).rejects.toMatchObject({ message: "Detailed", status: 422, code: "REQUEST_FAILED" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("plain failure", { status: 500, statusText: "Server failed" })));
    await expect(api("/plain")).rejects.toMatchObject({ message: "Server failed", status: 500 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api("/empty")).resolves.toBeUndefined();
    clearSession();
    expect(sessionStorage.getItem("habitat-lab-session")).toBeNull();
  });

  it("downloads blobs with server and fallback names", async () => {
    sessionStorage.setItem("habitat-lab-session", "token");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("data", { status: 200, headers: { "Content-Disposition": "attachment; filename*=UTF-8''evidence.csv" } })));
    await download("/file", "fallback.csv");
    expect(click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("data", { status: 200, headers: { "Content-Disposition": "attachment; filename=plain.csv" } })));
    await download("/plain", "fallback.csv");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("data", { status: 200 })));
    await download("/fallback", "fallback.csv");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("bad", { status: 404, statusText: "Missing" })));
    await expect(download("/missing", "fallback")).rejects.toMatchObject({ status: 404 });
  });
});
