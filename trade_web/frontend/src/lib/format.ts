export function humanizeEnum(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return value
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatPercent(value?: number | null, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatScore(value?: number | null, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function formatCompactNumber(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDate(value?: string | null, locale = "en-US") {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(value?: string | null, locale = "en-US") {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatAction(action?: string | null) {
  if (!action) {
    return "Unknown";
  }
  return action.replace(/_/g, " ");
}

export function formatConfidence(value?: string | number | null) {
  if (typeof value === "number") {
    return formatPercent(value, 0);
  }
  if (!value) {
    return "—";
  }
  return humanizeEnum(String(value));
}

export function shortText(value?: string | null, limit = 120) {
  if (!value) {
    return "";
  }
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

export function labelizeDataset(value?: string | null) {
  if (!value) {
    return "Unknown dataset";
  }
  return value.replace(/^tushare_/, "").replace(/_/g, " ");
}
