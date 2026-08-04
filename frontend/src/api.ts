const SESSION_KEY = "habitat-lab-session";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "REQUEST_FAILED",
  ) {
    super(message);
  }
}

async function sessionToken(): Promise<string> {
  const existing = sessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const response = await fetch("/api/session");
  if (!response.ok) throw new ApiError("Could not start a local session", response.status);
  const payload = (await response.json()) as { token: string };
  sessionStorage.setItem(SESSION_KEY, payload.token);
  return payload.token;
}

async function requestWithSession(path: string, options: RequestInit = {}): Promise<Response> {
  const token = await sessionToken();
  const headers = new Headers(options.headers);
  headers.set("X-Workspace-Token", token);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status !== 401) return response;
  clearSession();
  const refreshedToken = await sessionToken();
  const refreshedHeaders = new Headers(options.headers);
  refreshedHeaders.set("X-Workspace-Token", refreshedToken);
  if (options.body && !refreshedHeaders.has("Content-Type")) {
    refreshedHeaders.set("Content-Type", "application/json");
  }
  return fetch(`/api${path}`, { ...options, headers: refreshedHeaders });
}

/** The server accepted the connection and then vanished, or was never there. */
export const SERVER_UNREACHABLE = "SERVER_UNREACHABLE";

export type ServerHealth = {
  status: string;
  inFlight: number;
  operation: {
    operationId: string;
    method: string;
    path: string;
    stage: string;
    elapsedSeconds: number;
  } | null;
};

/**
 * Is the local server alive, and does it still have `operationId` in hand?
 *
 * Unauthenticated and deliberately independent of `api`: it is polled while another request is
 * outstanding, so it must not fail for the same reason that request might.
 */
export async function health(operationId?: string): Promise<ServerHealth | null> {
  try {
    const query = operationId ? `?operation=${encodeURIComponent(operationId)}` : "";
    const response = await fetch(`/api/health${query}`);
    if (!response.ok) return null;
    return (await response.json()) as ServerHealth;
  } catch {
    return null;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await requestWithSession(path, options);
  } catch (reason) {
    // A session bootstrap that answered with an HTTP error already knows what went wrong; only a
    // rejected fetch means the connection itself never completed — the server exited mid-request,
    // or it was never running. Left as a bare TypeError that surfaces as "Failed to fetch", which
    // says nothing about which side stopped.
    if (reason instanceof ApiError) throw reason;
    throw new ApiError(
      "The local server stopped responding, so the request never completed. It may have crashed — "
        + "check the console window it was started from, and server-errors.log in the workspace "
        + "folder.",
      0,
      SERVER_UNREACHABLE,
    );
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string }; detail?: { code?: string; message?: string } }
      | null;
    const detail = payload?.error ?? payload?.detail;
    throw new ApiError(detail?.message ?? response.statusText, response.status, detail?.code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function eventSourceUrl(jobId: string, after = 0): Promise<string> {
  const token = await sessionToken();
  return `/api/jobs/${encodeURIComponent(jobId)}/events?token=${encodeURIComponent(token)}&after=${after}`;
}

export async function download(path: string, fallbackName: string): Promise<void> {
  const token = await sessionToken();
  const response = await fetch(`/api${path}`, {
    headers: { "X-Workspace-Token": token },
  });
  if (!response.ok) throw new ApiError(response.statusText, response.status);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const filename = encoded ? decodeURIComponent(encoded) : (plain ?? fallbackName);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}
