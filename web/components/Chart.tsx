"use client";

import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DatasetComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

/**
 * The one chart component.
 *
 * D-058: one chart library for the whole site. The old dashboard mixed
 * `st.bar_chart`, Plotly and Folium on one page, and mixed styling is most of
 * why a dashboard reads as amateur. Everything here goes through this wrapper
 * and inherits the same grid, palette and type.
 *
 * Written by hand rather than pulled from `echarts-for-react`, which has not
 * kept up with React 19's peer ranges -- forty lines is cheaper than a
 * dependency that blocks an upgrade.
 */

function readTheme() {
  if (typeof window === "undefined") {
    return { ink: "#e8edf7", muted: "#9aa8c2", grid: "#162135", surface: "#121b2d" };
  }
  const s = getComputedStyle(document.documentElement);
  return {
    ink: s.getPropertyValue("--ink").trim() || "#e8edf7",
    muted: s.getPropertyValue("--ink-muted").trim() || "#9aa8c2",
    grid: s.getPropertyValue("--grid").trim() || "#162135",
    surface: s.getPropertyValue("--surface-raised").trim() || "#121b2d",
  };
}

export type ChartOption = Record<string, unknown>;

export function Chart({
  option,
  height = 320,
  className,
  onReady,
}: {
  /** Given the resolved theme colours, return the ECharts option. */
  option: (theme: ReturnType<typeof readTheme>) => ChartOption;
  height?: number | string;
  className?: string;
  onReady?: (instance: echarts.ECharts) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [themeTick, setThemeTick] = useState(0);

  // Re-render on a theme flip, so a chart never keeps dark-mode axis colours on
  // a white background.
  useEffect(() => {
    const observer = new MutationObserver(() => setThemeTick((t) => t + 1));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!ref.current) return;
    const theme = readTheme();

    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, {
        renderer: "canvas",
      });
      onReady?.(chartRef.current);
    }

    const base: ChartOption = {
      backgroundColor: "transparent",
      animationDuration: 600,
      animationEasing: "cubicOut",
      textStyle: {
        fontFamily:
          "var(--font-sans), system-ui, sans-serif",
        color: theme.muted,
      },
      tooltip: {
        backgroundColor: theme.surface,
        borderColor: theme.grid,
        borderWidth: 1,
        textStyle: { color: theme.ink, fontSize: 12 },
        padding: [8, 10],
      },
    };

    chartRef.current.setOption({ ...base, ...option(theme) }, true);

    const ro = new ResizeObserver(() => chartRef.current?.resize());
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [option, themeTick, onReady]);

  useEffect(
    () => () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    },
    []
  );

  return (
    <div
      ref={ref}
      className={className}
      style={{ height, width: "100%" }}
      role="img"
    />
  );
}
