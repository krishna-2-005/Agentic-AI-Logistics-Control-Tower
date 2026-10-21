"use client";

import { useEffect, useMemo, useState } from "react";

import { Chart } from "@/components/Chart";
import { Card, Notice, Pill, TableShell, Td, Th } from "@/components/ui";
import {
  filterCorridors,
  paginate,
  stateOptions,
  type Direction,
} from "@/lib/corridorFilter";
import { cx, minutes, num, ratio, sci } from "@/lib/format";
import type { Corridor } from "@/lib/types";

type SortKey = "excess_ratio" | "n_legs" | "median_gap_min" | "q_value" | "eb_rank";

/** What each column means, in the words a first-time visitor needs. */
const DEFINITIONS: Record<string, string> = {
  overrun:
    "How much more this corridor overruns its OSRM estimate than the network typically does. 1.0x is exactly as much; above is worse.",
  legs: "How many journeys on this corridor the numbers rest on. Few legs, a shakier result.",
  late: "The median number of minutes a leg took beyond its OSRM estimate.",
  q: "The false-discovery-adjusted p-value (Benjamini-Hochberg). Below 0.05 means significant at a 5% false discovery rate; values under one in a million print as < 1e-6.",
  robust:
    "Whether the corridor is still significant when legs that share a trip, a vehicle or a day are treated as dependent, not independent.",
  eb: "Rank after empirical-Bayes shrinkage, which pulls small-sample extremes toward the network average. 1 is the worst.",
};

function ColumnHelp({ text, align }: { text: string; align: "left" | "right" }) {
  return (
    <span className="group/tip relative ml-1 inline-block align-middle">
      <span
        tabIndex={0}
        role="img"
        aria-label={text}
        className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-[var(--ink-faint)] text-[10px] font-semibold normal-case text-[var(--ink-muted)]"
      >
        ?
      </span>
      <span
        role="tooltip"
        className={cx(
          "pointer-events-none invisible absolute top-full z-30 mt-1 w-56 rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] p-2.5 text-left text-[11px] font-normal normal-case leading-snug tracking-normal text-[var(--ink)] opacity-0 shadow-xl shadow-black/30",
          "group-hover/tip:visible group-hover/tip:opacity-100 group-focus-within/tip:visible group-focus-within/tip:opacity-100",
          align === "right" ? "right-0" : "left-0"
        )}
      >
        {text}
      </span>
    </span>
  );
}

