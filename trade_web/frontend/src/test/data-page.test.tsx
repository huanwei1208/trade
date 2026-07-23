import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssetInventoryTable } from "../components/AssetInventoryTable";
import { KlineViewer } from "../components/KlineViewer";
import type { DataAsset, DataAssetObservability } from "../lib/api";
import { OBSERVED_SERIES_FIXTURE } from "./fixtures";

const btcAsset: DataAsset = {
  asset_id: "crypto.BTC",
  asset_class: "crypto",
  symbol: "BTC",
  venue: "okx",
  data_types: ["kline", "sentiment", "news"],
  total_rows: 730,
  first_date: "2024-07-12",
  last_date: "2026-07-11",
  lag_days: 12,
  health: "error",
};

const ethAsset: DataAsset = {
  ...btcAsset,
  asset_id: "crypto.ETH",
  symbol: "ETH",
  last_date: "2026-07-15",
  lag_days: 8,
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/v1/observatory/assets/crypto.BTC/series")) {
        return jsonResponse(OBSERVED_SERIES_FIXTURE);
      }
      if (url.includes("/api/data/kline/crypto.ETH")) {
        return jsonResponse({
          asset_id: "crypto.ETH",
          symbol: "ETH",
          interval: "1d",
          rows: [
            {
              date: "2026-07-15",
              open: 100,
              high: 110,
              low: 90,
              close: 105,
              volume: 1000,
            },
          ],
        });
      }
      return jsonResponse({});
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Data page BTC observability", () => {
  it("uses the BTC observed Observatory series for the generic K-Line viewer", async () => {
    render(<KlineViewer asset={btcAsset} />);

    await waitFor(() =>
      expect(screen.getByTestId("data-kline-source")).toHaveTextContent("Observed BTC"),
    );
    expect(screen.getByTestId("data-kline-source")).toHaveTextContent("Latest 2026-07-18");
    expect(screen.getByTestId("data-kline-source")).toHaveTextContent("published 2026-07-11");
    expect(screen.getByText("2026-07-18")).toBeTruthy();

    const fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/v1/observatory/assets/crypto.BTC/series",
    );
    expect(String(fetchMock.mock.calls[0][0])).toContain("view=observed");
  });

  it("keeps non-BTC assets on the existing published kline API", async () => {
    render(<KlineViewer asset={ethAsset} />);

    await waitFor(() =>
      expect(screen.getByTestId("data-kline-source")).toHaveTextContent("Published data"),
    );
    expect(screen.getByText("2026-07-15")).toBeTruthy();

    const fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/data/kline/crypto.ETH");
  });

  it("shows BTC observed latest while preserving the published watermark in the asset table", () => {
    const observed: DataAssetObservability = {
      asset_id: "crypto.BTC",
      status: "confirmed",
      channel: "observed",
      last_date: "2026-07-21",
      published_last_date: "2026-07-11",
      lag_days: 2,
      lifecycle_state: "staged",
      quality_state: "degraded",
      freshness_state: "fresh",
      run_id: "observed-run",
      reason_codes: [],
    };

    render(
      <AssetInventoryTable
        assets={[btcAsset, ethAsset]}
        observabilityByAsset={{ "crypto.BTC": observed }}
      />,
    );

    const btcRow = screen.getByText("crypto.BTC").closest("tr");
    expect(btcRow).not.toBeNull();
    const row = within(btcRow as HTMLTableRowElement);
    expect(row.getByText("2026-07-21")).toBeTruthy();
    expect(row.getByText("published 2026-07-11")).toBeTruthy();
    expect(row.getByText("observed")).toBeTruthy();
    expect(row.getByText("Stale")).toBeTruthy();

    fireEvent.change(screen.getByDisplayValue("All classes"), { target: { value: "crypto" } });
    expect(screen.getByText("2 / 2 assets")).toBeTruthy();
  });
});
