import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/observatory/ExchangeKlinePanel", () => ({
  ExchangeKlinePanel: ({ onRequestCompare }: { onRequestCompare?: () => void }) => (
    <div data-testid="exchange-kline-panel-stub">
      Exchange-style daily chart
      {onRequestCompare ? (
        <button type="button" onClick={onRequestCompare}>
          Open Compare
        </button>
      ) : null}
    </div>
  ),
}));

import type { ObservatoryUrlState } from "../lib/observatory";
import { ObservatoryPage } from "../pages/observatory/ObservatoryPage";
import {
  COMPOSITE_FIXTURE,
  CONTEXT_FIXTURE,
  DATE_EVIDENCE_FIXTURE,
  HYPOTHESES_FIXTURE,
  RESEARCH_RUN_FIXTURE,
  RUN_DETAIL_FIXTURE,
  RUN_DIFF_FIXTURE,
  RUNS_FIXTURE,
  TRUST_FIXTURE,
} from "./fixtures";
import { clearObservatoryResourceMemoryCache } from "../pages/observatory/observatoryResource";

const DEFAULT_STATE: ObservatoryUrlState = {
  lens: "overview",
  channel: "observed",
  chartMode: "market",
  knowledgeAsOf: "latest",
  range: "90D",
  runId: null,
  compareRunId: null,
  date: null,
};

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
}

function selectedSeries(view: string) {
  return {
    view,
    context: { ...CONTEXT_FIXTURE, resolved_channel: view },
    rows: COMPOSITE_FIXTURE.layers?.latest_observed?.rows ?? [],
    pit_valid: true,
    reason_codes: [],
    view_fingerprint: `vf_${view}`,
  };
}

function installObservatoryFetch(overrides: Partial<Record<string, unknown>> = {}) {
  const paths: string[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = typeof input === "string" ? input : input.toString();
    paths.push(path);
    const url = new URL(path, "https://trade.invalid");

    if (url.pathname.endsWith("/context")) {
      return jsonResponse(overrides.context ?? CONTEXT_FIXTURE);
    }
    if (url.pathname.endsWith("/series")) {
      if (url.searchParams.get("view") === "composite") {
        return jsonResponse(overrides.composite ?? COMPOSITE_FIXTURE);
      }
      return jsonResponse(
        overrides.series ?? selectedSeries(url.searchParams.get("view") || "observed"),
      );
    }
    if (url.pathname.endsWith("/trust")) {
      return jsonResponse(overrides.trust ?? TRUST_FIXTURE);
    }
    if (url.pathname.endsWith("/runs")) {
      return jsonResponse(overrides.runs ?? RUNS_FIXTURE);
    }
    if (url.pathname.endsWith("/runs/diff")) {
      return jsonResponse(overrides.diff ?? RUN_DIFF_FIXTURE);
    }
    if (url.pathname.includes("/runs/")) {
      return jsonResponse(overrides.detail ?? RUN_DETAIL_FIXTURE);
    }
    if (url.pathname.endsWith("/hypotheses")) {
      return jsonResponse(overrides.hypotheses ?? HYPOTHESES_FIXTURE);
    }
    if (url.pathname.includes("/research-runs/")) {
      return jsonResponse(overrides.researchRun ?? RESEARCH_RUN_FIXTURE);
    }
    if (url.pathname.includes("/dates/")) {
      return jsonResponse(overrides.dateEvidence ?? DATE_EVIDENCE_FIXTURE);
    }
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, paths };
}

function renderPage(state: Partial<ObservatoryUrlState> = {}) {
  return render(
    <ObservatoryPage
      refreshToken={0}
      urlState={{ ...DEFAULT_STATE, ...state }}
      onUrlStateChange={() => {}}
    />,
  );
}

