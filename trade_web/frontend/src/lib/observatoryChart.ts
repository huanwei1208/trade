import type {
  ObsAvailabilityState,
  ObsChannel,
  ObsContext,
  ObsRevisionState,
  ObsSeriesRow,
  ObsSingleSeries,
} from "./api";
import type { ObservatoryTimeframe } from "./observatory";

export const OBSERVATORY_KLINE_MAX_DAYS = 7_300;
export const OBSERVATORY_DIAGNOSTIC_REASON_LIMIT = 16;
export const OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT = 8;
export const OBSERVATORY_AGGREGATE_DECIMAL_DIGIT_LIMIT = 128;
export const OBSERVATORY_AGGREGATE_METADATA_LIMIT = OBSERVATORY_KLINE_MAX_DAYS;
export const OBSERVATORY_AGGREGATE_REASON_LIMIT = OBSERVATORY_DIAGNOSTIC_REASON_LIMIT;

const DAY_MS = 86_400_000;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const STRICT_DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
const SAFE_REASON_CODE = /^[A-Za-z0-9_:-]{1,64}$/;

export type ObservatoryKlineState = "ready" | "partial-invalid" | "empty" | "invalid";

export type ObservatoryKlineIdentity = {
  assetId: string;
  displaySymbol: string;
  provider: string;
  instrument: string;
  quote: string;
  interval: "1Dutc";
};

export type ObservatoryKlineLifecycle = {
  channel: ObsChannel;
  channelLabel: "Published baseline" | "Evaluated candidate" | "Latest observed";
  publication: "published" | "unpublished";
  publicationLabel: "Published baseline" | "UNPUBLISHED";
  lifecycleState: string | null;
};

export type ObservatoryCandleDatum = {
  time: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
};

export type ObservatoryVolumeDatum = {
  time: string;
  value?: number;
  color?: string;
};

export type ObservatoryKlineReadout = {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string | null;
  availabilityState: ObsAvailabilityState;
  revisionState: ObsRevisionState;
  qualityFlags: string[];
};

export type ObservatoryKlineDiagnostic = {
  date: string | null;
  reasonCodes: string[];
  evidenceRefs: string[];
  markerPosition: "above" | "below";
  omittedReasonCodeCount: number;
  omittedEvidenceRefCount: number;
};

export type ObservatoryKlineMarker = {
  time: string;
  reasonCodes: string[];
  evidenceRefs: string[];
  position: "above" | "below";
  tone: "info" | "warning" | "error";
};

export type ObservatoryKlineModel = {
  state: ObservatoryKlineState;
  identity: ObservatoryKlineIdentity | null;
  lifecycle: ObservatoryKlineLifecycle | null;
  candles: ObservatoryCandleDatum[];
  volumes: ObservatoryVolumeDatum[];
  markers: ObservatoryKlineMarker[];
  dates: string[];
  readouts: Record<string, ObservatoryKlineReadout>;
  diagnostics: ObservatoryKlineDiagnostic[];
  suppliedRowCount: number;
  renderedCandleCount: number;
  invalidRowCount: number;
  affectedDateCount: number;
  spanDays: number;
  fatalReasonCodes: string[];
  omittedFatalReasonCodeCount: number;
  timeframe?: ObservatoryTimeframe;
  canonicalDates?: Record<string, string | null>;
  bucketMetadata?: Record<string, ObservatoryKlineBucketMetadata>;
};

export type ObservatoryKlineBucketMetadata = {
  start: string;
  end: string;
  canonicalDate: string | null;
  coveredDateCount: number;
  validDateCount: number;
  partial: boolean;
  reasonCodes: string[];
  evidenceRefs: string[];
  omittedEvidenceRefCount: number;
  omittedReasonCodeCount: number;
  sourceInterval: string;
  snapshotId: string;
  channel: string;
};

export type ObservatoryKlineWindow = {
  from: string;
  to: string;
};

type ParsedRow = {
  row: ObsSeriesRow;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  readout: ObservatoryKlineReadout;
};

type DiagnosticEntry = {
  reasonCodes: Set<string>;
  evidenceRefs: Set<string>;
  markerPosition: "above" | "below";
  omittedReasonCodeCount: number;
  omittedEvidenceRefCount: number;
};

type DiagnosticMap = Map<string | null, DiagnosticEntry>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeEvidenceRef(value: string): boolean {
  if (value.length === 0 || value.length > 256 || value !== value.trim()) return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 31 || code === 127) return false;
  }
  return true;
}

function safeEvidenceRefs(value: unknown): { values: string[]; omittedCount: number } {
  if (!Array.isArray(value)) return { values: [], omittedCount: 0 };
  const values: string[] = [];
  let omittedCount = 0;
  for (const item of value) {
    if (typeof item !== "string" || !isSafeEvidenceRef(item) || values.includes(item)) continue;
    if (values.length < OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT) values.push(item);
    else omittedCount += 1;
  }
  return { values: values.sort(), omittedCount };
}

function markerPosition(value: unknown): "above" | "below" {
  return value === "below" ? "below" : "above";
}

function safeReasonCode(value: string | null | undefined, fallback: string): string {
  const normalized = value?.trim().replaceAll("-", "_").toUpperCase();
  return normalized && SAFE_REASON_CODE.test(normalized) ? normalized : fallback;
}

