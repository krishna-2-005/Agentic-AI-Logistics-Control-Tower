/**
 * The corridor table's filtering and paging, as pure functions.
 *
 * Kept free of React and of any import that is not a type, so the Node test in
 * `tests/web_format.test.mjs` can run them directly.
 */

import type { Corridor } from "./types";

export type Direction = "worse" | "better" | "both";

export interface Filter {
  query: string;
  direction: Direction;
  /** "" means every state. */
  state: string;
}

export const PAGE_SIZE = 25;

/** Everything a visitor might type that identifies a corridor. */
function haystack(c: Corridor): string {
  return [
    c.route,
    c.src.city,
    c.dst.city,
    c.src.facility,
    c.dst.facility,
    c.src.state,
    c.dst.state,
    c.src.code,
    c.dst.code,
    c.id,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function filterCorridors(rows: Corridor[], f: Filter): Corridor[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter((c) => {
    if (!c.is_significant) return false;
    if (f.direction !== "both" && c.direction !== f.direction) return false;
    if (f.state && c.src.state !== f.state && c.dst.state !== f.state) return false;
    return !q || haystack(c).includes(q);
  });
}

/** States that appear on either end of a significant corridor, sorted. */
export function stateOptions(rows: Corridor[]): string[] {
  const seen = new Set<string>();
  for (const c of rows) {
    if (!c.is_significant) continue;
    if (c.src.state) seen.add(c.src.state);
    if (c.dst.state) seen.add(c.dst.state);
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export interface PageInfo<T> {
  rows: T[];
  page: number;
  pages: number;
  from: number;
  to: number;
  total: number;
}

/** A 1-based page, clamped into range so a shrinking filter never strands the reader. */
export function paginate<T>(rows: T[], page: number, size = PAGE_SIZE): PageInfo<T> {
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const p = Math.min(Math.max(1, page), pages);
  const start = (p - 1) * size;
  const slice = rows.slice(start, start + size);
  return {
    rows: slice,
    page: p,
    pages,
    from: total === 0 ? 0 : start + 1,
    to: start + slice.length,
    total,
  };
}
