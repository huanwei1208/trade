import type { Page, Route } from "@playwright/test";

// Route interception that serves the frozen observatory fixtures. Preferred over
// a live backend for deterministic E2E (per the task brief). The JSON shapes
// mirror the frozen WP3 contracts exactly. Import-free duplication of the unit
// fixtures keeps the Playwright bundle independent of the Vite/TS app graph.

const CONTRACT = {
  asset_id: "crypto.BTC",
  display_symbol: "BTC",
  contract_version: "v1",
  primary_provider: "okx",
  primary_instrument: "BTC-USDT",
  shadow_provider: "binance",
  shadow_instrument: "BTCUSDT",
  quote: "USDT",
  primary_interval: "1Dutc",
  shadow_interval: "1d",
};

function row(date: string, close: string | null, over: Record<string, unknown> = {}) {
  return {
    date,
    open: close,
    high: close,
    low: close,
    close,
    volume: "1000",
    provider: "okx",
    instrument: "BTC-USDT",
    quote: "USDT",
    available_at: `${date}T00:05:00Z`,
    fetched_at: `${date}T00:06:00Z`,
    source_run_id: "run_observed",
    membership: ["latest_observed"],
    availability_state: "present",
    quality_flags: [],
    revision_state: "unchanged",
    render_role: "observed_only",
    metrics: {},
    ...over,
  };
}

function generatedDailyRows(count: number) {
  const end = Date.parse("2026-07-18T00:00:00.000Z");
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(end - (count - index - 1) * 86_400_000).toISOString().slice(0, 10);
    const open = 30_000 + index * 2;
    const close = open + (index % 2 === 0 ? 35 : -20);
    return row(date, String(close), {
      open: String(open),
      high: String(Math.max(open, close) + 90),
      low: String(Math.min(open, close) - 80),
      volume: String(10_000 + index),
      quality_flags: [],
      revision_state: "unchanged",
    });
  });
}

const CONTEXT = {
  snapshot_id: "snapshot_observed_0001",
  resolved_channel: "observed",
  run_id: "run_observed",
  release_id: null,
  contract: CONTRACT,
  market_watermark: "2026-07-18",
  input_watermarks: { primary: "2026-07-18" },
  output_watermark: "2026-07-18",
  requested_knowledge_as_of: "latest",
  effective_knowledge_cut: "2026-07-18T00:00:00Z",
  relevant_fact_sequence: 42,
  knowledge_mode: "installation_observed",
  revision_policy: "as_known",
  pit_coverage_status: "proven",
  created_at: "2026-07-18T01:00:00Z",
  certified_at: null,
  published_at: null,
  rendered_at: "2026-07-19T09:00:00Z",
  lifecycle_state: "staged",
  quality_state: "degraded",
  freshness_state: "fresh",
  compatibility_state: "compatible",
  acquisition_state: "succeeded",
  purpose_fitness: [
    {
      purpose: "manual_observation",
      allowed: true,
      status: "allowed",
      reason_codes: [],
      evidence_refs: [],
    },
    {
      purpose: "formal_system_consumption",
      allowed: false,
      status: "blocked",
      reason_codes: ["CHANNEL_UNAVAILABLE"],
      evidence_refs: [],
    },
    {
      purpose: "strict_research",
      allowed: false,
      status: "blocked",
      reason_codes: ["RESEARCH_NOT_ELIGIBLE"],
      evidence_refs: [],
    },
  ],
  artifact_refs: [
    { name: "canonical", sha256: "abc123", relative_path: "runs/run_observed/canonical.parquet" },
  ],
  findings_summary: { acquisition_stability: "3 / 29 real success days" },
  excluded_dates: [
    {
      date: "2026-07-15",
      exclusion_reason: "quarantined",
      quality_flags: ["quarantined"],
      evidence_refs: [],
      marker_position: "below",
    },
  ],
  reason_codes: [],
  view_fingerprint: "vf_context_0001",
  etag: "etag_context_0001",
  evidence_coverage: {},
  semantic_channels: {
    formal: { run_id: "run_formal", watermark: "2026-07-11", release_id: "release_0007" },
    evaluated_candidate: { run_id: "run_candidate", watermark: "2026-07-18", release_id: null },
    observed: { run_id: "run_observed", watermark: "2026-07-18", release_id: null },
  },
};

