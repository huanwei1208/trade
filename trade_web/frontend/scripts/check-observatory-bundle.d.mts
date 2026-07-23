export const OBSERVATORY_MAIN_BASELINE_GZIP_BYTES: number;
export const OBSERVATORY_MAIN_DELTA_BUDGET_BYTES: number;
export const OBSERVATORY_CHART_GZIP_BUDGET_BYTES: number;

export type ObservatoryBundleBudgetOptions = {
  distDir?: string;
  mainMaxBytes?: number;
  chartMaxBytes?: number;
};

export type ObservatoryBundleBudgetResult = {
  mainGzipBytes: number;
  chartGzipBytes: number;
};

export function checkObservatoryBundleBudgets(
  options?: ObservatoryBundleBudgetOptions,
): ObservatoryBundleBudgetResult;