function addDiagnostic(
  diagnostics: DiagnosticMap,
  date: string | null,
  code: string,
  evidenceRefs: string[] = [],
  position: "above" | "below" = "above",
  omittedEvidenceRefCount = 0,
): void {
  const current = diagnostics.get(date) ?? {
    reasonCodes: new Set<string>(),
    evidenceRefs: new Set<string>(),
    markerPosition: position,
    omittedReasonCodeCount: 0,
    omittedEvidenceRefCount: 0,
  };
  if (!current.reasonCodes.has(code)) {
    if (current.reasonCodes.size < OBSERVATORY_DIAGNOSTIC_REASON_LIMIT) {
      current.reasonCodes.add(code);
    } else {
      current.omittedReasonCodeCount += 1;
    }
  }
  for (const evidenceRef of evidenceRefs) {
    if (current.evidenceRefs.has(evidenceRef)) continue;
    if (current.evidenceRefs.size < OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT) {
      current.evidenceRefs.add(evidenceRef);
    } else {
      current.omittedEvidenceRefCount += 1;
    }
  }
  current.omittedEvidenceRefCount += omittedEvidenceRefCount;
  if (position === "below") current.markerPosition = "below";
  diagnostics.set(date, current);
}

function parseIsoDate(value: unknown): number | null {
  if (typeof value !== "string" || !ISO_DATE.test(value)) {
    return null;
  }
  const epoch = Date.parse(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(epoch) || new Date(epoch).toISOString().slice(0, 10) !== value) {
    return null;
  }
  return epoch;
}

function parseDecimal(value: unknown, allowZero: boolean): number | null {
  if (typeof value !== "string" || !STRICT_DECIMAL.test(value)) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || (allowZero ? parsed < 0 : parsed <= 0)) {
    return null;
  }
  return parsed;
}

function normalizedDecimalMagnitude(value: string): { integer: string; fraction: string } {
  const unsigned = value.startsWith("+") ? value.slice(1) : value;
  const [rawInteger = "", rawFraction = ""] = unsigned.split(".", 2);
  return {
    integer: rawInteger.replace(/^0+(?=\d)/, "") || "0",
    fraction: rawFraction.replace(/0+$/, ""),
  };
}

function compareExactPositiveDecimals(left: string, right: string): number {
  const leftValue = normalizedDecimalMagnitude(left);
  const rightValue = normalizedDecimalMagnitude(right);
  if (leftValue.integer.length !== rightValue.integer.length) {
    return leftValue.integer.length < rightValue.integer.length ? -1 : 1;
  }
  if (leftValue.integer !== rightValue.integer) {
    return leftValue.integer < rightValue.integer ? -1 : 1;
  }
  const fractionLength = Math.max(leftValue.fraction.length, rightValue.fraction.length);
  const leftFraction = leftValue.fraction.padEnd(fractionLength, "0");
  const rightFraction = rightValue.fraction.padEnd(fractionLength, "0");
  if (leftFraction === rightFraction) return 0;
  return leftFraction < rightFraction ? -1 : 1;
}

function requiredText(value: string | null | undefined): string | null {
  return typeof value === "string" && value.trim() === value && value.length > 0 ? value : null;
}

function buildIdentity(
  context: ObsContext,
  diagnostics: DiagnosticMap,
): ObservatoryKlineIdentity | null {
  const contract = context.contract;
  const assetId = requiredText(contract?.asset_id);
  const displaySymbol = requiredText(contract?.display_symbol);
  const provider = requiredText(contract?.primary_provider);
  const instrument = requiredText(contract?.primary_instrument);
  const quote = requiredText(contract?.quote);
  const interval = requiredText(contract?.primary_interval);

  if (!assetId || !displaySymbol || !provider || !instrument || !quote || !interval) {
    addDiagnostic(diagnostics, null, "CONTRACT_UNAVAILABLE");
    return null;
  }
  if (assetId !== "crypto.BTC") {
    addDiagnostic(diagnostics, null, "ASSET_IDENTITY_MISMATCH");
    return null;
  }
  if (interval !== "1Dutc") {
    addDiagnostic(diagnostics, null, "UNSUPPORTED_INTERVAL");
    return null;
  }
  return { assetId, displaySymbol, provider, instrument, quote, interval };
}

function isObsChannel(value: unknown): value is ObsChannel {
  return value === "formal" || value === "evaluated_candidate" || value === "observed";
}

function buildLifecycle(
  series: ObsSingleSeries,
  activeContext: ObsContext,
  diagnostics: DiagnosticMap,
): ObservatoryKlineLifecycle | null {
  const channel = series.view;
  const activeChannel = activeContext.resolved_channel;
  const selectedChannel = series.context?.resolved_channel;
  if (
    !isObsChannel(channel) ||
    !isObsChannel(activeChannel) ||
    !isObsChannel(selectedChannel) ||
    channel !== activeChannel ||
    channel !== selectedChannel
  ) {
    addDiagnostic(diagnostics, null, "LIFECYCLE_IDENTITY_MISMATCH");
    return null;
  }

  if (channel === "formal") {
    return {
      channel,
      channelLabel: "Published baseline",
      publication: "published",
      publicationLabel: "Published baseline",
      lifecycleState: requiredText(activeContext.lifecycle_state) ?? null,
    };
  }
  return {
    channel,
    channelLabel: channel === "evaluated_candidate" ? "Evaluated candidate" : "Latest observed",
    publication: "unpublished",
    publicationLabel: "UNPUBLISHED",
    lifecycleState: requiredText(activeContext.lifecycle_state) ?? null,
  };
}

