"use client";

import { Chart } from "@/components/Chart";
import { pct } from "@/lib/format";

/**
 * The distribution that is the whole project's reason for existing.
 *
 * The bar at 1.0 is the line between "arrived within plan" and "did not", and
 * the mass sits almost entirely to its right. A marker on the median says how
 * far right the middle of the network actually is.
 */
export function GapHistogram({
  bins,
  median,
  clipAt,
  aboveClip,
}: {
  bins: { x: number; n: number }[];
  median: number;
  clipAt: number;
  aboveClip: number;
}) {
  return (
    <>
      <Chart
        height={300}
        option={(t) => ({
          grid: { left: 54, right: 20, top: 24, bottom: 42 },
          xAxis: {
            type: "category",
            data: bins.map((b) => b.x.toFixed(1)),
            name: "realised ÷ planned time",
            nameLocation: "middle",
            nameGap: 28,
            nameTextStyle: { color: t.muted, fontSize: 11 },
            axisLine: { lineStyle: { color: t.grid } },
            axisTick: { show: false },
            axisLabel: {
              color: t.muted,
              fontSize: 11,
              interval: 4,
            },
          },
          yAxis: {
            type: "value",
            name: "legs",
            nameTextStyle: { color: t.muted, fontSize: 11, align: "right" },
            splitLine: { lineStyle: { color: t.grid } },
            axisLabel: {
              color: t.muted,
              fontSize: 11,
              formatter: (v: number) =>
                v >= 1000 ? `${v / 1000}k` : String(v),
            },
          },
          tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: (p: { name: string; value: number }[]) =>
              `<b>${p[0].value.toLocaleString()}</b> legs<br/>at ${p[0].name}× plan`,
          },
          series: [
            {
              type: "bar",
              data: bins.map((b) => b.n),
              itemStyle: {
                // On-plan legs are the reference; everything right of 1.0 is the
                // finding, so the ramp starts there rather than colouring all bars.
                color: (p: { dataIndex: number }) =>
                  bins[p.dataIndex].x <= 1.0 ? t.muted : "#e34948",
                borderRadius: [2, 2, 0, 0],
              },
              barCategoryGap: "12%",
              markLine: {
                silent: true,
                symbol: "none",
                label: {
                  color: t.ink,
                  fontSize: 11,
                  formatter: `median ${median.toFixed(2)}×`,
                  position: "insideEndTop",
                },
                lineStyle: { color: t.ink, type: "dashed", width: 1.2 },
                data: [
                  {
                    xAxis: bins.findIndex((b) => b.x >= median),
                  },
                ],
              },
            },
          ],
        })}
      />
      <p className="mt-2 text-xs text-[var(--ink-muted)]">
        Clipped at {clipAt}× so the tail does not flatten the bulk;{" "}
        {pct(aboveClip, 2)} of legs run beyond that and are not drawn.
      </p>
    </>
  );
}
