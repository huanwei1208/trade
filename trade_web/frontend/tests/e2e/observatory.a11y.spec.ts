import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockObservatoryApi } from "./mock-observatory";

// Accessibility checks (docs/26 §26.7): the observatory pages must have no
// critical axe violations, and status must be conveyed by more than color.

test.beforeEach(async ({ page }) => {
  await mockObservatoryApi(page);
});

async function analyze(page: import("@playwright/test").Page) {
  return new AxeBuilder({ page })
    .include('[data-testid="observatory-page"]')
    // Color-contrast tuning on a dark theme is out of scope for this pass; we
    // still assert on serious/critical structural violations below.
    .disableRules(["color-contrast"])
    .analyze();
}

function criticalOrSerious(results: Awaited<ReturnType<typeof analyze>>) {
  return results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
}

test("Overview lens has no critical/serious a11y violations", async ({ page }) => {
  await page.goto("/?obsLens=overview");
  await expect(page.getByTestId("observatory-page")).toBeVisible();
  await expect(page.getByTestId("composite-svg")).toBeVisible();
  const results = await analyze(page);
  expect(criticalOrSerious(results)).toEqual([]);
});

test("Trust lens has no critical/serious a11y violations", async ({ page }) => {
  await page.goto("/?obsLens=trust");
  await expect(page.getByTestId("trust-lens")).toBeVisible();
  const results = await analyze(page);
  expect(criticalOrSerious(results)).toEqual([]);
});

test("Research lens has no critical/serious a11y violations", async ({ page }) => {
  await page.goto("/?obsLens=research");
  await expect(page.getByTestId("research-lens")).toBeVisible();
  const results = await analyze(page);
  expect(criticalOrSerious(results)).toEqual([]);
});

test("status is conveyed by more than color (icons + text present)", async ({ page }) => {
  await page.goto("/?obsLens=overview");
  await expect(page.getByTestId("observatory-page")).toBeVisible();
  await page.getByTestId("hit-2026-07-15").click();
  // Non-color markers carry a text label, not just a colored dot.
  await expect(page.getByTestId("date-evidence-markers")).toContainText("Quarantined");
  // Chart markers carry a glyph.
  const marker = page.getByTestId("chart-marker").first();
  await expect(marker).toHaveCount(1);
  const markerText = (await marker.textContent()) || "";
  expect(markerText.length).toBeGreaterThan(0);
});
