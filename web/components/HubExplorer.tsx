"use client";

import { useMemo, useState } from "react";

import { Chart } from "@/components/Chart";
import { Card, Notice, TableShell, Td, Th } from "@/components/ui";
import { cx, minutes, num, pct, ratio } from "@/lib/format";
import type { Hub } from "@/lib/types";

type Metric = "share" | "minutes";

export function HubExplorer({ hubs }: { hubs: Hub[] }) {
  const [metric, setMetric] = useState<Metric>("minutes");
  const [query, setQuery] = useState("");

  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...hubs]
      .filter(
        (h) =>
          !q ||
          (h.city ?? "").toLowerCase().includes(q) ||
          (h.state ?? "").toLowerCase().includes(q) ||
          (h.name ?? "").toLowerCase().includes(q)
      )
      .sort((a, b) => {
        const av =
          metric === "share" ? (a.dwell_share ?? 0) : (a.median_dwell_min ?? 0);
        const bv =
          metric === "share" ? (b.dwell_share ?? 0) : (b.median_dwell_min ?? 0);
        return bv - av;
      });
  }, [hubs, metric, query]);

  const topByShare = [...hubs].sort(
    (a, b) => (b.dwell_share ?? 0) - (a.dwell_share ?? 0)
  )[0];
  const topByMinutes = [...hubs].sort(
    (a, b) => (b.median_dwell_min ?? 0) - (a.median_dwell_min ?? 0)
  )[0];

  const chartRows = ranked.slice(0, 15).reverse();

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-[var(--line)] p-0.5">
          {(
            [
              ["minutes", "By dwell minutes"],
              ["share", "By dwell share"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              onClick={() => setMetric(v)}
              className={cx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                metric === v
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
          placeholder="Search a hub or state…"
          className="min-w-[12rem] flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-1.5 text-sm placeholder:text-[var(--ink-faint)]"
        />
      </div>

      {topByShare && topByMinutes && topByShare.code !== topByMinutes.code && (
        <Notice tone="info" title="The two metrics disagree" className="mb-4">
          By share, <strong>{topByShare.city}</strong> is worst — it spends{" "}
          {pct(topByShare.dwell_share, 1)} of its legs parked. By minutes,{" "}
          <strong>{topByMinutes.city}</strong> is worst, at{" "}
          {minutes(topByMinutes.median_dwell_min)}. A short leg that waits an
          hour has a terrible share; a long leg that waits six has a modest one.
          Which you want depends on whether you are fixing a facility or a
          promise to a customer.
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <TableShell maxHeight="32rem">
          <thead>
            <tr>
              <Th align="left">#</Th>
              <Th align="left">Hub</Th>
              <Th align="right">Dwell</Th>
              <Th align="right">Share</Th>
              <Th align="right">Legs out</Th>
              <Th align="right">Ratio</Th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((h, i) => (
              <tr
                key={h.code}
                className="transition-colors hover:bg-[var(--surface-sunken)]"
              >
                <Td mono className="text-[var(--ink-faint)]">
                  {i + 1}
                </Td>
                <Td>
                  <p className="text-[13px] font-medium">{h.city ?? h.code}</p>
                  <p className="truncate text-[11px] text-[var(--ink-faint)]">
                    {h.state ?? "—"}
                  </p>
                </Td>
                <Td align="right" mono>
                  {minutes(h.median_dwell_min)}
                </Td>
                <Td align="right" mono>
                  {pct(h.dwell_share, 1)}
                </Td>
                <Td align="right" mono>
                  {num(h.outbound_legs)}
                </Td>
                <Td align="right" mono className="text-[var(--ink-faint)]">
                  {ratio(h.median_gap_ratio)}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>

        <Card>
          <p className="text-sm font-medium">
            Top 15 {metric === "share" ? "by dwell share" : "by dwell minutes"}
          </p>
          <Chart
            height={430}
            option={(t) => ({
              grid: { left: 96, right: 28, top: 16, bottom: 34 },
              xAxis: {
                type: "value",
                axisLabel: {
                  color: t.muted,
                  fontSize: 10,
                  formatter: (v: number) =>
                    metric === "share" ? `${(v * 100).toFixed(0)}%` : `${v}m`,
                },
                splitLine: { lineStyle: { color: t.grid } },
              },
              yAxis: {
                type: "category",
                data: chartRows.map((h) => h.city ?? h.code),
                axisLabel: { color: t.muted, fontSize: 11 },
                axisLine: { lineStyle: { color: t.grid } },
                axisTick: { show: false },
              },
              tooltip: {
                trigger: "axis",
                axisPointer: { type: "shadow" },
              },
              series: [
                {
                  type: "bar",
                  data: chartRows.map((h) =>
                    metric === "share" ? h.dwell_share : h.median_dwell_min
                  ),
                  itemStyle: { color: "#4d9fff", borderRadius: [0, 3, 3, 0] },
                  barWidth: "62%",
                  label: {
                    show: true,
                    position: "right",
                    color: t.muted,
                    fontSize: 10,
                    formatter: (p: { value: number }) =>
                      metric === "share"
                        ? `${(p.value * 100).toFixed(0)}%`
                        : `${Math.round(p.value)}m`,
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