const FORMAL_ROWS = [
  row("2026-07-09", "58000", {
    membership: ["formal"],
    render_role: "formal_baseline",
    source_run_id: "run_formal",
  }),
  row("2026-07-10", "59000", {
    membership: ["formal"],
    render_role: "formal_baseline",
    source_run_id: "run_formal",
  }),
  row("2026-07-11", "60000", {
    membership: ["formal"],
    render_role: "formal_baseline",
    source_run_id: "run_formal",
  }),
];

const CANDIDATE_ROWS = [
  row("2026-07-10", "59050", {
    membership: ["evaluated_candidate"],
    render_role: "candidate_overlap",
    revision_state: "changed",
    source_run_id: "run_candidate",
  }),
  row("2026-07-11", "60000", {
    membership: ["evaluated_candidate"],
    render_role: "candidate_overlap",
    source_run_id: "run_candidate",
  }),
  row("2026-07-12", "61000", {
    membership: ["evaluated_candidate"],
    render_role: "candidate_only",
    source_run_id: "run_candidate",
  }),
  row("2026-07-13", null, {
    membership: ["evaluated_candidate"],
    render_role: "candidate_only",
    availability_state: "missing",
    source_run_id: "run_candidate",
  }),
  row("2026-07-14", "62000", {
    membership: ["evaluated_candidate"],
    render_role: "candidate_only",
    source_run_id: "run_candidate",
  }),
];

const OBSERVED_ROWS = [
  row("2026-07-14", "62010", {
    open: "61680",
    high: "62340",
    low: "61420",
    render_role: "observed_overlap",
  }),
  row("2026-07-15", "62500", {
    open: "62010",
    high: "62820",
    low: "61870",
    render_role: "observed_only",
    quality_flags: ["quarantined"],
  }),
  row("2026-07-16", "63000", {
    open: "62500",
    high: "63310",
    low: "62240",
    render_role: "observed_only",
  }),
  row("2026-07-17", "63500", {
    open: "63000",
    high: "63880",
    low: "62760",
    render_role: "observed_only",
    revision_state: "changed",
  }),
  row("2026-07-18", "64000", {
    open: "63500",
    high: "64220",
    low: "63210",
    render_role: "observed_only",
  }),
];

const COMPOSITE = {
  view: "composite",
  asset_id: "crypto.BTC",
  etag: "etag_composite_0001",
  fingerprint_basis: "fb_0001",
  layers: {
    formal: {
      channel: "formal",
      context: { ...CONTEXT, resolved_channel: "formal", market_watermark: "2026-07-11" },
      rows: FORMAL_ROWS,
    },
    evaluated_candidate: { channel: "evaluated_candidate", context: CONTEXT, rows: CANDIDATE_ROWS },
    latest_observed: { channel: "latest_observed", context: CONTEXT, rows: OBSERVED_ROWS },
  },
  reason_codes: [],
  view_fingerprint: "vf_composite_0001",
};

const FORMAL_SERIES = {
  view: "formal",
  context: { ...CONTEXT, resolved_channel: "formal", market_watermark: "2026-07-11" },
  rows: FORMAL_ROWS.map((r, i) => ({
    ...r,
    metrics:
      i === FORMAL_ROWS.length - 1
        ? {
            return_1d: "1.69",
            return_7d: "3.44",
            return_30d: "12.10",
            drawdown: "-4.20",
            rv20_percentile: "72",
          }
        : {},
  })),
  pit_valid: true,
  reason_codes: [],
  view_fingerprint: "vf_formal_0001",
  etag: "etag_formal_0001",
};

const DATE_EVIDENCE = {
  date: "2026-07-15",
  snapshot_id: "snapshot_observed_0001",
  run_id: "run_observed",
  ohlcv: OBSERVED_ROWS[1],
  reconciliation: { basis_bps: "12.5", aligned: "true" },
  revision: { revision_state: "unchanged" },
  run_lineage: ["run_observed"],
  research_visibility: "not_visible",
  reason_codes: [],
};

