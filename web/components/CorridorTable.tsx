"use client";

import { useMemo, useState } from "react";

import { Chart } from "@/components/Chart";
import {
  Card,
  Notice,
  Pill,
  SeverityBadge,
  TableShell,
  Td,
  Th,
} from "@/components/ui";
import { cx, minutes, num, ratio, sci } from "@/lib/format";
import type { Corridor } from "@/lib/types";

type SortKey = "excess_ratio" | "n_legs" | "median_gap_min" | "q_value";

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
  const [direction, setDirection] = useState<"worse" | "better" | "both">("worse");
  const [sort, setSort] = useState<SortKey>("excess_ratio");
  const [asc, setAsc] = useState(false);

  const source = floor === 10 ? ten : thirty;

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = source.filter((c) => {
      if (!c.is_significant) return false;
      if (direction !== "both" && c.direction !== direction) return false;
      if (!q) return true;
      return (
        (c.src.city ?? "").toLowerCase().includes(q) ||
        (c.dst.city ?? "").toLowerCase().includes(q) ||
        (c.src.state ?? "").toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q)
      );
    });
    return filtered.sort((a, b) => {
      const av = (a[sort] ?? 0) as number;
      const bv = (b[sort] ?? 0) as number;
      return asc ? av - bv : bv - av;
    });
  }, [source, query, direction, sort, asc]);

  function header(key: SortKey, label: string, align: "left" | "right" = "right") {
    const active = sort === key;
    return (
      <Th align={align}>
        <button
          onClick={() => {
            if (active) setAsc((v) => !v);
            else {
              setSort(key);
              setAsc(false);
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
      </Th>
    );
  }

  return (
    <>
      {/* ── floor toggle ─────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-[var(--line)] p-0.5">
          {([10, 30] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFloor(f)}
              className={cx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                floor === f
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
              )}
            >
              {f}-leg floor
            </button>
          ))}
        </div>

        <div className="flex rounded-lg border border-[var(--line)] p-0.5">
          {(
            [
              ["worse", "Slower"],
              ["better", "Faster"],
              ["both", "Both"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              onClick={() => setDirection(v)}
              className={cx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                direction === v
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a city or state…"
          className="min-w-[12rem] flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-1.5 text-sm placeholder:text-[var(--ink-faint)]"
        />

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
        <TableShell maxHeight="34rem">
          <thead>
            <tr>
              <Th align="left">Corridor</Th>
              {header("excess_ratio", "Overrun")}
              {header("n_legs", "Legs")}
              {header("median_gap_min", "Typically late")}
              {header("q_value", "q")}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
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
                        {c.src.city ?? c.src.code} → {c.dst.city ?? c.dst.code}
                      </p>
                      <p className="truncate text-[11px] text-[var(--ink-faint)]">
                        {c.src.state ?? "—"}
                        {c.intra_city && " · intra-city"}
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
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <Td className="py-8 text-center text-[var(--ink-muted)]">
                  Nothing matches that search.
                </Td>
              </tr>
            )}
          </tbody>
        </TableShell>

        {/* ── effect size against support ────────────────────────────── */}
        <Card>
          <p className="text-sm font-medium">Effect size against evidence</p>
          <p className="mb-3 mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">
            Every significant corridor, plotted by how many legs it rests on.
            The extreme overruns sit on the left — they are real findings and
            they are also the ones most likely to be a lucky sample.
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
                    value: [
                      c.n_legs,
                      c.excess_ratio,
                      `${c.src.city ?? c.src.code} → ${c.dst.city ?? c.dst.code}`,
                    ],
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
