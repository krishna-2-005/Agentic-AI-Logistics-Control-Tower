/** Number and label formatting, in one place so the whole site reads alike. */

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", {
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

/** q-values run to 1e-7; exponent notation is the honest rendering. */
export function sci(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value === 0) return "0";
  if (value >= 0.001) return value.toFixed(4);
  return value.toExponential(1);
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
