"use client";

import { useState } from "react";

import { Chart } from "@/components/Chart";
import { cx } from "@/lib/format";
import type { ModelSlice } from "@/lib/types";

/**
 * MAE by slice, model against the baseline it is judged on.
 *
 * Paired bars rather than a delta, because the delta alone hides the thing
 * worth seeing: on corridors with history the two bars are nearly the same
 * height. The win is real and it is concentrated in one slice.
 */
export function ModelSlices({ slices }: { slices: ModelSlice[] }) {
  const dimensions = Array.from(new Set(slices.map((s) => s.dimension)));
  const [dimension, setDimension] = useState(
    dimensions.includes("support_in_train") ? "support_in_train" : dimensions[0]
  );

  const rows = slices.filter(
    (s) => s.dimension === dimension && s.model !== "corridor_median"
  );

  const labels = rows.map((s) => s.slice);
  const modelMae = rows.map((s) => s.mae_min);
  const baseMae = rows.map((s) => s.baseline_mae_min);

  return (
    <>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {dimensions.map((d) => (
          <button
            key={d}
            onClick={() => setDimension(d)}
            className={cx(
              "rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
              dimension === d
                ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent)]"
                : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
            )}
          >
            {d.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      <Chart
        height={Math.max(260, labels.length * 46)}
        option={(t) => ({
          grid: { left: 110, right: 40, top: 30, bottom: 34 },
          legend: {
            data: ["model", "corridor median"],
            top: 0,
            right: 0,
            textStyle: { color: t.muted, fontSize: 11 },
            itemWidth: 10,
            itemHeight: 10,
          },
          xAxis: {
            type: "value",
            name: "MAE (min) — lower is better",
            nameLocation: "middle",
            nameGap: 24,
            nameTextStyle: { color: t.muted, fontSize: 11 },
            splitLine: { lineStyle: { color: t.grid } },
            axisLabel: { color: t.muted, fontSize: 10 },
          },
          yAxis: {
            type: "category",
            data: labels,
            axisLabel: { color: t.muted, fontSize: 11 },
            axisLine: { lineStyle: { color: t.grid } },
            axisTick: { show: false },
          },
          tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
          series: [
            {
              name: "model",
              type: "bar",
              data: modelMae,
              itemStyle: { color: "#4d9fff", borderRadius: [0, 3, 3, 0] },
              barGap: "10%",
            },
            {
              name: "corridor median",
              type: "bar",
              data: baseMae,
              itemStyle: { color: t.grid, borderRadius: [0, 3, 3, 0] },
            },
          ],
        })}
      />

      <p className="mt-2 text-xs leading-relaxed text-[var(--ink-muted)]">
        Where the two bars are the same length, a lookup of the corridor&apos;s
        own median is as good as the model. The model earns its place on the
        slice where no such history exists.
      </p>
    </>
  );
}
