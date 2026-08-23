import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(frontendRoot, "..", "..");
const workspaceRoot = path.join(repositoryRoot, "reports", "e2e-workspace");
const metadataPath = path.join(repositoryRoot, "reports", "e2e-replay-run.json");
const port = 8766;
const baseUrl = `http://127.0.0.1:${port}`;

type FixtureMetadata = { runId: string };

function pythonCommand(): { executable: string; prefix: string[] } {
  if (process.platform === "win32") {
    return { executable: path.join(repositoryRoot, ".venv", "Scripts", "python.exe"), prefix: [] };
  }
  return { executable: "uv", prefix: ["--project", repositoryRoot, "run"] };
}

function buildWorkspace(): FixtureMetadata {
  const command = pythonCommand();
  execFileSync(
    command.executable,
    [
      ...command.prefix,
      ...(process.platform === "win32" ? [] : ["python"]),
      path.join(repositoryRoot, "tools", "build_replay_e2e_workspace.py"),
    ],
    {
      cwd: repositoryRoot,
      env: { ...process.env, PYTHONPATH: path.join(repositoryRoot, "src"), UV_NO_EDITABLE: "1" },
      stdio: "inherit",
    },
  );
  return JSON.parse(readFileSync(metadataPath, "utf8")) as FixtureMetadata;
}

async function assertPortIsFree(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const probe = net.createServer();
    probe.once("error", (error: NodeJS.ErrnoException) => {
      reject(new Error(
        error.code === "EADDRINUSE"
          ? `Playwright E2E refuses to reuse a server on ${baseUrl}; stop the stale server and retry.`
          : `Unable to reserve ${baseUrl}: ${error.message}`,
      ));
    });
    probe.listen(port, "127.0.0.1", () => probe.close(() => resolve()));
  });
}

function startBackend(): ChildProcess {
  const command = pythonCommand();
  return spawn(
    command.executable,
    [
      ...command.prefix,
      ...(process.platform === "win32" ? ["-m", "smart_home_sim.web.launcher"] : ["smart-home-sim-app"]),
      "--workspace",
      workspaceRoot,
      "--name",
      "E2E",
      "--port",
      String(port),
      "--no-browser",
    ],
    {
      cwd: repositoryRoot,
      env: { ...process.env, PYTHONPATH: path.join(repositoryRoot, "src"), UV_NO_EDITABLE: "1" },
      // The launcher is long lived; unread pipes can block it during a browser run.
      stdio: "ignore",
    },
  );
}

async function waitForExpectedWorkspace(runId: string, child: ChildProcess): Promise<void> {
  const deadline = Date.now() + 120_000;
  let lastError = "backend did not respond";
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`E2E backend stopped before becoming ready (exit ${child.exitCode}).`);
    }
    try {
      const session = await fetch(`${baseUrl}/api/session`);
      if (!session.ok) throw new Error(`session returned ${session.status}`);
      const token = (await session.json() as { token?: string }).token;
      const job = await fetch(`${baseUrl}/api/jobs/${runId}`, {
        headers: token ? { "X-Workspace-Token": token } : {},
      });
      if (job.ok) return;
      lastError = `server answered for a different workspace (run ${runId} returned ${job.status})`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`E2E backend did not serve the freshly built workspace: ${lastError}`);
}

async function stopBackend(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  child.kill();
  await new Promise((resolve) => setTimeout(resolve, 300));
  if (child.exitCode === null && process.platform === "win32" && child.pid) {
    try {
      execFileSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      // The launcher can exit between the liveness check and taskkill on Windows.
    }
  }
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  // Building happens before port inspection deliberately: a reuseExistingServer-style path must
  // never let stale state skip fixture construction.  A listener is then a hard failure.
  const fixture = buildWorkspace();
  await assertPortIsFree();
  const child = startBackend();
  try {
    await waitForExpectedWorkspace(fixture.runId, child);
  } catch (error) {
    await stopBackend(child);
    throw error;
  }
  return () => stopBackend(child);
}
