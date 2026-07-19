import { expect, test } from "@playwright/test";

import { mockObservatoryApi } from "./mock-observatory";

// E2E flow (docs/26 §26.7): Overview -> Date Evidence -> Run Diff -> Research ->
// URL restore. The API is mocked deterministically. Also asserts there is NO
// future-outcome label leakage in Observe/Investigate DOM.

test.beforeEach(async ({ page }) => {
  await mockObservatoryApi(page);
});

async function gotoObservatory(page: import("@playwright/test").Page, query = "?obsLens=overview") {
  await page.goto(`/${query}`);
  await expect(page.getByTestId("observatory-page")).toBeVisible();
}

test("Overview shows the Truth Bar with all three watermarks and the composite chart", async ({ page }) => {
  await gotoObservatory(page);
  await expect(page.getByTestId("obs-truthbar")).toBeVisible();
  await expect(page.getByTestId("wm-observed")).toHaveText("2026-07-18");
  await expect(page.getByTestId("wm-candidate")).toHaveText("2026-07-18");
  await expect(page.getByTestId("wm-formal")).toHaveText("2026-07-11");
  await expect(page.getByTestId("composite-svg")).toBeVisible();
  await expect(page.getByTestId("formal-watermark-divider")).toBeVisible();
  // Three independent layers exist.
  await expect(page.getByTestId("layer-formal")).toBeVisible();
  await expect(page.getByTestId("layer-evaluated_candidate")).toBeVisible();
  await expect(page.getByTestId("layer-latest_observed")).toBeVisible();
});

test("Observe/Investigate does NOT leak future-outcome labels", async ({ page }) => {
  await gotoObservatory(page);
  // Select a date to open Date Evidence.
  await page.getByTestId("hit-2026-07-15").click();
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  await expect(page.getByTestId("research-visibility")).toContainText("not_visible");
  // The future-outcome region must NOT be present anywhere in Observe.
  await expect(page.getByTestId("future-outcome-region")).toHaveCount(0);
  const bodyText = (await page.locator("body").innerText()).toUpperCase();
  expect(bodyText).not.toContain("FUTURE OUTCOME");
});

test("Date evidence drilldown shows provider, basis and non-color markers", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("hit-2026-07-15").click();
  const panel = page.getByTestId("date-evidence");
  await expect(panel).toContainText("okx");
  await expect(panel).toContainText("basis_bps");
  await expect(page.getByTestId("date-evidence-markers")).toContainText("Quarantined");
});

test("Runs & Lineage: run diff reports added/removed/changed and code change", async ({ page }) => {
  await gotoObservatory(page, "?obsLens=runs");
  await expect(page.getByTestId("runs-table")).toBeVisible();
  // Base = run_observed, compare = run_formal.
  const rows = page.locator('[data-testid="runs-table"] tbody tr');
  await rows.nth(0).getByRole("button", { name: "Base" }).click();
  await rows.nth(1).getByRole("button", { name: "Compare" }).click();
  await expect(page.getByTestId("run-detail")).toBeVisible();
  await expect(page.getByTestId("cert-split")).toBeVisible();
  await expect(page.getByTestId("run-diff")).toBeVisible();
  await expect(page.getByTestId("run-diff")).toContainText("Added dates");
  await expect(page.getByTestId("run-diff")).toContainText("Removed dates");
  await expect(page.getByTestId("run-diff")).toContainText("code changed");
});

test("Research lens shows H1 evidence, the distinct future region, and Open in Lab", async ({ page }) => {
  await gotoObservatory(page, "?obsLens=research");
  await expect(page.getByTestId("research-hypothesis")).toContainText("H1");
  await expect(page.getByTestId("research-metrics")).toContainText("1.42");
  // Future-outcome region IS present here (and only here).
  await expect(page.getByTestId("future-outcome-region")).toBeVisible();
  // Open in Lab is display-only and reveals a copyable command fixing snapshot_id.
  await page.getByTestId("open-in-lab-button").click();
  await expect(page.getByTestId("open-in-lab-command")).toContainText("--snapshot-id snapshot_formal_0007");
});

test("Fixed URL restores lens + selected date on reload", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("hit-2026-07-16").click();
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  // The URL should now carry obsDate.
  await expect(page).toHaveURL(/obsDate=2026-07-16/);
  // Reload and confirm the same evidence context is restored.
  await page.reload();
  await expect(page.getByTestId("observatory-page")).toBeVisible();
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  await expect(page).toHaveURL(/obsDate=2026-07-16/);
});

test("Switching lenses updates the URL and restores after reload", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("lens-tab-trust").click();
  await expect(page.getByTestId("trust-lens")).toBeVisible();
  await expect(page).toHaveURL(/obsLens=trust/);
  await page.reload();
  await expect(page.getByTestId("trust-lens")).toBeVisible();
});
