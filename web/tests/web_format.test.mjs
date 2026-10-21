// Pure-function tests for the site's formatting, filtering and glossary.
// Run: node --test web/tests/web_format.test.mjs   (Node 22.18+ strips types itself)
// tests/test_web_node.py runs this file from pytest, skipping when Node is absent.

import assert from "node:assert/strict";
import { test } from "node:test";

import { filterCorridors, paginate, stateOptions } from "../lib/corridorFilter.ts";
import { interval, minutes, num, pct, sci } from "../lib/format.ts";
import { GLOSSARY, REQUIRED_TERMS } from "../lib/glossary.ts";

test("numbers group internationally, never in lakhs", () => {
  assert.equal(num(56353613), "56,353,613");
  assert.equal(num(144867), "144,867");
  assert.equal(num(26369), "26,369");
  assert.equal(num(1234.5, 1), "1,234.5");
  assert.equal(num(null), "—");
  assert.ok(!num(56353613).includes("5,63"));
});

test("q-values never print a bare zero", () => {
  assert.equal(sci(0), "< 1e-6");
  assert.equal(sci(1e-9), "< 1e-6");
  assert.equal(sci(0.0123), "0.0123");
  assert.equal(sci(2.5e-5), "2.5e-5");
  assert.equal(sci(null), "—");
});

test("percent, interval and minutes", () => {
  assert.equal(pct(0.8506, 1), "85.1%");
  assert.equal(interval(0.8506, 0.9343), "85.1%–93.4%");
  assert.equal(interval(null, 0.9), "—");
  assert.equal(minutes(107.09), "1h 47m");
});

const place = (city, state) => ({ code: `C-${city}`, city, state, facility: null, lat: 1, lon: 1 });
const row = (id, src, dst, direction, sig = true) => ({
  id,
  route: `${src.city} → ${dst.city}`,
  src,
  dst,
  direction,
  is_significant: sig,
});
const rows = [
  row("a", place("Pune", "Maharashtra"), place("Mumbai", "Maharashtra"), "worse"),
  row("b", place("Kanpur", "Uttar Pradesh"), place("Kanpur", "Uttar Pradesh"), "worse"),
  row("c", place("Hubli", "Karnataka"), place("Pune", "Maharashtra"), "better"),
  row("d", place("Goa", "Goa"), place("Pune", "Maharashtra"), "worse", false),
];

test("filter: significant only, direction, state, search", () => {
  assert.equal(filterCorridors(rows, { query: "", direction: "both", state: "" }).length, 3);
  assert.deepEqual(
    filterCorridors(rows, { query: "", direction: "worse", state: "" }).map((c) => c.id),
    ["a", "b"]
  );
  assert.deepEqual(
    filterCorridors(rows, { query: "", direction: "both", state: "Karnataka" }).map((c) => c.id),
    ["c"]
  );
  assert.deepEqual(
    filterCorridors(rows, { query: "kanpur", direction: "both", state: "" }).map((c) => c.id),
    ["b"]
  );
  assert.deepEqual(stateOptions(rows), ["Karnataka", "Maharashtra", "Uttar Pradesh"]);
});

test("paginate clamps the page and reports the visible range", () => {
  const items = Array.from({ length: 60 }, (_, i) => i);
  const p1 = paginate(items, 1, 25);
  assert.deepEqual([p1.from, p1.to, p1.pages, p1.rows.length], [1, 25, 3, 25]);
  const p3 = paginate(items, 99, 25);
  assert.deepEqual([p3.page, p3.from, p3.to], [3, 51, 60]);
  const empty = paginate([], 5, 25);
  assert.deepEqual([empty.page, empty.from, empty.to, empty.pages], [1, 0, 0, 1]);
});

test("glossary covers every term the site relies on", () => {
  const have = GLOSSARY.map((g) => g.term.toLowerCase());
  for (const required of REQUIRED_TERMS) {
    assert.ok(
      have.some((t) => t.includes(required.toLowerCase())),
      `glossary is missing "${required}"`
    );
  }
  for (const g of GLOSSARY) assert.ok(g.definition.length > 20, g.term);
  assert.equal(new Set(have).size, have.length, "duplicate glossary term");
});
