import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, type ObsErrorPayload } from "../../lib/api";
import type { ObservatoryResourceStatus, ObservatorySafeError } from "../../lib/observatory";

const MAX_MEMORY_CACHE_BYTES = 1_000_000;

export type ObservatoryResourceState<T> = {
  identity: string | null;
  status: ObservatoryResourceStatus;
  data: T | null;
  error: ApiError | null;
  confirmedReloadKey: unknown | null;
};

export type ObservatoryValidationFailure = {
  message: string;
  reasonCodes?: string[];
  evidenceRefs?: string[];
  retryable?: boolean;
};

export type ObservatoryResourceOptions<T> = {
  enabled?: boolean;
  reloadKey?: unknown;
  validateResponse?: (data: T) => boolean | ObservatoryValidationFailure;
};

type MemoryCacheEntry = {
  etag: string;
  data: unknown;
  bytes: number;
};

type FetchResult<T> = {
  data: T;
  etag: string | null;
  fromMemory: boolean;
};

const memoryCache = new Map<string, MemoryCacheEntry>();
let memoryCacheBytes = 0;

function compareStrings(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

/**
 * Canonical identity for an Observatory GET. Every selector is retained so an
 * ETag from one snapshot, channel, date, or run is never reused for another.
 */
export function observatoryRequestIdentity(path: string): string {
  const url = new URL(path, "https://observatory.invalid");
  const entries = [...url.searchParams.entries()].sort(
    ([leftKey, leftValue], [rightKey, rightValue]) => {
      const keyOrder = compareStrings(leftKey, rightKey);
      return keyOrder === 0 ? compareStrings(leftValue, rightValue) : keyOrder;
    },
  );
  const params = new URLSearchParams(entries);
  const query = params.toString();
  return `GET ${url.pathname}${query ? `?${query}` : ""}`;
}

function cacheEntry(identity: string): MemoryCacheEntry | null {
  const entry = memoryCache.get(identity);
  if (!entry) {
    return null;
  }
  memoryCache.delete(identity);
  memoryCache.set(identity, entry);
  return entry;
}

function deleteCacheEntry(identity: string) {
  const entry = memoryCache.get(identity);
  if (!entry) {
    return;
  }
  memoryCacheBytes -= entry.bytes;
  memoryCache.delete(identity);
}

function serializedSize(value: unknown): number | null {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return null;
  }
}

function storeCacheEntry(identity: string, etag: string, data: unknown) {
  const bytes = serializedSize({ identity, etag, data });
  if (bytes === null || bytes > MAX_MEMORY_CACHE_BYTES) {
    deleteCacheEntry(identity);
    return;
  }

  deleteCacheEntry(identity);
  memoryCache.set(identity, { etag, data, bytes });
  memoryCacheBytes += bytes;

  while (memoryCacheBytes > MAX_MEMORY_CACHE_BYTES) {
    const oldestIdentity = memoryCache.keys().next().value;
    if (typeof oldestIdentity !== "string") {
      break;
    }
    deleteCacheEntry(oldestIdentity);
  }
}

function readResponsePayload(text: string): unknown {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function apiErrorFromResponse(response: Response, payload: unknown): ApiError {
  const message =
    (typeof payload === "object" &&
      payload &&
      "message" in payload &&
      typeof payload.message === "string" &&
      payload.message) ||
    response.statusText ||
    "Observatory request failed.";
  return new ApiError(message, response.status, payload);
}

async function fetchObservatoryResource<T>(
  path: string,
  identity: string,
  signal: AbortSignal,
): Promise<FetchResult<T>> {
  const cached = cacheEntry(identity);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (cached) {
    headers["If-None-Match"] = cached.etag;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      headers,
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    throw new ApiError(
      "Network request failed. Check whether the backend is reachable.",
      undefined,
      {
        message: "Network request failed. Check whether the backend is reachable.",
        retryable: true,
      },
    );
  }

  if (response.status === 304) {
    if (cached) {
      return { data: cached.data as T, etag: cached.etag, fromMemory: true };
    }
    throw new ApiError("The response could not be revalidated from memory.", 304, {
      message: "Current Observatory data is unavailable. Refresh to request a full response.",
      retryable: true,
    });
  }

  const payload = readResponsePayload(await response.text());
  if (!response.ok) {
    throw apiErrorFromResponse(response, payload);
  }

  return {
    data: payload as T,
    etag: response.headers.get("ETag"),
    fromMemory: false,
  };
}

function responseIdentityError(failure?: ObservatoryValidationFailure): ApiError {
  const message =
    failure?.message ?? "The response did not match the active Observatory selection.";
  return new ApiError("Response identity did not match the active request.", 422, {
    message,
    reason_codes: failure?.reasonCodes ?? ["RESPONSE_IDENTITY_MISMATCH"],
    evidence_refs: failure?.evidenceRefs ?? [],
    retryable: failure?.retryable ?? true,
  });
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError("Observatory request failed.", undefined, {
    message: "Unable to load current Observatory evidence.",
    retryable: true,
  });
}

function unavailableStatus(status: number | undefined): boolean {
  return status === 400 || status === 404 || status === 409 || status === 422 || status === 503;
}

function safeText(value: unknown, fallback: string): string {
  if (typeof value !== "string") {
    return fallback;
  }
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 240 || /[\\/\r\n]/.test(trimmed)) {
    return fallback;
  }
  return trimmed;
}