beforeEach(() => {
  clearObservatoryResourceMemoryCache();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ObservatoryPage request matrix", () => {
  it("loads Context first, then only the snapshot-pinned Market series", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({ range: "90D" });

    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(1));
    expect(paths.filter((path) => path.includes("/context"))).toHaveLength(1);
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
    expect(paths.some((path) => path.includes("/runs"))).toBe(false);
    expect(paths.some((path) => path.includes("/hypotheses"))).toBe(false);

    const selectedPath = paths.find(
      (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "observed",
    );
    expect(selectedPath).toBeTruthy();

    const selectedParams = new URL(selectedPath!, "https://trade.invalid").searchParams;
    expect(selectedParams.get("snapshot_id")).toBe(CONTEXT_FIXTURE.snapshot_id);
    expect(selectedParams.get("from")).toBe("2026-04-20");
    expect(selectedParams.get("to")).toBe("2026-07-18");
    expect(
      paths.some(
        (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "composite",
      ),
    ).toBe(false);
    expect(await screen.findByTestId("exchange-kline-panel-stub")).toBeTruthy();
    expect(screen.getByTestId("market-summary")).toBeTruthy();
    expect(screen.queryByTestId("what-changed")).toBeNull();
  });

  it("loads only the bounded composite series in Compare mode", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({ chartMode: "compare", range: "90D" });

    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(1));
    const compositePath = paths.find(
      (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "composite",
    );
    expect(compositePath).toBeTruthy();
    const params = new URL(compositePath!, "https://trade.invalid").searchParams;
    expect(params.get("snapshot_id")).toBeNull();
    expect(params.get("from")).toBe("2026-04-20");
    expect(params.get("to")).toBe("2026-07-18");
    expect(screen.getByTestId("composite-chart")).toBeTruthy();
    expect(screen.getByTestId("what-changed")).toBeTruthy();
    expect(screen.queryByTestId("market-summary")).toBeNull();
  });

  it("refetches the same composite URL when a channel switch resolves a new Context snapshot", async () => {
    const nextSnapshotId = "snapshot_formal_0002";
    const nextContext = {
      ...CONTEXT_FIXTURE,
      resolved_channel: "formal",
      snapshot_id: nextSnapshotId,
    };
    const nextComposite = {
      ...COMPOSITE_FIXTURE,
      layers: {
        ...COMPOSITE_FIXTURE.layers,
        formal: {
          ...COMPOSITE_FIXTURE.layers?.formal,
          context: {
            ...COMPOSITE_FIXTURE.layers?.formal?.context,
            resolved_channel: "formal",
            snapshot_id: nextSnapshotId,
          },
        },
      },
    };
    const paths: string[] = [];
    let compositeRequests = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = typeof input === "string" ? input : input.toString();
      paths.push(path);
      const url = new URL(path, "https://trade.invalid");
      if (url.pathname.endsWith("/context")) {
        return jsonResponse(
          url.searchParams.get("channel") === "formal" ? nextContext : CONTEXT_FIXTURE,
        );
      }
      if (url.pathname.endsWith("/series") && url.searchParams.get("view") === "composite") {
        compositeRequests += 1;
        return jsonResponse(compositeRequests === 1 ? COMPOSITE_FIXTURE : nextComposite);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, chartMode: "compare", range: "All" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(compositeRequests).toBe(1));
    expect(await screen.findByTestId("composite-chart")).toBeTruthy();

    page.rerender(
      <ObservatoryPage
        refreshToken={0}
        urlState={{
          ...DEFAULT_STATE,
          chartMode: "compare",
          channel: "formal",
          range: "All",
        }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() =>
      expect(paths.some((path) => path.endsWith("/context?channel=formal"))).toBe(true),
    );
    await waitFor(() => expect(compositeRequests).toBe(2));
    expect(screen.getByTestId("composite-chart")).toBeTruthy();
    expect(screen.queryByText("Composite comparison unavailable")).toBeNull();
  });

  it("waits for refreshed Context before revalidating a still-mounted composite URL", async () => {
    const nextSnapshotId = "snapshot_observed_0002";
    const nextContext = { ...CONTEXT_FIXTURE, snapshot_id: nextSnapshotId };
    const nextComposite = {
      ...COMPOSITE_FIXTURE,
      layers: {
        ...COMPOSITE_FIXTURE.layers,
        latest_observed: {
          ...COMPOSITE_FIXTURE.layers?.latest_observed,
          context: {
            ...COMPOSITE_FIXTURE.layers?.latest_observed?.context,
            snapshot_id: nextSnapshotId,
          },
        },
      },
    };
    let contextRequests = 0;
    let compositeRequests = 0;
    let resolveRefreshContext: ((response: Response) => void) | null = null;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = typeof input === "string" ? input : input.toString();
      const url = new URL(path, "https://trade.invalid");
      if (url.pathname.endsWith("/context")) {
        contextRequests += 1;
        if (contextRequests === 1) return Promise.resolve(jsonResponse(CONTEXT_FIXTURE));
        return new Promise<Response>((resolve) => {
          resolveRefreshContext = resolve;
        });
      }
      if (url.pathname.endsWith("/series") && url.searchParams.get("view") === "composite") {
        compositeRequests += 1;
        return Promise.resolve(
          jsonResponse(compositeRequests === 1 ? COMPOSITE_FIXTURE : nextComposite),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, chartMode: "compare", range: "All" }}
        onUrlStateChange={() => {}}
      />,
    );

    expect(await screen.findByTestId("composite-chart")).toBeTruthy();
    expect(contextRequests).toBe(1);
    expect(compositeRequests).toBe(1);

    page.rerender(
      <ObservatoryPage
        refreshToken={1}
        urlState={{ ...DEFAULT_STATE, chartMode: "compare", range: "All" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(contextRequests).toBe(2));
    expect(compositeRequests).toBe(1);
    expect(screen.queryByTestId("composite-chart")).toBeNull();

    await act(async () => {
      resolveRefreshContext?.(jsonResponse(nextContext));
      await Promise.resolve();
    });

    await waitFor(() => expect(compositeRequests).toBe(2));
    expect(await screen.findByTestId("composite-chart")).toBeTruthy();
    expect(screen.queryByText("Composite comparison unavailable")).toBeNull();
  });

  it("loads Compare date evidence directly from Context without a selected-series request", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({ chartMode: "compare", date: "2026-07-15" });

    await waitFor(() =>
      expect(paths.some((path) => path.includes("/dates/2026-07-15"))).toBe(true),
    );
    expect(
      paths.filter(
        (path) =>
          path.includes("/series") &&
          new URL(path, "https://trade.invalid").searchParams.get("view") !== "composite",
      ),
    ).toHaveLength(0);
    const datePath = paths.find((path) => path.includes("/dates/2026-07-15"));
    expect(datePath).toContain(`snapshot_id=${CONTEXT_FIXTURE.snapshot_id}`);
    expect(await screen.findByTestId("date-evidence")).toHaveTextContent("run_observed");
  });

  it("keeps the Market/Compare switch outside the lazy renderer boundary", async () => {
    const onUrlStateChange = vi.fn();
    installObservatoryFetch();
    render(
      <ObservatoryPage
        refreshToken={0}
        urlState={DEFAULT_STATE}
        onUrlStateChange={onUrlStateChange}
      />,
    );

    await screen.findByTestId("exchange-kline-panel-stub");
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(onUrlStateChange).toHaveBeenCalledWith({ chartMode: "compare" });
  });

  it("reuses confirmed Market resources when returning to the Overview lens", async () => {
    const { paths } = installObservatoryFetch();
    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "overview" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(1));
    const initialCount = paths.length;

    page.rerender(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "runs" }}
        onUrlStateChange={() => {}}
      />,
    );
    await waitFor(() => expect(paths.some((path) => path.includes("/runs"))).toBe(true));
    const afterRunsCount = paths.length;

    page.rerender(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "overview" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(screen.getByTestId("exchange-kline-panel-stub")).toBeTruthy());
    expect(paths).toHaveLength(afterRunsCount);
    expect(paths.filter((path) => path.includes("/context"))).toHaveLength(1);
    expect(paths.filter((path) => path.includes("/series"))).toHaveLength(1);
    expect(afterRunsCount).toBe(initialCount + 1);
  });

  it("reloads cached Market resources after an explicit refresh", async () => {
    const { paths } = installObservatoryFetch();
    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "overview" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(1));

    page.rerender(
      <ObservatoryPage
        refreshToken={1}
        urlState={{ ...DEFAULT_STATE, lens: "overview" }}
        onUrlStateChange={() => {}}
      />,
    );

    await waitFor(() => expect(paths.filter((path) => path.includes("/context")).length).toBe(2));
    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(2));
  });

  it("accepts the backend null echo for the committed latest knowledge selector", async () => {
    const { paths } = installObservatoryFetch({
      context: { ...CONTEXT_FIXTURE, requested_knowledge_as_of: null },
    });
    renderPage();

    await waitFor(() => expect(paths.filter((path) => path.includes("/series")).length).toBe(1));
    expect(screen.queryByText("Market snapshot unavailable")).toBeNull();
  });

  it("rejects a latest Context response that omits its knowledge selector before loading descendants", async () => {
    const { paths } = installObservatoryFetch({
      context: { ...CONTEXT_FIXTURE, requested_knowledge_as_of: undefined },
    });
    renderPage({ date: "2026-07-10" });

    await waitFor(() => expect(screen.getByText("Market snapshot unavailable")).toBeTruthy());
    expect(screen.getByTestId("obs-truthbar")).toHaveTextContent("RESPONSE_IDENTITY_MISMATCH");
    expect(paths.filter((path) => path.includes("/context"))).toHaveLength(1);
    expect(paths.some((path) => path.includes("/series"))).toBe(false);
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
    expect(paths.some((path) => path.includes("/dates/"))).toBe(false);
    expect(screen.queryByTestId("market-summary")).toBeNull();
    expect(screen.queryByTestId("composite-chart")).toBeNull();
  });

  it("pins Assurance coverage and gates to the resolved Context snapshot without loading Market comparison", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({ lens: "trust", channel: "observed", range: "30D" });

    await waitFor(() => expect(paths.some((path) => path.includes("/trust"))).toBe(true));
    expect(
      paths.some(
        (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "composite",
      ),
    ).toBe(false);
    expect(paths.some((path) => path.includes("/runs"))).toBe(false);
    expect(paths.some((path) => path.includes("/hypotheses"))).toBe(false);

    const seriesPath = paths.find(
      (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "observed",
    );
    const trustPath = paths.find((path) =>
      path.endsWith("/trust?channel=observed&snapshot_id=snapshot_observed_0001"),
    );
    expect(new URL(seriesPath!, "https://trade.invalid").searchParams.get("snapshot_id")).toBe(
      CONTEXT_FIXTURE.snapshot_id,
    );
    expect(trustPath).toBeTruthy();
  });

  it("loads catalog-wide lineage only for a runs deep link and its selected detail/diff", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({ lens: "runs", runId: "run_formal", compareRunId: "run_observed" });

    await waitFor(() => expect(paths.some((path) => path.includes("/runs/diff"))).toBe(true));
    expect(paths.some((path) => path.includes("/context"))).toBe(false);
    expect(paths.some((path) => path.includes("/series"))).toBe(false);
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
    expect(paths.some((path) => path.includes("/hypotheses"))).toBe(false);
    expect(screen.getByText(/Catalog-wide immutable run evidence/)).toBeTruthy();
  });

  it("selects H1 by identity rather than the first hypothesis and loads only its run", async () => {
    const h1 = HYPOTHESES_FIXTURE.hypotheses?.[0];
    const hypotheses = {
      hypotheses: [
        {
          hypothesis_id: "H2",
          hypothesis_version: "other",
          statement: "Not the selected hypothesis.",
          current_research_run_id: "H2:run",
        },
        h1,
      ],
    };
    const { paths } = installObservatoryFetch({ hypotheses });
    renderPage({ lens: "research" });

    await waitFor(() =>
      expect(paths.some((path) => path.includes("/research-runs/H1%3Agen_0007"))).toBe(true),
    );
    expect(paths.some((path) => path.includes("/research-runs/H2%3Arun"))).toBe(false);
    expect(screen.getByTestId("research-scope-notice")).toHaveTextContent(
      "not confirmation of the selected Market snapshot",
    );
    expect(screen.queryByText("Not the selected hypothesis.")).toBeNull();
  });

  it("blocks dependent Market calls when Context is unavailable", async () => {
    const unavailableContext = jsonResponse(
      {
        message: "Point-in-time evidence is not proven.",
        reason_codes: ["PIT_NOT_PROVEN"],
        retryable: false,
      },
      { status: 422, statusText: "Unprocessable Entity" },
    );
    const fetchMock = vi.fn().mockResolvedValue(unavailableContext);
    vi.stubGlobal("fetch", fetchMock);

    renderPage({ chartMode: "compare" });

    await waitFor(() => expect(screen.getByText("Market snapshot unavailable")).toBeTruthy());
    expect(
      screen.getByText(/remain blocked until the selected snapshot is confirmed/i),
    ).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("blocks bounded descendants instead of issuing an unbounded request when Context has no watermark", async () => {
    const { paths } = installObservatoryFetch({
      context: { ...CONTEXT_FIXTURE, market_watermark: null },
    });
    renderPage({ range: "90D" });

    await waitFor(() =>
      expect(screen.getByText("Selected market window unavailable")).toBeTruthy(),
    );
    expect(paths.filter((path) => path.includes("/context"))).toHaveLength(1);
    expect(paths.some((path) => path.includes("/series"))).toBe(false);
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
  });

  it("rejects a composite whose active channel layer does not match Context", async () => {
    const composite = {
      ...COMPOSITE_FIXTURE,
      layers: {
        ...COMPOSITE_FIXTURE.layers,
        latest_observed: {
          ...COMPOSITE_FIXTURE.layers?.latest_observed,
          context: {
            ...CONTEXT_FIXTURE,
            snapshot_id: "snapshot_wrong_0001",
            resolved_channel: "observed",
          },
        },
      },
    };
    installObservatoryFetch({ composite });
    renderPage({ chartMode: "compare" });

    await waitFor(() => expect(screen.getByText("Composite comparison unavailable")).toBeTruthy());
    expect(
      screen.getByText("The selected composite layer did not match the resolved market snapshot."),
    ).toBeTruthy();
    expect(screen.queryByTestId("composite-chart")).toBeNull();
    expect(screen.queryByTestId("what-changed")).toBeNull();
  });

  it("suppresses unproven composite overlays for a historical knowledge cut", async () => {
    const { paths } = installObservatoryFetch({
      context: {
        ...CONTEXT_FIXTURE,
        requested_knowledge_as_of: "2026-07-11T00:00:00Z",
        effective_knowledge_cut: "2026-07-11T00:00:00Z",
      },
    });
    renderPage({ chartMode: "compare", knowledgeAsOf: "2026-07-11T00:00:00Z" });

    await waitFor(() => expect(screen.getByText("Composite comparison unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "COMPOSITE_PIT_NOT_PROVEN",
    );
    expect(
      paths.some(
        (path) => new URL(path, "https://trade.invalid").searchParams.get("view") === "composite",
      ),
    ).toBe(false);
    expect(screen.queryByTestId("composite-chart")).toBeNull();
  });

  it("rejects a current Context response for a historical knowledge cut before loading descendants", async () => {
    const { paths } = installObservatoryFetch();
    renderPage({
      knowledgeAsOf: "2026-07-11T00:00:00Z",
      date: "2026-07-10",
    });

    await waitFor(() => expect(screen.getByText("Market snapshot unavailable")).toBeTruthy());
    expect(screen.getByTestId("obs-truthbar")).toHaveTextContent("RESPONSE_IDENTITY_MISMATCH");
    expect(screen.getByText(/committed knowledge selector/i)).toBeTruthy();
    expect(paths.filter((path) => path.includes("/context"))).toHaveLength(1);
    expect(paths.some((path) => path.includes("/series"))).toBe(false);
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
    expect(paths.some((path) => path.includes("/dates/"))).toBe(false);
    expect(screen.queryByTestId("market-summary")).toBeNull();
    expect(screen.queryByTestId("composite-chart")).toBeNull();
  });

  it("fails closed on a non-PIT selected series and does not load Trust evidence", async () => {
    const { paths } = installObservatoryFetch({
      series: {
        ...selectedSeries("observed"),
        pit_valid: false,
        reason_codes: ["RESTATED_NOT_PIT"],
      },
    });
    renderPage({ lens: "trust" });

    await waitFor(() => expect(screen.getByText("Coverage evidence unavailable")).toBeTruthy());
    expect(screen.getAllByTestId("observatory-error-state")[0]).toHaveTextContent(
      "RESTATED_NOT_PIT",
    );
    expect(paths.some((path) => path.includes("/trust"))).toBe(false);
    expect(screen.queryByText("No findings recorded for this snapshot.")).toBeNull();
  });

  it("does not render Market metrics from a non-PIT selected series", async () => {
    installObservatoryFetch({
      series: {
        ...selectedSeries("observed"),
        pit_valid: false,
        reason_codes: ["RESTATED_NOT_PIT"],
      },
    });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Selected-channel market series unavailable")).toBeTruthy(),
    );
    expect(screen.queryByTestId("market-summary")).toBeNull();
    expect(
      screen.getByText(/market metrics are unavailable until its evidence is confirmed/i),
    ).toBeTruthy();
  });

  it("requires an immutable H1 research run before rendering the Research lens", async () => {
    const { paths } = installObservatoryFetch({
      hypotheses: {
        hypotheses: [
          {
            ...HYPOTHESES_FIXTURE.hypotheses?.[0],
            current_research_run_id: null,
          },
        ],
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_RUN_UNAVAILABLE",
    );
    expect(paths.some((path) => path.includes("/research-runs/"))).toBe(false);
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("reports a missing H1 with a safe reason and does not request another hypothesis receipt", async () => {
    const { paths } = installObservatoryFetch({ hypotheses: { hypotheses: [] } });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_HYPOTHESIS_UNAVAILABLE",
    );
    expect(paths.some((path) => path.includes("/research-runs/"))).toBe(false);
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("requires a non-empty H1 version before requesting a research receipt", async () => {
    const { paths } = installObservatoryFetch({
      hypotheses: {
        hypotheses: [
          {
            ...HYPOTHESES_FIXTURE.hypotheses?.[0],
            hypothesis_version: undefined,
          },
        ],
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_VERSION_UNAVAILABLE",
    );
    expect(paths.some((path) => path.includes("/research-runs/"))).toBe(false);
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt that omits its research state", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        research_state: undefined,
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_STATE_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt with an unrecognized research state", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        research_state: "future_state",
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_STATE_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt that omits its version identity", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        hypothesis_version: undefined,
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_VERSION_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects stale or version-drifted H1 research receipts", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        is_current: false,
        hypothesis_version: "btc-vol-persistence-v0",
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt that omits its dataset snapshot", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        dataset_snapshot_id: null,
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_SNAPSHOT_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt that omits its knowledge cutoff", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        knowledge_as_of: null,
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_KNOWLEDGE_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("rejects an H1 research receipt without evidence references", async () => {
    installObservatoryFetch({
      researchRun: {
        ...RESEARCH_RUN_FIXTURE,
        evidence_refs: [],
      },
    });
    renderPage({ lens: "research" });

    await waitFor(() => expect(screen.getByText("H1 research evidence unavailable")).toBeTruthy());
    expect(screen.getByTestId("observatory-error-state")).toHaveTextContent(
      "H1_RESEARCH_EVIDENCE_UNAVAILABLE",
    );
    expect(screen.queryByTestId("research-lens")).toBeNull();
  });

  it("reloads the H1 receipt once the refreshed same-run H1 version is confirmed", async () => {
    const h1 = HYPOTHESES_FIXTURE.hypotheses?.[0];
    if (!h1) {
      throw new Error("H1 fixture is required for the receipt reload regression.");
    }

    let hypothesisRequestCount = 0;
    let researchRequestCount = 0;
    let resolveRefreshedHypotheses: (response: Response) => void = () => {
      throw new Error("The refreshed hypotheses resolver is not initialized.");
    };
    const refreshedHypotheses = new Promise<Response>((resolve) => {
      resolveRefreshedHypotheses = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const requestUrl = new URL(
        typeof input === "string" ? input : input.toString(),
        "https://trade.invalid",
      );

      if (requestUrl.pathname.endsWith("/hypotheses")) {
        hypothesisRequestCount += 1;
        if (hypothesisRequestCount === 1) {
          return Promise.resolve(jsonResponse(HYPOTHESES_FIXTURE));
        }
        return refreshedHypotheses;
      }
      if (requestUrl.pathname.includes("/research-runs/")) {
        researchRequestCount += 1;
        return Promise.resolve(
          jsonResponse({
            ...RESEARCH_RUN_FIXTURE,
            hypothesis_version:
              researchRequestCount === 2 ? "btc-vol-persistence-v2" : h1.hypothesis_version,
          }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "research" }}
        onUrlStateChange={() => {}}
      />,
    );
    await waitFor(() => expect(researchRequestCount).toBe(1));
    await waitFor(() => expect(screen.getByTestId("research-lens")).toBeTruthy());
    expect(screen.getByTestId("research-metrics")).toBeTruthy();

    page.rerender(
      <ObservatoryPage
        refreshToken={1}
        urlState={{ ...DEFAULT_STATE, lens: "research" }}
        onUrlStateChange={() => {}}
      />,
    );
    await waitFor(() => expect(hypothesisRequestCount).toBe(2));
    expect(researchRequestCount).toBe(1);
    expect(screen.queryByTestId("research-lens")).toBeNull();
    expect(screen.queryByTestId("research-metrics")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Loading H1 research evidence");

    resolveRefreshedHypotheses(
      jsonResponse({
        hypotheses: [{ ...h1, hypothesis_version: "btc-vol-persistence-v2" }],
      }),
    );

    await waitFor(() => expect(researchRequestCount).toBe(2));
    await waitFor(() =>
      expect(screen.getByTestId("research-hypothesis")).toHaveTextContent("btc-vol-persistence-v2"),
    );
    expect(researchRequestCount).toBe(2);
  });

  it("withholds an unchanged H1 receipt until its refreshed receipt confirms", async () => {
    let hypothesisRequestCount = 0;
    let researchRequestCount = 0;
    let resolveRefreshedHypotheses: (response: Response) => void = () => {
      throw new Error("The refreshed hypotheses resolver is not initialized.");
    };
    let resolveRefreshedResearchRun: (response: Response) => void = () => {
      throw new Error("The refreshed research receipt resolver is not initialized.");
    };
    const refreshedHypotheses = new Promise<Response>((resolve) => {
      resolveRefreshedHypotheses = resolve;
    });
    const refreshedResearchRun = new Promise<Response>((resolve) => {
      resolveRefreshedResearchRun = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const requestUrl = new URL(
        typeof input === "string" ? input : input.toString(),
        "https://trade.invalid",
      );

      if (requestUrl.pathname.endsWith("/hypotheses")) {
        hypothesisRequestCount += 1;
        return hypothesisRequestCount === 1
          ? Promise.resolve(jsonResponse(HYPOTHESES_FIXTURE))
          : refreshedHypotheses;
      }
      if (requestUrl.pathname.includes("/research-runs/")) {
        researchRequestCount += 1;
        return researchRequestCount === 1
          ? Promise.resolve(jsonResponse(RESEARCH_RUN_FIXTURE))
          : refreshedResearchRun;
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = render(
      <ObservatoryPage
        refreshToken={0}
        urlState={{ ...DEFAULT_STATE, lens: "research" }}
        onUrlStateChange={() => {}}
      />,
    );
    await waitFor(() => expect(screen.getByTestId("research-lens")).toBeTruthy());
    expect(screen.getByTestId("research-metrics")).toBeTruthy();

    page.rerender(
      <ObservatoryPage
        refreshToken={1}
        urlState={{ ...DEFAULT_STATE, lens: "research" }}
        onUrlStateChange={() => {}}
      />,
    );
    await waitFor(() => expect(hypothesisRequestCount).toBe(2));
    expect(researchRequestCount).toBe(1);

    resolveRefreshedHypotheses(jsonResponse(HYPOTHESES_FIXTURE));

    await waitFor(() => expect(researchRequestCount).toBe(2));
    expect(screen.queryByTestId("research-lens")).toBeNull();
    expect(screen.queryByTestId("research-metrics")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Loading H1 research evidence");

    resolveRefreshedResearchRun(jsonResponse(RESEARCH_RUN_FIXTURE));

    await waitFor(() => expect(screen.getByTestId("research-lens")).toBeTruthy());
    expect(screen.getByTestId("research-metrics")).toBeTruthy();
    expect(researchRequestCount).toBe(2);
  });
});
