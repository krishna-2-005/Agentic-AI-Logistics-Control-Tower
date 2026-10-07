"use client";

import dynamic from "next/dynamic";

import type { Corridor } from "@/lib/types";

/**
 * The landing hero.
 *
 * deck.gl and MapLibre both touch `window` on import, so the map is loaded
 * client-side only -- a static export has no browser at build time.
 */
const CorridorMap = dynamic(
  () => import("./CorridorMap").then((m) => m.CorridorMap),
  {
    ssr: false,
    loading: () => (
      <div className="h-[420px] animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]" />
    ),
  }
);

export function HeroMap({ corridors }: { corridors: Corridor[] }) {
  return (
    <div className="relative">
      <CorridorMap corridors={corridors} height={420} interactive={false} />
      <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-[var(--line)] bg-[var(--surface)]/85 px-3 py-2 text-xs backdrop-blur">
        <p className="font-medium">The eight worst corridors</p>
        <p className="mt-0.5 text-[var(--ink-faint)]">
          thickness and colour = how far over plan
        </p>
      </div>
    </div>
  );
}
