import { randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { checkObservatoryBundleBudgets } from "../../scripts/check-observatory-bundle.mjs";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture({ lazy = true, linked = true, nested = false, chartBytes = 128 } = {}) {
  const root = mkdtempSync(join(tmpdir(), "observatory-bundle-budget-"));
  roots.push(root);
  const distDir = join(root, "dist");
  mkdirSync(join(distDir, ".vite"), { recursive: true });
  mkdirSync(join(distDir, "assets"), { recursive: true });
  const chartKey = "src/components/observatory/ExchangeKlineChart.tsx";
  const observatoryKey = "src/pages/observatory/ObservatoryPage.tsx";
  writeFileSync(join(distDir, "assets", "index-HASH.js"), "export const main = true;");
  writeFileSync(join(distDir, "assets", "observatory-HASH.js"), "export const page = true;");
  writeFileSync(join(distDir, "assets", "chart-HASH.js"), randomBytes(chartBytes));
  writeFileSync(
    join(distDir, ".vite", "manifest.json"),
    JSON.stringify({
      "index.html": {
        file: "assets/index-HASH.js",
        isEntry: true,
        dynamicImports: linked ? [nested ? observatoryKey : chartKey] : [],
      },
      [observatoryKey]: {
        file: "assets/observatory-HASH.js",
        src: observatoryKey,
        isDynamicEntry: true,
        dynamicImports: [chartKey],
      },
      [chartKey]: {
        file: "assets/chart-HASH.js",
        src: chartKey,
        isDynamicEntry: lazy,
      },
    }),
  );
  return distDir;
}

describe("Observatory bundle budget", () => {
  it("uses manifest source identity rather than hashed asset names", () => {
    const result = checkObservatoryBundleBudgets({
      distDir: fixture(),
      mainMaxBytes: 1_024,
      chartMaxBytes: 1_024,
    });
    expect(result.mainGzipBytes).toBeGreaterThan(0);
    expect(result.chartGzipBytes).toBeGreaterThan(0);
  });

  it("accepts a chart chunk reached through the lazy Observatory page", () => {
    const result = checkObservatoryBundleBudgets({
      distDir: fixture({ nested: true }),
      mainMaxBytes: 1_024,
      chartMaxBytes: 1_024,
    });
    expect(result.mainGzipBytes).toBeGreaterThan(0);
    expect(result.chartGzipBytes).toBeGreaterThan(0);
  });

  it("rejects an eager or unlinked chart chunk", () => {
    expect(() =>
      checkObservatoryBundleBudgets({
        distDir: fixture({ lazy: false }),
        mainMaxBytes: 1_024,
        chartMaxBytes: 1_024,
      }),
    ).toThrow("BUNDLE_CHART_NOT_LAZY");
    expect(() =>
      checkObservatoryBundleBudgets({
        distDir: fixture({ linked: false }),
        mainMaxBytes: 1_024,
        chartMaxBytes: 1_024,
      }),
    ).toThrow("BUNDLE_CHART_NOT_LINKED_AS_DYNAMIC_IMPORT");
  });

  it("rejects a chart chunk over its gzip ceiling", () => {
    expect(() =>
      checkObservatoryBundleBudgets({
        distDir: fixture({ chartBytes: 4_096 }),
        mainMaxBytes: 1_024,
        chartMaxBytes: 128,
      }),
    ).toThrow("BUNDLE_CHART_GZIP_EXCEEDED");
  });
});