const TRUST = {
  snapshot_id: "snapshot_observed_0001",
  run_id: "run_observed",
  gates: [
    {
      gate: "contract",
      status: "pass",
      reason_code: null,
      detail: "identity verified",
      metrics: {},
    },
    {
      gate: "acquisition",
      status: "warn",
      reason_code: "D1_INSUFFICIENT",
      detail: "3 / 29 real success days",
      metrics: {},
    },
    {
      gate: "publish",
      status: "block",
      reason_code: "CHANNEL_UNAVAILABLE",
      detail: "not published",
      metrics: {},
    },
  ],
  findings: [
    {
      finding_id: "f001",
      gate: "acquisition",
      severity: "warn",
      reason_code: "D1_INSUFFICIENT",
      affected_dates: ["2026-07-12"],
      evidence_refs: ["run_candidate"],
    },
  ],
  acquisition_state: "succeeded",
  quality_state: "degraded",
};

const RUNS = {
  runs: [
    {
      run_id: "run_observed",
      created_at: "2026-07-18T01:00:00Z",
      market_watermark: "2026-07-18",
      data_readiness: "degraded",
      quality_state: "degraded",
      lifecycle_state: "staged",
      canonical_rows: 725,
    },
    {
      run_id: "run_formal",
      created_at: "2026-07-11T01:00:00Z",
      market_watermark: "2026-07-11",
      data_readiness: "ready",
      quality_state: "assured",
      lifecycle_state: "published",
      canonical_rows: 730,
    },
  ],
  next_cursor: null,
  catalog_fingerprint: "catalog_fp_0001",
};

const RUN_DETAIL = {
  run_id: "run_observed",
  created_at: "2026-07-18T01:00:00Z",
  market_watermark: "2026-07-18",
  data_readiness: "degraded",
  quality_state: "degraded",
  lifecycle_state: "staged",
  acquisition_state: "succeeded",
  canonical_rows: 725,
  code_revision: "abc123",
  artifact_refs: [{ name: "canonical", sha256: "abc123def456" }],
  gates: TRUST.gates,
};

const RUN_DIFF = {
  base: {
    run_id: "run_formal",
    watermark: "2026-07-11",
    canonical_rows: 730,
    canonical_hash: "hf",
    code_revision: "aaa",
    config_hash: "c1",
    schema_hash: "s1",
  },
  compare: {
    run_id: "run_observed",
    watermark: "2026-07-18",
    canonical_rows: 725,
    canonical_hash: "ho",
    code_revision: "bbb",
    config_hash: "c1",
    schema_hash: "s1",
  },
  added_dates: ["2026-07-12", "2026-07-16", "2026-07-17", "2026-07-18"],
  removed_dates: ["2026-07-05"],
  changed_dates: [{ date: "2026-07-10", base_close: "59000", compare_close: "59050" }],
  gate_changes: { publish: { base: ["pass", null], compare: ["block", "CHANNEL_UNAVAILABLE"] } },
  code_changed: true,
  config_changed: false,
  schema_changed: false,
};

const HYPOTHESES = {
  hypotheses: [
    {
      hypothesis_id: "H1",
      hypothesis_version: "btc-vol-persistence-v1",
      statement:
        "After BTC 20-day realized volatility enters a high-volatility regime, is the next seven full-UTC-day realized volatility significantly and stably higher than normal days?",
      directional: false,
      research_state: "candidate",
      current_research_run_id: "H1:gen_0007",
    },
  ],
};

const RESEARCH_RUN = {
  research_run_id: "H1:gen_0007",
  hypothesis_id: "H1",
  hypothesis_version: "btc-vol-persistence-v1",
  validation_run_id: "val_0007",
  generation_id: "gen_0007",
  dataset_snapshot_id: "snapshot_formal_0007",
  knowledge_as_of: "2026-07-11T00:00:00Z",
  research_state: "candidate",
  is_current: true,
  metrics: {
    effect_ratio: "1.42",
    ci_low: "1.05",
    ci_high: "1.93",
    q_value: "0.031",
    sample_size: "58",
    data_readiness: "degraded",
  },
  evidence_refs: ["receipts/h1_gen_0007.json"],
};

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function invalid(route: Route, message: string) {
  return route.fulfill({
    status: 422,
    contentType: "application/json",
    body: JSON.stringify({
      message,
      reason_codes: ["INVALID_SNAPSHOT_SELECTOR"],
      evidence_refs: [],
      retryable: false,
    }),
  });
}

function requireSnapshot(url: URL, route: Route) {
  if (url.searchParams.get("snapshot_id") !== CONTEXT.snapshot_id) {
    return invalid(route, "Mock requires the selected Context snapshot_id.");
  }
  return null;
}