function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex rounded-lg border border-[var(--line)] p-0.5"
    >
      {options.map(([v, text]) => (
        <button
          key={String(v)}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={cx(
            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
            value === v
              ? "bg-[var(--accent)] text-white shadow-sm"
              : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function CorridorTable({
  ten,
  thirty,
  sharedTop20,
}: {
  ten: Corridor[];
  thirty: Corridor[];
  sharedTop20: number;
}) {
  const [floor, setFloor] = useState<10 | 30>(10);
  const [query, setQuery] = useState("");
  const [direction, setDirection] = useState<Direction>("worse");
  const [state, setState] = useState("");
  const [sort, setSort] = useState<SortKey>("excess_ratio");
  const [asc, setAsc] = useState(false);
  const [page, setPage] = useState(1);

  const source = floor === 10 ? ten : thirty;
  const states = useMemo(() => stateOptions(source), [source]);
  // Optional columns exist only when the export found the B3 / B4 files.
  const hasRobust = source.some((c) => c.robust !== undefined);
  const hasEb = source.some((c) => c.eb_rank !== undefined);

  const rows = useMemo(() => {
    const filtered = filterCorridors(source, { query, direction, state });
    return filtered.sort((a, b) => {
      const av = (a[sort] ?? Number.POSITIVE_INFINITY) as number;
      const bv = (b[sort] ?? Number.POSITIVE_INFINITY) as number;
      return asc ? av - bv : bv - av;
    });
  }, [source, query, direction, state, sort, asc]);

  // A new filter starts from the first page.
  useEffect(() => setPage(1), [query, direction, state, floor, sort, asc]);
  // A state that does not exist at the other floor must not silently empty the table.
  useEffect(() => {
    if (state && !states.includes(state)) setState("");
  }, [states, state]);

  const view = paginate(rows, page);

  function header(
    key: SortKey,
    label: string,
    help: string,
    align: "left" | "right" = "right"
  ) {
    const active = sort === key;
    return (
      <Th
        align={align}
        aria-sort={active ? (asc ? "ascending" : "descending") : "none"}
      >
        <button
          type="button"
          onClick={() => {
            if (active) setAsc((v) => !v);
            else {
              setSort(key);
              setAsc(key === "eb_rank");
            }
          }}
          className={cx(
            "inline-flex items-center gap-1 transition-colors hover:text-[var(--ink)]",
            active && "text-[var(--ink)]"
          )}
        >
          {label}
          <span aria-hidden className={cx("text-[9px]", !active && "opacity-30")}>
            {active && asc ? "▲" : "▼"}
          </span>
        </button>
        <ColumnHelp text={help} align={align} />
      </Th>
    );
  }

  return (
    <>
      {/* ── controls ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented
          label="Support floor"
          value={floor}
          options={[
            [10, "10-leg floor"],
            [30, "30-leg floor"],
          ] as const}
          onChange={setFloor}
        />
        <Segmented
          label="Direction"
          value={direction}
          options={[
            ["worse", "Slower"],
            ["better", "Faster"],
            ["both", "Both"],
          ] as const}
          onChange={setDirection}
        />

        <label className="sr-only" htmlFor="corridor-search">
          Search corridors by city, state, facility or code
        </label>
        <input
          id="corridor-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a city, facility or code…"
          className="min-w-[12rem] flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-1.5 text-sm placeholder:text-[var(--ink-faint)]"
        />

        <label className="sr-only" htmlFor="corridor-state">
          Filter by state
        </label>
        <select
          id="corridor-state"
          value={state}
          onChange={(e) => setState(e.target.value)}
          className="rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-1.5 text-sm"
        >
          <option value="">All states</option>
          {states.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <Pill>{num(rows.length)} corridors</Pill>
      </div>

      {floor === 30 && (
        <Notice tone="warn" title="This is a different network" className="mb-4">
          At the 30-leg floor only {num(thirty.length)} corridors clear the bar,
          covering 18.9% of legs instead of 78.6%. Its top-20 shares{" "}
          {sharedTop20 === 0 ? "no corridor" : `${sharedTop20} corridors`} with
          the 10-leg list. Both tables are real; they answer different questions.
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <div className="min-w-0">
          <TableShell maxHeight="38rem">
            <thead>
              <tr>
                <Th align="left">Corridor</Th>
                {header("excess_ratio", "Overrun", DEFINITIONS.overrun)}
                {header("n_legs", "Legs", DEFINITIONS.legs)}
                {header("median_gap_min", "Typically late", DEFINITIONS.late)}
                {header("q_value", "q", DEFINITIONS.q)}
                {hasRobust && (
                  <Th align="right">
                    Robust
                    <ColumnHelp text={DEFINITIONS.robust} align="right" />
                  </Th>
                )}
                {hasEb && header("eb_rank", "EB rank", DEFINITIONS.eb)}
              </tr>
            </thead>
            <tbody>
              {view.rows.map((c) => (
                <tr
                  key={c.id}
                  className="transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <Td>
                    <div className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className="h-6 w-0.5 shrink-0 rounded-full"
                        style={{ background: c.severity.color }}
                      />
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium">
                          {c.route}
                        </p>
                        <p className="truncate text-[11px] text-[var(--ink-faint)]">
                          {c.src.state ?? "—"}
                          {c.intra_city && <> · intra-city</>}
                        </p>
                      </div>
                    </div>
                  </Td>
                  <Td align="right" mono>
                    <span
                      style={{ color: c.severity.color }}
                      className="font-semibold"
                    >
                      {ratio(c.excess_ratio)}
                    </span>
                  </Td>
                  <Td align="right" mono>
                    {num(c.n_legs)}
                  </Td>
                  <Td align="right" mono>
                    {minutes(c.median_gap_min)}
                  </Td>
                  <Td align="right" mono className="text-[var(--ink-faint)]">
                    {sci(c.q_value)}
                  </Td>
                  {hasRobust && (
                    <Td align="right">
                      {c.robust === undefined ? "—" : c.robust ? "yes" : "no"}
                    </Td>
                  )}
                  {hasEb && (
                    <Td align="right" mono>
                      {c.eb_rank === undefined ? "—" : num(c.eb_rank)}
                    </Td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <Td className="py-8 text-center text-[var(--ink-muted)]">
                    Nothing matches those filters.
                  </Td>
                </tr>
              )}
            </tbody>
          </TableShell>

          <nav
            aria-label="Corridor pages"
            className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--ink-muted)]"
          >
            <span className="tabular">
              {view.total === 0
                ? "No corridors"
                : `Showing ${num(view.from)}–${num(view.to)} of ${num(view.total)}`}
            </span>
            <span className="flex items-center gap-2">
              <button
                type="button"
                disabled={view.page <= 1}
                onClick={() => setPage(view.page - 1)}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 transition-colors enabled:hover:border-[var(--ink-faint)] enabled:hover:text-[var(--ink)] disabled:opacity-40"
              >
                Previous
              </button>
              <span className="tabular">
                Page {num(view.page)} of {num(view.pages)}
              </span>
              <button
                type="button"
                disabled={view.page >= view.pages}
                onClick={() => setPage(view.page + 1)}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 transition-colors enabled:hover:border-[var(--ink-faint)] enabled:hover:text-[var(--ink)] disabled:opacity-40"
              >
                Next
              </button>
            </span>
          </nav>
        </div>

        {/* ── effect size against support ────────────────────────────── */}
        <Card>
          <p className="text-sm font-medium">Effect size against evidence</p>
          <p className="mb-3 mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">
            Every significant corridor in the current filter, plotted by how many
            legs it rests on. The extreme overruns sit on the left — they are real
            findings and they are also the ones most likely to be a lucky sample.
          </p>
          <Chart
            height={330}
            option={(t) => ({
              grid: { left: 46, right: 16, top: 14, bottom: 42 },
              xAxis: {
                type: "log",
                name: "legs observed",
                nameLocation: "middle",
                nameGap: 26,
                nameTextStyle: { color: t.muted, fontSize: 11 },
                axisLine: { lineStyle: { color: t.grid } },
                splitLine: { lineStyle: { color: t.grid } },
                axisLabel: { color: t.muted, fontSize: 10 },
              },
              yAxis: {
                type: "log",
                name: "overrun ×",
                nameTextStyle: { color: t.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: t.grid } },
                axisLabel: { color: t.muted, fontSize: 10 },
              },
              tooltip: {
                trigger: "item",
                formatter: (p: { data: [number, number, string, string] }) =>
                  `<b>${p.data[2]}</b><br/>${p.data[1].toFixed(2)}× on ${p.data[0]} legs`,
              },
              series: [
                {
                  type: "scatter",
                  symbolSize: 6,
                  data: rows.map((c) => ({
                    value: [c.n_legs, c.excess_ratio, c.route],
                    itemStyle: { color: c.severity.color, opacity: 0.75 },
                  })),
                  markLine: {
                    silent: true,
                    symbol: "none",
                    lineStyle: { color: t.muted, type: "dashed", width: 1 },
                    label: {
                      color: t.muted,
                      fontSize: 10,
                      formatter: "network typical",
                    },
                    data: [{ yAxis: 1 }],
                  },
                },
              ],
            })}
          />
        </Card>
      </div>
    </>
  );
}
