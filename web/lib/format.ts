/**
 * Number and label formatting, in one place so the whole site reads alike.
 *
 * Pure functions with no imports, so `tests/web_format.test.mjs` can run them
 * directly under Node.
 */

/** The one locale for every number: international grouping, 56,353,613 not 5,63,53,613. */
export const NUMBER_LOCALE = "en-US";

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(NUMBER_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** 613 -> "10h 13m". Minutes alone stop being legible somewhere around 200. */
export function minutes(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) < 60) return `${Math.round(value)} min`;
  const h = Math.floor(Math.abs(value) / 60);
  const m = Math.round(Math.abs(value) % 60);
  const sign = value < 0 ? "−" : "";
  return m === 0 ? `${sign}${h}h` : `${sign}${h}h ${m}m`;
}

export function ratio(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}×`;
}

/**
 * A q-value that never prints a bare "0". Below one in a million the honest
 * statement is a bound, because a float underflow or a rounded export is not zero.
 */
export function sci(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 1e-6) return "< 1e-6";
  if (value >= 0.001) return value.toFixed(4);
  return value.toExponential(1);
}

/** A Wilson interval as "85.1%–93.4%". */
export function interval(
  low: number | null | undefined,
  high: number | null | undefined,
  digits = 1
): string {
  if (low === null || low === undefined || high === null || high === undefined) return "—";
  return `${(low * 100).toFixed(digits)}%–${(high * 100).toFixed(digits)}%`;
}

/** "IND208012AAA>IND209304AAA" -> "Kanpur → Kanpur", falling back to codes. */
export function routeLabel(
  src: { city: string | null; code: string },
  dst: { city: string | null; code: string }
): string {
  return `${src.city ?? src.code} → ${dst.city ?? dst.code}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