function safeStringList(value: unknown, pattern: RegExp): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is string => typeof item === "string" && pattern.test(item))
    .slice(0, 8);
}

/**
 * Converts the frozen safe error payload into display data. Raw response text,
 * exception strings, and path-shaped values are intentionally not exposed.
 */
export function parseObservatoryError(
  error: ApiError | null | undefined,
): ObservatorySafeError | null {
  if (!error) {
    return null;
  }
  const detail = error.detail;
  const payload =
    typeof detail === "object" && detail !== null ? (detail as ObsErrorPayload) : null;
  const fallback = unavailableStatus(error.status)
    ? "This Observatory resource is unavailable for the selected evidence."
    : "Unable to load current Observatory evidence.";

  return {
    message: safeText(payload?.message, fallback),
    reasonCodes: safeStringList(payload?.reason_codes, /^[A-Z][A-Z0-9_]{0,95}$/),
    evidenceRefs: safeStringList(payload?.evidence_refs, /^[A-Za-z0-9._:-]{1,160}$/),
    retryable: payload?.retryable === true,
  };
}

export function clearObservatoryResourceMemoryCache() {
  memoryCache.clear();
  memoryCacheBytes = 0;
}

/**
 * Scoped Observatory GET lifecycle. It has no persistent cache: only a
 * byte-capped in-memory ETag entry for the exact full request identity.
 */
export function useObservatoryResource<T>(
  path: string | null,
  options: ObservatoryResourceOptions<T> = {},
) {
  const { enabled = true, reloadKey, validateResponse } = options;
  const validateResponseRef = useRef(validateResponse);
  validateResponseRef.current = validateResponse;
  const identity = useMemo(() => (path ? observatoryRequestIdentity(path) : null), [path]);
  const [state, setState] = useState<ObservatoryResourceState<T>>({
    identity: null,
    status: "idle",
    data: null,
    error: null,
    confirmedReloadKey: null,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!path || !identity || !enabled) {
      setState({
        identity,
        status: "idle",
        data: null,
        error: null,
        confirmedReloadKey: null,
      });
      return;
    }

    const controller = new AbortController();
    setState({
      identity,
      status: "loading",
      data: null,
      error: null,
      confirmedReloadKey: null,
    });

    fetchObservatoryResource<T>(path, identity, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) {
          return;
        }
        const validation = validateResponseRef.current?.(result.data);
        if (validation === false || (validation && validation !== true)) {
          throw responseIdentityError(validation === false ? undefined : validation);
        }
        if (!result.fromMemory) {
          if (result.etag) {
            storeCacheEntry(identity, result.etag, result.data);
          } else {
            deleteCacheEntry(identity);
          }
        }
        setState({
          identity,
          status: "confirmed",
          data: result.data,
          error: null,
          confirmedReloadKey: reloadKey ?? null,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const apiError = toApiError(error);
        setState({
          identity,
          status: unavailableStatus(apiError.status) ? "unavailable" : "failed",
          data: null,
          error: apiError,
          confirmedReloadKey: null,
        });
      });

    return () => {
      controller.abort();
    };
  }, [attempt, enabled, identity, path, reloadKey]);

  const current =
    state.identity === identity
      ? state
      : {
          identity,
          status: "idle" as const,
          data: null,
          error: null,
          confirmedReloadKey: null,
        };

  return {
    ...current,
    loading: current.status === "loading",
    retry: useCallback(() => setAttempt((currentAttempt) => currentAttempt + 1), []),
  };
}
