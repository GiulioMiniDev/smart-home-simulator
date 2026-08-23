import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";
import axe from "axe-core";

type ReplayRun = { runId: string };

async function replayRun(): Promise<ReplayRun> {
  return JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as ReplayRun;
}

function selectedEvent(page: import("@playwright/test").Page) {
  return page.locator(".replay-track-events button.is-selected, button.replay-cluster-mark.is-selected");
}

async function selectEvent(page: import("@playwright/test").Page): Promise<void> {
  await page.locator("button.replay-cluster-mark").first().click();
  const clustered = page.locator(".replay-cluster-items button").first();
  if (await clustered.isVisible()) {
    await clustered.evaluate((element: HTMLButtonElement) => element.click());
  }
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
  await selectEvent(page);
  await expect(selectedEvent(page)).toHaveCount(1);
  const selectedSemanticLabel = await selectedEvent(page).getAttribute("aria-label");
  const selectedTime = await time.inputValue();

  await page.getByRole("button", { name: "Presentation" }).click();
  await expect(time).toHaveValue(selectedTime);
  await page.getByRole("button", { name: "Analysis" }).click();
  await expect(time).toHaveValue(selectedTime);
  await expect(selectedEvent(page)).toHaveAttribute("aria-label", selectedSemanticLabel ?? "");

  await page.getByRole("button", { name: "Oracle" }).click();
  await expect(page.getByText("Simulated cause").first()).toBeVisible();
  await expect(time).toHaveValue(selectedTime);
  const oracleSelection = await selectedEvent(page).getAttribute("aria-label");
  // Projection can disclose a richer label, but it must retain the selected instant.
  expect(oracleSelection?.slice(0, 5)).toBe(selectedSemanticLabel?.slice(0, 5));
  await page.getByRole("button", { name: "Observable" }).click();
  await expect(time).toHaveValue(selectedTime);
  await expect(selectedEvent(page)).toHaveAttribute("aria-label", selectedSemanticLabel ?? "");

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
  const time = page.getByRole("slider", { name: "Replay time" });
  const stepStartingPoint = String(Date.parse("2026-10-30T06:14:00.000Z"));
  await time.fill(stepStartingPoint);
  await expect(time).toHaveValue(stepStartingPoint);
  await expect(page.locator("button.replay-cluster-mark").first()).toBeVisible();
  await selectEvent(page);
  await expect(selectedEvent(page)).toHaveCount(1);
  const beforeStep = await time.inputValue();
  const beforeSemanticEvent = await selectedEvent(page).getAttribute("aria-label");
  const next = page.getByRole("button", { name: "Next event" });
  await expect(next).toBeEnabled();
  await next.press("Enter");
  await expect(time).not.toHaveValue(beforeStep);
  await expect(selectedEvent(page)).not.toHaveAttribute("aria-label", beforeSemanticEvent ?? "");
  const saved = await time.inputValue();
  await page.waitForTimeout(750);
  await page.reload();
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("slider", { name: "Replay time" })).toHaveValue(saved);
});
