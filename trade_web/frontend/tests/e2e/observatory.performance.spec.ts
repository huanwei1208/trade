import { expect, test } from "@playwright/test";

import { mockObservatoryApi } from "./mock-observatory";

test.describe.configure({ mode: "serial" });

for (const fixture of [
  { rows: 730, adapterBudgetMs: 100, readyBudgetMs: 1_500 },
  { rows: 7_300, adapterBudgetMs: 500, readyBudgetMs: 3_000 },
]) {
  test(`${fixture.rows.toLocaleString()} daily bars stay within structural and readiness budgets`, async ({
    page,
  }) => {
    await mockObservatoryApi(page, { selectedRowCount: fixture.rows });
    const evidenceRequests: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path.includes("/dates/")) evidenceRequests.push(path);
    });

    const startedAt = Date.now();
    await page.goto("/?obsLens=overview&obsRange=All");
    const chartFrame = page.getByTestId("exchange-kline-chart");
    await expect(chartFrame).toHaveAttribute("data-renderer-state", "ready", {
      timeout: fixture.readyBudgetMs,
    });
    await expect(chartFrame.locator("canvas").first()).toBeVisible();
    await expect(chartFrame.getByText("Daily chart interaction degraded.")).toHaveCount(0);
    const readyDurationMs = Date.now() - startedAt;
    const adapterDurationMs = Number(
      await page.getByTestId("exchange-kline-panel").getAttribute("data-adapter-duration-ms"),
    );

    expect(adapterDurationMs).toBeLessThan(fixture.adapterBudgetMs);
    expect(readyDurationMs).toBeLessThan(fixture.readyBudgetMs);
    console.info(
      `observatory-kline-performance rows=${fixture.rows} adapter_ms=${adapterDurationMs.toFixed(3)} ready_ms=${readyDurationMs}`,
    );
    await expect(chartFrame).toHaveCount(1);
    await expect(page.locator('[data-testid^="candle-"]')).toHaveCount(0);

    const chart = page.getByRole("group", { name: /Interactive BTC daily candlestick chart/ });
    const box = await chart.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      for (let index = 0; index < 100; index += 1) {
        await page.mouse.move(
          box.x + ((index % 50) / 50) * box.width,
          box.y + ((index % 20) / 20) * box.height,
        );
      }
    }
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
    expect(evidenceRequests).toEqual([]);
    await expect(chartFrame).toHaveAttribute("data-renderer-state", "ready");
  });
}
