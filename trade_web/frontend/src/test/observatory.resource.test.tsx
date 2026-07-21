import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearObservatoryResourceMemoryCache,
  observatoryRequestIdentity,
  parseObservatoryError,
  useObservatoryResource,
} from "../pages/observatory/observatoryResource";

type Fixture = { snapshot_id: string; value: string };

type PendingRequest = {
  path: string;
  init?: RequestInit;
  resolve: (response: Response) => void;
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

function deferredFetch() {
  const requests: PendingRequest[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input.toString();
    return new Promise<Response>((resolve) => {
      requests.push({ path, init, resolve });
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, requests };
}

beforeEach(() => {
  clearObservatoryResourceMemoryCache();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("observatoryRequestIdentity", () => {
  it("preserves every selector while normalizing query ordering", () => {
    expect(
      observatoryRequestIdentity("/api/series?channel=observed&snapshot_id=snap-a&from=2026-07-01"),
    ).toBe(
      observatoryRequestIdentity("/api/series?from=2026-07-01&snapshot_id=snap-a&channel=observed"),
    );
    expect(observatoryRequestIdentity("/api/series?channel=observed&snapshot_id=snap-a")).not.toBe(
      observatoryRequestIdentity("/api/series?channel=observed&snapshot_id=snap-b"),
    );
  });
});

describe("useObservatoryResource", () => {
  it("aborts a superseded identity, clears old truth, and ignores its late response", async () => {
    const { requests } = deferredFetch();
    const firstPath = "/api/series?channel=observed&snapshot_id=snap-a";
    const secondPath = "/api/series?channel=observed&snapshot_id=snap-b";
    const { result, rerender } = renderHook(({ path }) => useObservatoryResource<Fixture>(path), {
      initialProps: { path: firstPath },
    });

    await waitFor(() => expect(requests).toHaveLength(1));
    const first = requests[0];
    expect(result.current.status).toBe("loading");

    rerender({ path: secondPath });

    await waitFor(() => expect(requests).toHaveLength(2));
    expect(first.init?.signal?.aborted).toBe(true);
    expect(result.current.status).toBe("loading");
    expect(result.current.data).toBeNull();

    await act(async () => {
      first.resolve(jsonResponse({ snapshot_id: "snap-a", value: "obsolete" }));
    });
    expect(result.current.status).toBe("loading");
    expect(result.current.data).toBeNull();

    await act(async () => {
      requests[1].resolve(jsonResponse({ snapshot_id: "snap-b", value: "current" }));
    });
    await waitFor(() => expect(result.current.status).toBe("confirmed"));
    expect(result.current.data).toEqual({ snapshot_id: "snap-b", value: "current" });
  });

  it("reuses a 304 payload only from the exact in-memory request identity", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { snapshot_id: "snap-a", value: "first" },
          {
            headers: { ETag: "etag-snap-a" },
          },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 304 }));
    vi.stubGlobal("fetch", fetchMock);

    const firstPath = "/api/series?channel=observed&snapshot_id=snap-a";
    const canonicalEquivalentPath = "/api/series?snapshot_id=snap-a&channel=observed";
    const { result, rerender } = renderHook(({ path }) => useObservatoryResource<Fixture>(path), {
      initialProps: { path: firstPath },
    });

    await waitFor(() => expect(result.current.status).toBe("confirmed"));
    expect(result.current.data).toEqual({ snapshot_id: "snap-a", value: "first" });

    rerender({ path: canonicalEquivalentPath });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.status).toBe("confirmed"));
    expect(result.current.data).toEqual({ snapshot_id: "snap-a", value: "first" });
    expect((fetchMock.mock.calls[1][1] as RequestInit | undefined)?.headers).toEqual({
      Accept: "application/json",
      "If-None-Match": "etag-snap-a",
    });
    expect(window.localStorage.length).toBe(0);
  });

  it("does not treat a 304 without exact cached data as current truth", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 304 })));

    const { result } = renderHook(() =>
      useObservatoryResource<Fixture>("/api/series?channel=observed&snapshot_id=snap-a"),
    );

    await waitFor(() => expect(result.current.status).toBe("failed"));
    expect(result.current.data).toBeNull();
    expect(parseObservatoryError(result.current.error)?.retryable).toBe(true);
  });

  it("classifies safe structured availability errors without exposing path-shaped evidence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            message: "Point-in-time evidence is not proven.",
            reason_codes: ["PIT_NOT_PROVEN"],
            evidence_refs: ["catalog:snap-a", "/unsafe/local/path"],
            retryable: false,
          },
          { status: 422, statusText: "Unprocessable Entity" },
        ),
      ),
    );

    const { result } = renderHook(() =>
      useObservatoryResource<Fixture>("/api/series?channel=observed&snapshot_id=snap-a"),
    );

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
    expect(result.current.data).toBeNull();
    expect(parseObservatoryError(result.current.error)).toEqual({
      message: "Point-in-time evidence is not proven.",
      reasonCodes: ["PIT_NOT_PROVEN"],
      evidenceRefs: ["catalog:snap-a"],
      retryable: false,
    });
  });

  it("surfaces a semantic response rejection as structured unavailable evidence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ snapshot_id: "snap-a", value: "restated" })),
    );

    const { result } = renderHook(() =>
      useObservatoryResource<Fixture>("/api/series?channel=observed&snapshot_id=snap-a", {
        validateResponse: () => ({
          message:
            "The selected market series is not point-in-time valid for this evidence selection.",
          reasonCodes: ["RESTATED_NOT_PIT"],
          retryable: false,
        }),
      }),
    );

    await waitFor(() => expect(result.current.status).toBe("unavailable"));
    expect(result.current.data).toBeNull();
    expect(parseObservatoryError(result.current.error)).toMatchObject({
      reasonCodes: ["RESTATED_NOT_PIT"],
      retryable: false,
    });
  });
});
