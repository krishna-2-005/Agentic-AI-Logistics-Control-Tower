"use client";

import dynamic from "next/dynamic";
import type { ComponentProps } from "react";

import { Lazy } from "@/components/Lazy";

import type { ChartImpl } from "./ChartImpl";

export type { ChartOption } from "./ChartImpl";

// echarts is a few hundred kilobytes: it loads when a chart nears the viewport.
const Impl = dynamic(() => import("./ChartImpl").then((m) => m.ChartImpl), {
  ssr: false,
});

/** The one chart component, loaded on demand. Same props as `ChartImpl`. */
export function Chart(props: ComponentProps<typeof ChartImpl>) {
  return (
    <Lazy height={props.height ?? 320} label={props.label ?? "Chart loading"}>
      <Impl {...props} />
    </Lazy>
  );
}
