import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

// RA.1 (docs/27 Phase A, F14): App-level fail-closed behavior for the Observatory
// rollout capability. Only a FRESH, successful capability response with show_nav
// may authorize the nav entry and mount the Observatory page. Cached/previous
// ready, loading, error, and direct ?obsLens URLs on an unready backend must all
// deny. AppShell-injection tests (observatory.nav.test.tsx) are insufficient for
// this because they bypass the App's capability request/freshness logic.

type FetchController = {
  // Resolves the capability request with the given JSON body.
  capabilityBody: unknown;
  // When set, the capability request rejects (network failure) instead.
  capabilityFails: boolean;
  // When set, the capability request never resolves (stays loading).
  capabilityPending: boolean;
};

const control: FetchController = {
  capabilityBody: { enabled: true, state: "ready", show_nav: true },
  capabilityFails: false,
  capabilityPending: false,
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/observatory/capability")) {
      if (control.capabilityPending) {
        return new Promise<Response>(() => {}); // never settles -> stays loading
      }
      if (control.capabilityFails) {
        throw new TypeError("network down");
      }
      return jsonResponse(control.capabilityBody);
    }
    // Every other shell request (trust overview, today page, etc.) returns a
    // benign empty object so the app renders without crashing.
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function setUrl(search: string) {
  window.history.replaceState({}, "", `/${search}`);
}

beforeEach(() => {
  window.localStorage.clear();
  control.capabilityBody = { enabled: true, state: "ready", show_nav: true };
  control.capabilityFails = false;
  control.capabilityPending = false;
  setUrl("");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App Observatory capability gating (fail closed)", () => {
  it("shows nav and mounts Observatory only after a fresh ready response", async () => {
    control.capabilityBody = { enabled: true, state: "ready", show_nav: true };
    installFetch();
    setUrl("?obsLens=overview");
    render(<App />);

    // Fresh success authorizes: nav appears and the Observatory page mounts.
    await waitFor(() => expect(screen.getByTestId("nav-observatory")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("observatory-page")).toBeTruthy());
  });

  it("denies when a previous ready page is remembered but the capability request fails", async () => {
    // Simulate a prior session that had Observatory open (localStorage remembers
    // the page). A capability cache must NOT authorize: with the request failing,
    // there is no fresh success, so nav stays hidden and Observatory never mounts.
    window.localStorage.setItem("trade-web:page", JSON.stringify("observatory"));
    window.localStorage.setItem(
      "trade-web:obs-capability",
      JSON.stringify({ enabled: true, state: "ready", show_nav: true }),
    );
    control.capabilityFails = true;
    installFetch();
    render(<App />);

    // Give the failing request time to settle, then assert fail-closed.
    await waitFor(() => expect(screen.queryByTestId("nav-today")).toBeTruthy());
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    expect(screen.queryByTestId("observatory-page")).toBeNull();
  });

  it("denies while the capability request is loading (no premature authorization)", async () => {
    control.capabilityPending = true;
    installFetch();
    setUrl("?obsLens=overview");
    render(<App />);

    // The shell renders immediately; the capability is still in flight, so the
    // Observatory nav/page must not appear.
    await waitFor(() => expect(screen.getByTestId("nav-today")).toBeTruthy());
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    expect(screen.queryByTestId("observatory-page")).toBeNull();
  });

  it("denies on an error capability state even with a fresh response", async () => {
    control.capabilityBody = { enabled: true, state: "error", show_nav: false };
    installFetch();
    setUrl("?obsLens=overview");
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("nav-today")).toBeTruthy());
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    expect(screen.queryByTestId("observatory-page")).toBeNull();
  });

  it.each([
    { enabled: false, state: "ready", show_nav: true },
    { enabled: true, state: "catalog_missing", show_nav: true },
  ])("denies contradictory capability payload %o", async (capability) => {
    control.capabilityBody = capability;
    installFetch();
    setUrl("?obsLens=overview");
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("nav-today")).toBeTruthy());
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    expect(screen.queryByTestId("observatory-page")).toBeNull();
    expect(screen.getByTestId("observatory-unavailable-notice")).toBeTruthy();
  });

  it.each([
    { state: "disabled", enabled: false },
    { state: "catalog_missing", enabled: true },
    { state: "catalog_stale", enabled: true },
    { state: "catalog_corrupt", enabled: true },
  ])("denies a direct ?obsLens URL when capability is %o", async ({ state, enabled }) => {
    control.capabilityBody = { enabled, state, show_nav: false };
    installFetch();
    setUrl("?obsLens=overview");
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("nav-today")).toBeTruthy());
    // Direct-open must fail closed: unready backend never mounts Observatory.
    expect(screen.queryByTestId("observatory-page")).toBeNull();
    expect(screen.queryByTestId("nav-observatory")).toBeNull();
    const notice = screen.getByTestId("observatory-unavailable-notice");
    expect(notice).toHaveTextContent("BTC Observatory is unavailable.");
    expect(
      (screen.getByLabelText("Attempted Observatory link") as HTMLInputElement).value,
    ).toContain("obsLens=overview");
  });

  it("keeps only safe Observatory selectors in a denied attempted link", async () => {
    control.capabilityBody = { enabled: false, state: "disabled", show_nav: false };
    installFetch();
    setUrl("?obsLens=overview&obsDate=2026-07-15&access_token=not-safe");
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("observatory-unavailable-notice")).toBeTruthy());
    const attemptedLink = (screen.getByLabelText("Attempted Observatory link") as HTMLInputElement)
      .value;
    expect(attemptedLink).toContain("obsLens=overview");
    expect(attemptedLink).toContain("obsDate=2026-07-15");
    expect(attemptedLink).not.toContain("access_token");
  });
});