function contractsMatch(active: ObsContext, selected: ObsContext | undefined): boolean {
  const activeContract = active.contract;
  const selectedContract = selected?.contract;
  return (
    selectedContract !== undefined &&
    selectedContract.asset_id === activeContract?.asset_id &&
    selectedContract.display_symbol === activeContract?.display_symbol &&
    selectedContract.primary_provider === activeContract?.primary_provider &&
    selectedContract.primary_instrument === activeContract?.primary_instrument &&
    selectedContract.quote === activeContract?.quote &&
    selectedContract.primary_interval === activeContract?.primary_interval
  );
}

function parsePresentRow(
  row: ObsSeriesRow,
  date: string,
  diagnostics: DiagnosticMap,
): ParsedRow | null {
  const open = parseDecimal(row.open, false);
  const high = parseDecimal(row.high, false);
  const low = parseDecimal(row.low, false);
  const close = parseDecimal(row.close, false);
  const volume =
    row.volume === null || row.volume === undefined ? null : parseDecimal(row.volume, true);

  if (open === null || high === null || low === null || close === null) {
    addDiagnostic(diagnostics, date, "INVALID_OHLC_DECIMAL");
    return null;
  }
  if (row.volume !== null && row.volume !== undefined && volume === null) {
    addDiagnostic(diagnostics, date, "INVALID_VOLUME");
    return null;
  }
  const exactOpen = row.open as string;
  const exactHigh = row.high as string;
  const exactLow = row.low as string;
  const exactClose = row.close as string;
  if (
    compareExactPositiveDecimals(exactHigh, exactOpen) < 0 ||
    compareExactPositiveDecimals(exactHigh, exactClose) < 0 ||
    compareExactPositiveDecimals(exactHigh, exactLow) < 0 ||
    compareExactPositiveDecimals(exactLow, exactOpen) > 0 ||
    compareExactPositiveDecimals(exactLow, exactClose) > 0 ||
    compareExactPositiveDecimals(exactLow, exactHigh) > 0
  ) {
    addDiagnostic(diagnostics, date, "INVALID_OHLC_ENVELOPE");
    return null;
  }

  const revisionState = row.revision_state ?? "unknown";
  return {
    row,
    date,
    open,
    high,
    low,
    close,
    volume,
    readout: {
      date,
      open: row.open as string,
      high: row.high as string,
      low: row.low as string,
      close: row.close as string,
      volume: row.volume ?? null,
      availabilityState: "present",
      revisionState,
      qualityFlags: [...(row.quality_flags ?? [])],
    },
  };
}

function markerTone(reasonCodes: string[]): ObservatoryKlineMarker["tone"] {
  if (
    reasonCodes.some(
      (reason) =>
        reason.startsWith("INVALID_") ||
        reason === "DUPLICATE_DATE" ||
        reason === "MISSING_DAILY_ROW",
    )
  ) {
    return "error";
  }
  if (reasonCodes.some((reason) => reason !== "REVISION_CHANGED" && reason !== "REVISION_ADDED")) {
    return "warning";
  }
  return "info";
}

function toDiagnostics(diagnostics: DiagnosticMap): ObservatoryKlineDiagnostic[] {
  return [...diagnostics.entries()]
    .map(([date, entry]) => ({
      date,
      reasonCodes: [...entry.reasonCodes].sort(),
      evidenceRefs: [...entry.evidenceRefs].sort(),
      markerPosition: entry.markerPosition,
      omittedReasonCodeCount: entry.omittedReasonCodeCount,
      omittedEvidenceRefCount: entry.omittedEvidenceRefCount,
    }))
    .sort((left, right) => {
      if (left.date === null) return -1;
      if (right.date === null) return 1;
      return left.date.localeCompare(right.date);
    });
}

function invalidModel(
  diagnostics: DiagnosticMap,
  identity: ObservatoryKlineIdentity | null,
  lifecycle: ObservatoryKlineLifecycle | null,
  suppliedRowCount: number,
  invalidRowCount: number,
  spanDays = 0,
): ObservatoryKlineModel {
  const converted = toDiagnostics(diagnostics);
  const fatalReasonCodes = [
    ...new Set(converted.flatMap((diagnostic) => diagnostic.reasonCodes)),
  ].sort();
  return {
    state: "invalid",
    identity,
    lifecycle,
    candles: [],
    volumes: [],
    markers: [],
    dates: [],
    readouts: {},
    diagnostics: converted,
    suppliedRowCount,
    renderedCandleCount: 0,
    invalidRowCount,
    affectedDateCount: new Set(converted.flatMap((item) => (item.date ? [item.date] : []))).size,
    spanDays,
    fatalReasonCodes,
    omittedFatalReasonCodeCount: converted.reduce(
      (total, diagnostic) => total + diagnostic.omittedReasonCodeCount,
      0,
    ),
  };
}

function rejectedPayloadModel(code = "CHART_DATA_REJECTED"): ObservatoryKlineModel {
  const diagnostics: DiagnosticMap = new Map();
  addDiagnostic(diagnostics, null, code);
  return invalidModel(diagnostics, null, null, 0, 0);
}

