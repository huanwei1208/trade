import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

export const OBSERVATORY_MAIN_BASELINE_GZIP_BYTES = 156_150;
export const OBSERVATORY_MAIN_DELTA_BUDGET_BYTES = 8 * 1_024;
export const OBSERVATORY_CHART_GZIP_BUDGET_BYTES = 60 * 1_024;

const CHART_SOURCE = "src/components/observatory/ExchangeKlineChart.tsx";

function chunkKeyMatches(key, chunk, source) {
  return key === source || chunk?.src === source;
}

function readManifest(distDir) {
  const manifestPath = resolve(distDir, ".vite", "manifest.json");
  const parsed = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("BUNDLE_MANIFEST_INVALID");
  }
  return parsed;
}

function gzipBytes(distDir, file) {
  return gzipSync(readFileSync(resolve(distDir, file))).byteLength;
}

function isDynamicImportReachable(manifest, startKey, targetSource) {
  const pending = [startKey];
  const seen = new Set();
  while (pending.length > 0) {
    const key = pending.pop();
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    const chunk = manifest[key];
    if (chunkKeyMatches(key, chunk, targetSource)) {
      return true;
    }
    const dynamicImports = Array.isArray(chunk?.dynamicImports) ? chunk.dynamicImports : [];
    pending.push(...dynamicImports);
  }
  return false;
}

export function checkObservatoryBundleBudgets({
  distDir = resolve(process.cwd(), "dist"),
  mainMaxBytes = OBSERVATORY_MAIN_BASELINE_GZIP_BYTES + OBSERVATORY_MAIN_DELTA_BUDGET_BYTES,
  chartMaxBytes = OBSERVATORY_CHART_GZIP_BUDGET_BYTES,
} = {}) {
  const manifest = readManifest(distDir);
  const entries = Object.entries(manifest);
  const entryPair = entries.find(([, chunk]) => chunk?.isEntry === true);
  const chartPair = entries.find(([key, chunk]) => chunkKeyMatches(key, chunk, CHART_SOURCE));
  if (!entryPair) throw new Error("BUNDLE_MAIN_ENTRY_MISSING");
  if (!chartPair) throw new Error("BUNDLE_CHART_ENTRY_MISSING");

  const [, entry] = entryPair;
  const [, chart] = chartPair;
  if (chart.isDynamicEntry !== true) throw new Error("BUNDLE_CHART_NOT_LAZY");
  const [entryKey] = entryPair;
  if (!isDynamicImportReachable(manifest, entryKey, CHART_SOURCE)) {
    throw new Error("BUNDLE_CHART_NOT_LINKED_AS_DYNAMIC_IMPORT");
  }
  if (typeof entry.file !== "string" || typeof chart.file !== "string") {
    throw new Error("BUNDLE_ASSET_PATH_MISSING");
  }

  const mainGzipBytes = gzipBytes(distDir, entry.file);
  const chartGzipBytes = gzipBytes(distDir, chart.file);
  if (mainGzipBytes > mainMaxBytes) {
    throw new Error(`BUNDLE_MAIN_GZIP_EXCEEDED:${mainGzipBytes}:${mainMaxBytes}`);
  }
  if (chartGzipBytes > chartMaxBytes) {
    throw new Error(`BUNDLE_CHART_GZIP_EXCEEDED:${chartGzipBytes}:${chartMaxBytes}`);
  }
  return { mainGzipBytes, chartGzipBytes };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = checkObservatoryBundleBudgets();
  process.stdout.write(
    `observatory bundle budgets: PASS main_gzip=${result.mainGzipBytes} chart_gzip=${result.chartGzipBytes}\n`,
  );
}
