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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await requestWithSession(path, options);
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