export function buildObservatoryKlineModel(
  series: ObsSingleSeries,
  activeContext: ObsContext,
  maxDays = OBSERVATORY_KLINE_MAX_DAYS,
  window?: ObservatoryKlineWindow | null,
): ObservatoryKlineModel {
  try {
    if (!isRecord(series) || !isRecord(activeContext)) {
      return rejectedPayloadModel();
    }
    return buildObservatoryKlineModelUnchecked(series, activeContext, maxDays, window);
  } catch {
    return rejectedPayloadModel();
  }
}

function buildObservatoryKlineModelUnchecked(
  series: ObsSingleSeries,
  activeContext: ObsContext,
  maxDays: number,
  window?: ObservatoryKlineWindow | null,
): ObservatoryKlineModel {
  const diagnostics: DiagnosticMap = new Map();
  const rows = series.rows;
  const rawExcludedDates = activeContext.excluded_dates;
  const excludedDates = Array.isArray(rawExcludedDates) ? rawExcludedDates : [];
  const suppliedRowCount = Array.isArray(rows) ? rows.length : 0;
  const identity = buildIdentity(activeContext, diagnostics);
  const lifecycle = buildLifecycle(series, activeContext, diagnostics);
  const windowFromEpoch = window ? parseIsoDate(window.from) : null;
  const windowToEpoch = window ? parseIsoDate(window.to) : null;

  if (!Array.isArray(rows)) {
    addDiagnostic(diagnostics, null, "SERIES_ROWS_UNAVAILABLE");
  }
  if (rawExcludedDates !== undefined && !Array.isArray(rawExcludedDates)) {
    addDiagnostic(diagnostics, null, "EXCLUDED_DATES_UNAVAILABLE");
  }
  if (!contractsMatch(activeContext, series.context)) {
    addDiagnostic(diagnostics, null, "SERIES_CONTRACT_MISMATCH");
  }
  if (
    window &&
    (windowFromEpoch === null || windowToEpoch === null || windowFromEpoch > windowToEpoch)
  ) {
    addDiagnostic(diagnostics, null, "REQUEST_WINDOW_INVALID");
  }
  if (!identity || !lifecycle || !Array.isArray(rows) || diagnostics.has(null)) {
    return invalidModel(diagnostics, identity, lifecycle, suppliedRowCount, suppliedRowCount);
  }

  if (!Number.isInteger(maxDays) || maxDays <= 0) {
    addDiagnostic(diagnostics, null, "CHART_CAPACITY_EXCEEDED");
    return invalidModel(diagnostics, identity, lifecycle, suppliedRowCount, suppliedRowCount);
  }

  const rowDateCounts = new Map<string, number>();
  let minEpoch = Number.POSITIVE_INFINITY;
  let maxEpoch = Number.NEGATIVE_INFINITY;
  let malformedDate = false;
  let provenanceMismatch = false;
  let shapeInvalid = false;
  let windowMismatch = false;

  const recordEpoch = (epoch: number): number => {
    minEpoch = Math.min(minEpoch, epoch);
    maxEpoch = Math.max(maxEpoch, epoch);
    return Math.floor((maxEpoch - minEpoch) / DAY_MS) + 1;
  };

  for (const row of rows) {
    if (
      !isRecord(row) ||
      (row.quality_flags !== undefined && !Array.isArray(row.quality_flags)) ||
      (row.membership !== undefined && !Array.isArray(row.membership))
    ) {
      shapeInvalid = true;
      addDiagnostic(diagnostics, null, "ROW_SHAPE_INVALID");
      continue;
    }
    const epoch = parseIsoDate(row.date);
    if (epoch === null || typeof row.date !== "string") {
      malformedDate = true;
      addDiagnostic(diagnostics, null, "MALFORMED_DATE");
      continue;
    }
    if (
      window &&
      windowFromEpoch !== null &&
      windowToEpoch !== null &&
      (epoch < windowFromEpoch || epoch > windowToEpoch)
    ) {
      windowMismatch = true;
      addDiagnostic(diagnostics, null, "SERIES_WINDOW_MISMATCH");
      continue;
    }
    const spanDays = recordEpoch(epoch);
    if (spanDays > maxDays) {
      addDiagnostic(diagnostics, null, "CHART_CAPACITY_EXCEEDED");
      return invalidModel(
        diagnostics,
        identity,
        lifecycle,
        suppliedRowCount,
        suppliedRowCount,
        spanDays,
      );
    }
    rowDateCounts.set(row.date, (rowDateCounts.get(row.date) ?? 0) + 1);
    if (
      row.provider !== identity.provider ||
      row.instrument !== identity.instrument ||
      row.quote !== identity.quote
    ) {
      provenanceMismatch = true;
      addDiagnostic(diagnostics, row.date, "PROVENANCE_MISMATCH");
    }
  }

  const excludedByDate = new Set<string>();
  for (const excluded of excludedDates) {
    if (!isRecord(excluded)) {
      shapeInvalid = true;
      addDiagnostic(diagnostics, null, "EXCLUSION_SHAPE_INVALID");
      continue;
    }
    const epoch = parseIsoDate(excluded.date);
    if (epoch === null || typeof excluded.date !== "string") {
      malformedDate = true;
      addDiagnostic(diagnostics, null, "MALFORMED_DATE");
      continue;
    }
    if (
      window &&
      windowFromEpoch !== null &&
      windowToEpoch !== null &&
      (epoch < windowFromEpoch || epoch > windowToEpoch)
    ) {
      continue;
    }
    if (
      (excluded.quality_flags !== undefined && !Array.isArray(excluded.quality_flags)) ||
      (excluded.evidence_refs !== undefined && !Array.isArray(excluded.evidence_refs))
    ) {
      shapeInvalid = true;
      addDiagnostic(diagnostics, null, "EXCLUSION_SHAPE_INVALID");
      continue;
    }
    const spanDays = recordEpoch(epoch);
    if (spanDays > maxDays) {
      addDiagnostic(diagnostics, null, "CHART_CAPACITY_EXCEEDED");
      return invalidModel(
        diagnostics,
        identity,
        lifecycle,
        suppliedRowCount,
        suppliedRowCount,
        spanDays,
      );
    }
    excludedByDate.add(excluded.date);
    const reasons = [
      "EXCLUDED_DATE",
      safeReasonCode(excluded.exclusion_reason, "EXCLUSION_REASON_UNAVAILABLE"),
    ];
    for (const flag of excluded.quality_flags ?? []) {
      reasons.push(safeReasonCode(flag, "QUALITY_FLAG_UNAVAILABLE"));
    }
    const evidenceRefs = safeEvidenceRefs(excluded.evidence_refs);
    const position = markerPosition(excluded.marker_position);
    for (const [index, reason] of reasons.entries()) {
      addDiagnostic(
        diagnostics,
        excluded.date,
        reason,
        index === 0 ? evidenceRefs.values : [],
        position,
        index === 0 ? evidenceRefs.omittedCount : 0,
      );
    }
  }

  if (malformedDate || provenanceMismatch || shapeInvalid || windowMismatch) {
    return invalidModel(
      diagnostics,
      identity,
      lifecycle,
      suppliedRowCount,
      provenanceMismatch || shapeInvalid || windowMismatch ? rows.length : 1,
    );
  }
  if (!Number.isFinite(minEpoch) || !Number.isFinite(maxEpoch)) {
    if (rows.length === 0 && excludedByDate.size === 0) {
      return {
        state: "empty",
        identity,
        lifecycle,
        candles: [],
        volumes: [],
        markers: [],
        dates: [],
        readouts: {},
        diagnostics: [],
        suppliedRowCount: 0,
        renderedCandleCount: 0,
        invalidRowCount: 0,
        affectedDateCount: 0,
        spanDays: 0,
        fatalReasonCodes: [],
        omittedFatalReasonCodeCount: 0,
      };
    }
    addDiagnostic(diagnostics, null, "NO_VALID_DATES");
    return invalidModel(diagnostics, identity, lifecycle, suppliedRowCount, suppliedRowCount);
  }

  const spanDays = Math.floor((maxEpoch - minEpoch) / DAY_MS) + 1;

  const rowByDate = new Map<string, ObsSeriesRow>();
  for (const row of rows) {
    const date = row.date as string;
    if ((rowDateCounts.get(date) ?? 0) > 1) {
      addDiagnostic(diagnostics, date, "DUPLICATE_DATE");
      continue;
    }
    rowByDate.set(date, row);
  }

  const candles: ObservatoryCandleDatum[] = [];
  const volumes: ObservatoryVolumeDatum[] = [];
  const dates: string[] = [];
  const readouts: Record<string, ObservatoryKlineReadout> = {};
  let invalidRowCount = 0;
  let renderedCandleCount = 0;
  let degraded = false;

  for (let index = 0; index < spanDays; index += 1) {
    const date = new Date(minEpoch + index * DAY_MS).toISOString().slice(0, 10);
    dates.push(date);
    const excluded = excludedByDate.has(date);
    const duplicate = (rowDateCounts.get(date) ?? 0) > 1;
    const row = rowByDate.get(date);

    if (excluded) {
      candles.push({ time: date });
      volumes.push({ time: date });
      degraded = true;
      if (row) invalidRowCount += 1;
      continue;
    }
    if (duplicate) {
      candles.push({ time: date });
      volumes.push({ time: date });
      invalidRowCount += rowDateCounts.get(date) ?? 0;
      degraded = true;
      continue;
    }
    if (!row) {
      addDiagnostic(diagnostics, date, "MISSING_DAILY_ROW");
      candles.push({ time: date });
      volumes.push({ time: date });
      degraded = true;
      continue;
    }

    const availability = row.availability_state ?? "unknown";
    if (availability !== "present") {
      addDiagnostic(diagnostics, date, `AVAILABILITY_${safeReasonCode(availability, "UNKNOWN")}`);
      candles.push({ time: date });
      volumes.push({ time: date });
      invalidRowCount += 1;
      degraded = true;
      continue;
    }

    const parsed = parsePresentRow(row, date, diagnostics);
    if (!parsed) {
      candles.push({ time: date });
      volumes.push({ time: date });
      invalidRowCount += 1;
      degraded = true;
      continue;
    }

    candles.push({
      time: date,
      open: parsed.open,
      high: parsed.high,
      low: parsed.low,
      close: parsed.close,
    });
    volumes.push(
      parsed.volume === null
        ? { time: date }
        : {
            time: date,
            value: parsed.volume,
            color:
              parsed.close >= parsed.open ? "rgba(38, 166, 154, 0.45)" : "rgba(239, 83, 80, 0.45)",
          },
    );
    readouts[date] = parsed.readout;
    renderedCandleCount += 1;

    for (const flag of row.quality_flags ?? []) {
      addDiagnostic(diagnostics, date, safeReasonCode(flag, "QUALITY_FLAG_UNAVAILABLE"));
      degraded = true;
    }
    if (row.revision_state === "changed" || row.revision_state === "added") {
      addDiagnostic(diagnostics, date, `REVISION_${row.revision_state.toUpperCase()}`);
    }
  }

  if (renderedCandleCount === 0) {
    addDiagnostic(diagnostics, null, "NO_VALID_CANDLES");
    return invalidModel(
      diagnostics,
      identity,
      lifecycle,
      suppliedRowCount,
      invalidRowCount,
      spanDays,
    );
  }

  const convertedDiagnostics = toDiagnostics(diagnostics);
  const markers = convertedDiagnostics.flatMap((diagnostic) =>
    diagnostic.date
      ? [
          {
            time: diagnostic.date,
            reasonCodes: diagnostic.reasonCodes,
            evidenceRefs: diagnostic.evidenceRefs,
            position: diagnostic.markerPosition,
            tone: markerTone(diagnostic.reasonCodes),
          } satisfies ObservatoryKlineMarker,
        ]
      : [],
  );
  const affectedDateCount = new Set(markers.map((marker) => marker.time)).size;

  return {
    state: degraded ? "partial-invalid" : "ready",
    identity,
    lifecycle,
    candles,
    volumes,
    markers,
    dates,
    readouts,
    diagnostics: convertedDiagnostics,
    suppliedRowCount,
    renderedCandleCount,
    invalidRowCount,
    affectedDateCount,
    spanDays,
    fatalReasonCodes: [],
    omittedFatalReasonCodeCount: 0,
  };
}