function requireBoundedWindow(url: URL, route: Route) {
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  if (from !== "2026-04-20" || to !== "2026-07-18") {
    return invalid(route, "Mock requires the Context-derived 90D server window.");
  }
  return null;
}

export async function mockObservatoryApi(
  page: Page,
  options: { selectedRowCount?: number } = {},
): Promise<void> {
  const selectedRows = options.selectedRowCount
    ? generatedDailyRows(options.selectedRowCount)
    : OBSERVED_ROWS;
  const selectedContext = options.selectedRowCount ? { ...CONTEXT, excluded_dates: [] } : CONTEXT;
  // Non-observatory endpoints the shell may call (trust overview) — stub empty.
  await page.route("**/api/trust/overview", (route) =>
    json(route, { as_of: "2026-07-19", trust_scalar: null, coverage: null, trend: [] }),
  );
  await page.route("**/api/today-page", (route) => json(route, {}));

  await page.route("**/api/v1/observatory/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    // RA.1 (F14): the frontend gates Observatory nav/page on a FRESH ready
    // capability response. The E2E suite exercises a prepared, enabled backend, so
    // this fixture returns `ready` to keep the existing Observatory flows valid.
    if (path.endsWith("/capability")) {
      return json(route, {
        enabled: true,
        state: "ready",
        show_nav: true,
        generation_id: "gen_0007",
      });
    }
    if (path.endsWith("/context")) {
      if (url.searchParams.get("channel") !== "observed") {
        return invalid(route, "Mock supports the observed channel only.");
      }
      return json(route, selectedContext);
    }
    if (path.endsWith("/series")) {
      const view = url.searchParams.get("view") || "composite";
      if (!options.selectedRowCount) {
        const windowError = requireBoundedWindow(url, route);
        if (windowError) {
          return windowError;
        }
      } else if (url.searchParams.has("from") || url.searchParams.has("to")) {
        return invalid(route, "Performance fixtures require an unbounded All request.");
      }
      if (view === "composite") {
        if (url.searchParams.has("snapshot_id")) {
          return invalid(route, "Composite comparison must not carry snapshot_id.");
        }
        return json(route, COMPOSITE);
      }
      const snapshotError = requireSnapshot(url, route);
      if (snapshotError) {
        return snapshotError;
      }
      if (view !== "observed") {
        return invalid(route, "Mock selected-channel series must match Context.");
      }
      return json(route, {
        ...FORMAL_SERIES,
        view: "observed",
        context: selectedContext,
        rows: selectedRows,
      });
    }
    if (path.includes("/dates/")) {
      const snapshotError = requireSnapshot(url, route);
      if (snapshotError) {
        return snapshotError;
      }
      const requestedDate = decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
      return json(route, {
        ...DATE_EVIDENCE,
        date: requestedDate,
        ohlcv: OBSERVED_ROWS.find((candidate) => candidate.date === requestedDate) ?? null,
      });
    }
    if (path.endsWith("/trust")) {
      const snapshotError = requireSnapshot(url, route);
      if (snapshotError) {
        return snapshotError;
      }
      return json(route, TRUST);
    }
    if (path.endsWith("/runs")) {
      if (url.searchParams.get("limit") !== "50") {
        return invalid(route, "Mock requires cursor-bounded run requests.");
      }
      return json(route, RUNS);
    }
    if (path.endsWith("/runs/diff")) {
      const base = url.searchParams.get("base");
      const compare = url.searchParams.get("compare");
      if (!base || !compare) {
        return invalid(route, "Mock requires explicit base and compare run ids.");
      }
      return json(route, {
        ...RUN_DIFF,
        base: { ...RUN_DIFF.base, run_id: base },
        compare: { ...RUN_DIFF.compare, run_id: compare },
      });
    }
    if (path.includes("/runs/")) {
      const runId = decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
      return json(route, { ...RUN_DETAIL, run_id: runId });
    }
    if (path.endsWith("/hypotheses")) {
      return json(route, HYPOTHESES);
    }
    if (path.includes("/research-runs/")) {
      const researchRunId = decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
      if (researchRunId !== "H1:gen_0007") {
        return invalid(route, "Mock requires explicit H1 research run selection.");
      }
      return json(route, RESEARCH_RUN);
    }
    return json(route, {});
  });
}
