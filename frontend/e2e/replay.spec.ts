import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";
import axe from "axe-core";

type ReplayRun = { runId: string };

async function replayRun(): Promise<ReplayRun> {
  return JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as ReplayRun;
}

test("replays one verified run in presentation and analysis modes", async ({ page }) => {
  const run = await replayRun();
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByText("Replay verified")).toBeVisible();
  const time = page.getByRole("slider", { name: "Replay time" });
  const initial = await time.inputValue();
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(() => time.inputValue()).not.toBe(initial);
  await page.getByRole("button", { name: "Open evidence" }).click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await page.getByRole("button", { name: "Oracle" }).click();
  await expect(page.getByText("Simulated cause").first()).toBeVisible();

  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    const result = await (
      window as typeof window & {
        axe: { run: (root: Document) => Promise<{ violations: unknown[] }> };
      }
    ).axe.run(document);
    return result.violations;
  });
  expect(violations).toEqual([]);
});

test("replay survives reload and keyboard stepping", async ({ page }) => {
  const run = await replayRun();
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await page.getByRole("button", { name: "Analysis" }).click();
  await page.getByRole("button", { name: "Next event" }).press("Enter");
  const saved = await page.getByRole("slider", { name: "Replay time" }).inputValue();
  await page.reload();
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("slider", { name: "Replay time" })).toHaveValue(saved);
});