type ExactAggregateDecimal = {
  coefficient: bigint;
  scale: number;
};

function parseExactAggregateDecimal(value: string): ExactAggregateDecimal | null {
  if (!STRICT_DECIMAL.test(value)) return null;
  const negative = value.startsWith("-");
  const unsigned = value.replace(/^[+-]/, "");
  const [integer = "0", fraction = ""] = unsigned.split(".", 2);
  const digits = `${integer}${fraction}`.replace(/^0+(?=\d)/, "") || "0";
  if (digits.length > OBSERVATORY_AGGREGATE_DECIMAL_DIGIT_LIMIT) return null;
  let coefficient = BigInt(digits);
  let scale = fraction.length;
  while (scale > 0 && coefficient % 10n === 0n) {
    coefficient /= 10n;
    scale -= 1;
  }
  if (negative) coefficient = -coefficient;
  return { coefficient, scale };
}

function alignExactAggregateDecimals(
  left: ExactAggregateDecimal,
  right: ExactAggregateDecimal,
): [bigint, bigint, number] {
  const scale = Math.max(left.scale, right.scale);
  return [
    left.coefficient * 10n ** BigInt(scale - left.scale),
    right.coefficient * 10n ** BigInt(scale - right.scale),
    scale,
  ];
}

function compareExactAggregateDecimals(
  left: ExactAggregateDecimal,
  right: ExactAggregateDecimal,
): number {
  const [leftCoefficient, rightCoefficient] = alignExactAggregateDecimals(left, right);
  return leftCoefficient < rightCoefficient ? -1 : leftCoefficient > rightCoefficient ? 1 : 0;
}

