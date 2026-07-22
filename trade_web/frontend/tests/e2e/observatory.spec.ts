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

test("Market defaults to the exchange-style selected-channel daily chart", async ({ page }) => {
  await gotoObservatory(page);
  await expect(page.getByTestId("obs-truthbar")).toBeVisible();
  await expect(page.getByTestId("wm-observed")).toHaveText("2026-07-18");
  await expect(page.getByTestId("wm-candidate")).toHaveText("2026-07-18");
  await expect(page.getByTestId("wm-formal")).toHaveText("2026-07-11");
  await expect(page.getByTestId("exchange-kline-chart")).toHaveAttribute(
    "data-renderer-state",
    "ready",
  );
  await expect(page.getByTestId("exchange-kline-lifecycle")).toHaveText(
    "Latest observed · UNPUBLISHED",
  );
  const gapCanvas = page.getByTestId("exchange-kline-gap-markers");
  await expect(gapCanvas).toHaveAttribute("data-marker-count", "1");
  await expect
    .poll(() =>
      gapCanvas.evaluate((canvas: HTMLCanvasElement) => {
        const context = canvas.getContext("2d");
        if (!context || canvas.width === 0 || canvas.height === 0) return false;
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let index = 3; index < pixels.length; index += 4) {
          if (pixels[index] > 0) return true;
        }
        return false;
      }),
    )
    .toBe(true);
  await expect(page.getByText("BTC/USDT")).toBeVisible();
  await expect(page.getByText("Local daily Observatory snapshot · not live")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Market chart view" }).getByRole("button", { name: "Market" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("composite-svg")).toHaveCount(0);
  await expect(page).not.toHaveURL(/obsChart=/);
});

test("Market timeframe switches stay local and ordinary chart clicks do not pin or navigate", async ({
  page,
}) => {
  await gotoObservatory(page);
  await page.getByTestId("exchange-kline-timeframe-1W").click();
  await expect(page.getByTestId("exchange-kline-timeframe-1W")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page).toHaveURL(/obsTimeframe=1W/);
  await page.getByTestId("exchange-kline-canvas-shell").click({ position: { x: 120, y: 90 } });
  await expect(page).not.toHaveURL(/obsDate=/);
  await expect(page.getByTestId("date-evidence")).toHaveCount(0);
  await page.getByTestId("exchange-kline-inspect-date").click();
  await expect(page).toHaveURL(/obsDate=/);
});

test("Compare preserves the separate three-layer lifecycle chart and restores from URL", async ({
  page,
}) => {
  await gotoObservatory(page, "?obsLens=overview&obsChart=compare");
  await expect(page.getByTestId("composite-svg")).toBeVisible();
  await expect(page.getByTestId("formal-watermark-divider")).toBeVisible();
  await expect(page.getByTestId("layer-formal")).toBeVisible();
  await expect(page.getByTestId("layer-evaluated_candidate")).toBeVisible();
  await expect(page.getByTestId("layer-latest_observed")).toBeVisible();
  await expect(page.getByTestId("exchange-kline-chart")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("composite-svg")).toBeVisible();
  await expect(page).toHaveURL(/obsChart=compare/);
});

test("Market and Compare issue only their mode-owned series request", async ({ page }) => {
  const seriesViews: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/series")) {
      seriesViews.push(url.searchParams.get("view") ?? "");
    }
  });

  await gotoObservatory(page);
  await expect(page.getByTestId("exchange-kline-chart")).toBeVisible();
  expect(seriesViews).toEqual(["observed"]);

  seriesViews.length = 0;
  await page.getByRole("button", { name: "Compare" }).click();
  await expect(page.getByTestId("composite-svg")).toBeVisible();
  expect(seriesViews).toEqual(["composite"]);
  await expect(page).toHaveURL(/obsChart=compare/);
});