function addExactAggregateDecimals(
  left: ExactAggregateDecimal,
  right: ExactAggregateDecimal,
): ExactAggregateDecimal | null {
  const [leftCoefficient, rightCoefficient, scale] = alignExactAggregateDecimals(left, right);
  const coefficient = leftCoefficient + rightCoefficient;
  const digits =
    coefficient < 0n ? (-coefficient).toString().length : coefficient.toString().length;
  if (digits > OBSERVATORY_AGGREGATE_DECIMAL_DIGIT_LIMIT) return null;
  return { coefficient, scale };
}

function formatExactAggregateDecimal(value: ExactAggregateDecimal): string {
  const negative = value.coefficient < 0n;
  const digits = (negative ? -value.coefficient : value.coefficient).toString();
  if (value.scale === 0) return `${negative ? "-" : ""}${digits}`;
  const padded = digits.padStart(value.scale + 1, "0");
  const integer = padded.slice(0, -value.scale) || "0";
  const fraction = padded.slice(-value.scale).replace(/0+$/, "");
  return `${negative ? "-" : ""}${integer}${fraction ? `.${fraction}` : ""}`;
}

function aggregateBucketStart(date: string, timeframe: ObservatoryTimeframe): string {
  if (timeframe === "1D") return date;
  if (timeframe === "1M") return `${date.slice(0, 7)}-01`;
  if (timeframe === "1Y") return `${date.slice(0, 4)}-01-01`;
  const epoch = parseIsoDate(date);
  if (epoch === null) return date;
  const weekday = new Date(epoch).getUTCDay();
  const mondayOffset = (weekday + 6) % 7;
  return new Date(epoch - mondayOffset * DAY_MS).toISOString().slice(0, 10);
}

function aggregateBucketEnd(start: string, timeframe: ObservatoryTimeframe): string {
  if (timeframe === "1D") return start;
  const epoch = parseIsoDate(start);
  if (epoch === null) return start;
  const next = new Date(epoch);
  if (timeframe === "1W") next.setUTCDate(next.getUTCDate() + 7);
  if (timeframe === "1M") next.setUTCMonth(next.getUTCMonth() + 1);
  if (timeframe === "1Y") next.setUTCFullYear(next.getUTCFullYear() + 1);
  return new Date(next.getTime() - DAY_MS).toISOString().slice(0, 10);
}

type AggregateBucket = {
  start: string;
  end: string;
  dates: string[];
  validDates: string[];
  readouts: ObservatoryKlineReadout[];
  reasons: Set<string>;
  omittedReasonCodeCount: number;
  evidenceRefs: Set<string>;
  omittedEvidenceRefCount: number;
  partialVolume: boolean;
  overflow: boolean;
};

function boundedSetAdd(target: Set<string>, values: string[], limit: number): number {
  let omitted = 0;
  for (const value of values) {
    if (target.has(value)) continue;
    if (target.size < limit) target.add(value);
    else omitted += 1;
  }
  return omitted;
}

function aggregateBucketReadout(bucket: AggregateBucket): {
  readout: ObservatoryKlineReadout;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
} | null {
  const first = bucket.readouts[0];
  const last = bucket.readouts[bucket.readouts.length - 1];
  if (!first || !last) return null;
  const open = parseExactAggregateDecimal(first.open);
  const high = bucket.readouts.reduce<ExactAggregateDecimal | null>((current, readout) => {
    const candidate = parseExactAggregateDecimal(readout.high);
    if (!candidate) {
      bucket.overflow = true;
      return null;
    }
    return current === null || compareExactAggregateDecimals(candidate, current) > 0
      ? candidate
      : current;
  }, null);
  const low = bucket.readouts.reduce<ExactAggregateDecimal | null>((current, readout) => {
    const candidate = parseExactAggregateDecimal(readout.low);
    if (!candidate) return null;
    return current === null || compareExactAggregateDecimals(candidate, current) < 0
      ? candidate
      : current;
  }, null);
  const close = parseExactAggregateDecimal(last.close);
  if (!open || !high || !low || !close) {
    bucket.overflow = true;
    return null;
  }
  let exactVolume: ExactAggregateDecimal | null = null;
  for (const readout of bucket.readouts) {
    if (readout.volume === null) {
      bucket.partialVolume = true;
      continue;
    }
    const volume = parseExactAggregateDecimal(readout.volume);
    if (!volume) {
      bucket.overflow = true;
      return null;
    }
    exactVolume = exactVolume === null ? volume : addExactAggregateDecimals(exactVolume, volume);
    if (exactVolume === null) {
      bucket.overflow = true;
      return null;
    }
  }
  const openString = formatExactAggregateDecimal(open);
  const highString = formatExactAggregateDecimal(high);
  const lowString = formatExactAggregateDecimal(low);
  const closeString = formatExactAggregateDecimal(close);
  const volumeString =
    bucket.partialVolume || exactVolume === null ? null : formatExactAggregateDecimal(exactVolume);
  const readout: ObservatoryKlineReadout = {
    date: last.date,
    open: openString,
    high: highString,
    low: lowString,
    close: closeString,
    volume: volumeString,
    availabilityState: "present",
    revisionState: last.revisionState,
    qualityFlags: [...new Set(bucket.readouts.flatMap((item) => item.qualityFlags))].slice(0, 16),
  };
  const openGeometry = parseDecimal(openString, false);
  const highGeometry = parseDecimal(highString, false);
  const lowGeometry = parseDecimal(lowString, false);
  const closeGeometry = parseDecimal(closeString, false);
  const volumeGeometry = volumeString === null ? null : parseDecimal(volumeString, true);
  if (
    openGeometry === null ||
    highGeometry === null ||
    lowGeometry === null ||
    closeGeometry === null
  ) {
    bucket.overflow = true;
    return null;
  }
  return {
    readout,
    open: openGeometry,
    high: highGeometry,
    low: lowGeometry,
    close: closeGeometry,
    volume: volumeGeometry,
  };
}