test("Observe/Investigate does NOT leak future-outcome labels", async ({ page }) => {
  await gotoObservatory(page);
  // Keyboard-equivalent date selector opens the same snapshot-pinned evidence.
  await page.getByTestId("chart-date-inspector").fill("2026-07-15");
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  await expect(page.getByTestId("research-visibility")).toContainText("not_visible");
  // The future-outcome region must NOT be present anywhere in Observe.
  await expect(page.getByTestId("future-outcome-region")).toHaveCount(0);
  const bodyText = (await page.locator("body").innerText()).toUpperCase();
  expect(bodyText).not.toContain("FUTURE OUTCOME");
});

test("Date evidence drilldown shows provider, basis and non-color markers", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("chart-date-inspector").fill("2026-07-15");
  const panel = page.getByTestId("date-evidence");
  await expect(panel).toContainText("okx");
  await expect(panel).toContainText("basis_bps");
  await expect(page.getByTestId("date-evidence-markers")).toContainText("Quarantined");
});

test("Keyboard date inspection moves focus to evidence and Close returns it to the inspector", async ({
  page,
}) => {
  await gotoObservatory(page);
  const inspector = page.getByTestId("chart-date-inspector");
  await inspector.fill("2026-07-15");
  await expect(page.locator(".obs-date-evidence__focus")).toBeFocused();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(inspector).toBeFocused();
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

test("Research lens shows H1 evidence, the distinct future region, and Open in Lab", async ({
  page,
}) => {
  await gotoObservatory(page, "?obsLens=research");
  await expect(page.getByTestId("research-hypothesis")).toContainText("H1");
  await expect(page.getByTestId("research-metrics")).toContainText("1.42");
  // Future-outcome region IS present here (and only here).
  await expect(page.getByTestId("future-outcome-region")).toBeVisible();
  // Open in Lab is display-only and reveals a copyable command fixing snapshot_id.
  await page.getByTestId("open-in-lab-button").click();
  await expect(page.getByTestId("open-in-lab-command")).toContainText(
    "--snapshot-id snapshot_formal_0007",
  );
});

test("Fixed URL restores lens + selected date on reload", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("chart-date-inspector").fill("2026-07-16");
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  // The URL should now carry obsDate.
  await expect(page).toHaveURL(/obsDate=2026-07-16/);
  // Reload and confirm the same evidence context is restored.
  await page.reload();
  await expect(page.getByTestId("observatory-page")).toBeVisible();
  await expect(page.getByTestId("date-evidence")).toBeVisible();
  await expect(page).toHaveURL(/obsDate=2026-07-16/);
});

test("Compare date pinning uses the Context snapshot without loading Market series", async ({
  page,
}) => {
  const selectedViews: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/series")) selectedViews.push(url.searchParams.get("view") ?? "");
  });
  await gotoObservatory(page, "?obsLens=overview&obsChart=compare");
  await page.getByTestId("chart-date-inspector").fill("2026-07-15");
  await expect(page.getByTestId("date-evidence")).toContainText("run_observed");
  expect(selectedViews).toEqual(["composite"]);
});

test("Switching lenses updates the URL and restores after reload", async ({ page }) => {
  await gotoObservatory(page);
  await page.getByTestId("lens-tab-trust").click();
  await expect(page.getByTestId("trust-lens")).toBeVisible();
  await expect(page).toHaveURL(/obsLens=trust/);
  await page.reload();
  await expect(page.getByTestId("trust-lens")).toBeVisible();
});

test("Unready backend: a direct ?obsLens URL does NOT open Observatory (fail closed)", async ({
  page,
}) => {
  // Override only the capability route to report an unready state; the rest of the
  // observatory fixtures stay mocked. A direct-open URL must fail closed: the
  // Observatory page must not mount and the nav entry must stay hidden.
  await page.route("**/api/v1/observatory/capability", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: true, state: "catalog_missing", show_nav: false }),
    }),
  );
  await page.goto("/?obsLens=overview");
  // The shell renders and lands on Today (default) rather than Observatory.
  await expect(page.getByTestId("nav-today")).toBeVisible();
  await expect(page.getByTestId("observatory-page")).toHaveCount(0);
  await expect(page.getByTestId("nav-observatory")).toHaveCount(0);
  await expect(page.getByTestId("observatory-unavailable-notice")).toBeVisible();
  await expect(page.getByLabel("Attempted Observatory link")).toHaveValue(/obsLens=overview/);
});