export function aggregateObservatoryKlineModel(
  model: ObservatoryKlineModel,
  timeframe: ObservatoryTimeframe,
): ObservatoryKlineModel {
  const canonicalDates = Object.fromEntries(
    model.dates.map((date) => [date, model.readouts[date]?.date ?? null]),
  );
  if (timeframe === "1D" || model.state === "invalid" || model.state === "empty") {
    return { ...model, timeframe, canonicalDates };
  }

  const bucketMap = new Map<string, AggregateBucket>();
  const diagnosticsByDate = new Map(
    model.diagnostics
      .filter(
        (diagnostic): diagnostic is ObservatoryKlineDiagnostic & { date: string } =>
          diagnostic.date !== null,
      )
      .map((diagnostic) => [diagnostic.date, diagnostic]),
  );
  for (const date of model.dates) {
    const start = aggregateBucketStart(date, timeframe);
    let bucket = bucketMap.get(start);
    if (!bucket) {
      bucket = {
        start,
        end: aggregateBucketEnd(start, timeframe),
        dates: [],
        validDates: [],
        readouts: [],
        reasons: new Set<string>(),
        omittedReasonCodeCount: 0,
        evidenceRefs: new Set<string>(),
        omittedEvidenceRefCount: 0,
        partialVolume: false,
        overflow: false,
      };
      bucketMap.set(start, bucket);
    }
    bucket.dates.push(date);
    const diagnostic = diagnosticsByDate.get(date);
    if (diagnostic) {
      bucket.omittedReasonCodeCount += boundedSetAdd(
        bucket.reasons,
        diagnostic.reasonCodes,
        OBSERVATORY_AGGREGATE_REASON_LIMIT,
      );
      bucket.omittedEvidenceRefCount += boundedSetAdd(
        bucket.evidenceRefs,
        diagnostic.evidenceRefs,
        OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT,
      );
      bucket.omittedEvidenceRefCount += diagnostic.omittedEvidenceRefCount;
    }
    const readout = model.readouts[date];
    if (readout) {
      bucket.validDates.push(date);
      bucket.readouts.push(readout);
    }
  }

  if (bucketMap.size > OBSERVATORY_AGGREGATE_METADATA_LIMIT) {
    return {
      ...model,
      state: "invalid",
      timeframe,
      canonicalDates,
      candles: [],
      volumes: [],
      markers: [],
      dates: [],
      readouts: {},
      bucketMetadata: {},
      fatalReasonCodes: ["CHART_CAPACITY_EXCEEDED"],
      omittedFatalReasonCodeCount: 0,
      renderedCandleCount: 0,
    };
  }

  const dates = [...bucketMap.keys()].sort();
  const candles: ObservatoryCandleDatum[] = [];
  const volumes: ObservatoryVolumeDatum[] = [];
  const readouts: Record<string, ObservatoryKlineReadout> = {};
  const bucketMetadata: Record<string, ObservatoryKlineBucketMetadata> = {};
  const diagnostics: ObservatoryKlineDiagnostic[] = [];
  let renderedCandleCount = 0;
  let invalidRowCount = model.invalidRowCount;
  let partial = model.state === "partial-invalid";
  let aggregateOverflow = false;

  for (const date of dates) {
    const bucket = bucketMap.get(date) as AggregateBucket;
    const aggregated = aggregateBucketReadout(bucket);
    aggregateOverflow ||= bucket.overflow;
    const partialBucket = bucket.validDates.length < bucket.dates.length || bucket.partialVolume;
    const reasons = [...bucket.reasons];
    if (partialBucket) reasons.push("PARTIAL_TIMEFRAME_BUCKET");
    if (bucket.partialVolume) reasons.push("MISSING_VOLUME");
    const reasonCodes = [...new Set(reasons)].sort();
    const evidenceRefs = [...bucket.evidenceRefs].sort();
    const metadata: ObservatoryKlineBucketMetadata = {
      start: bucket.start,
      end: bucket.end,
      canonicalDate: bucket.validDates.at(-1) ?? null,
      coveredDateCount: bucket.dates.length,
      validDateCount: bucket.validDates.length,
      partial: partialBucket,
      reasonCodes,
      evidenceRefs,
      omittedEvidenceRefCount: bucket.omittedEvidenceRefCount,
      omittedReasonCodeCount: bucket.omittedReasonCodeCount,
      sourceInterval: model.identity?.interval ?? "1Dutc",
      snapshotId: "context-bound",
      channel: model.lifecycle?.channel ?? "unknown",
    };
    bucketMetadata[date] = metadata;
    if (!aggregated) {
      candles.push({ time: date });
      volumes.push({ time: date });
      invalidRowCount += 1;
      partial = true;
    } else {
      candles.push({
        time: date,
        open: aggregated.open,
        high: aggregated.high,
        low: aggregated.low,
        close: aggregated.close,
      });
      volumes.push(
        aggregated.volume === null
          ? { time: date }
          : {
              time: date,
              value: aggregated.volume,
              color:
                aggregated.close >= aggregated.open
                  ? "rgba(38, 166, 154, 0.45)"
                  : "rgba(239, 83, 80, 0.45)",
            },
      );
      readouts[date] = aggregated.readout;
      renderedCandleCount += 1;
      invalidRowCount += Math.max(0, bucket.dates.length - bucket.validDates.length);
    }
    if (partialBucket || !aggregated) {
      partial = true;
      diagnostics.push({
        date,
        reasonCodes: reasonCodes.length ? reasonCodes : ["EMPTY_TIMEFRAME_BUCKET"],
        evidenceRefs,
        markerPosition: "above",
        omittedReasonCodeCount: 0,
        omittedEvidenceRefCount: bucket.omittedEvidenceRefCount,
      });
    }
  }

  const markers = diagnostics.map((diagnostic) => ({
    time: diagnostic.date as string,
    reasonCodes: diagnostic.reasonCodes,
    evidenceRefs: diagnostic.evidenceRefs,
    position: diagnostic.markerPosition,
    tone: markerTone(diagnostic.reasonCodes),
  }));
  if (aggregateOverflow) {
    return {
      ...model,
      state: "invalid",
      timeframe,
      candles: [],
      volumes: [],
      markers: [],
      dates: [],
      readouts: {},
      diagnostics,
      bucketMetadata,
      renderedCandleCount: 0,
      fatalReasonCodes: ["AGGREGATE_DECIMAL_OVERFLOW"],
      omittedFatalReasonCodeCount: 0,
    };
  }
  return {
    ...model,
    state: partial ? "partial-invalid" : "ready",
    timeframe,
    candles,
    volumes,
    markers,
    dates,
    readouts,
    diagnostics,
    bucketMetadata,
    canonicalDates: Object.fromEntries(
      dates.map((date) => [date, bucketMetadata[date]?.canonicalDate ?? null]),
    ),
    renderedCandleCount,
    invalidRowCount,
    affectedDateCount: diagnostics.length,
    fatalReasonCodes: [],
    omittedFatalReasonCodeCount: 0,
  };
}
