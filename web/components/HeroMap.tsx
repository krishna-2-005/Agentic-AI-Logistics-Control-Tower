import Link from "next/link";

import { CorridorSketch } from "@/components/CorridorSketch";
import type { Corridor } from "@/lib/types";

/**
 * The landing hero: the worst corridors as a static drawing.
 *
 * This used to mount deck.gl and MapLibre on first paint. On a phone that blocked the main thread for
 * several seconds (Lighthouse total blocking time about 6 s, mobile performance 59) before the visitor
 * could scroll. The drawing paints at once and ships no JavaScript; the interactive map is one click away.
 */
export function HeroMap({ corridors }: { corridors: Corridor[] }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]">
      <CorridorSketch
        corridors={corridors}
        label={`The ${corridors.length} corridors that run furthest over the OSRM estimate, drawn between their end points; colour and thickness show how far over.`}
      />
      <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-[var(--line)] bg-[var(--surface)]/85 px-3 py-2 text-xs backdrop-blur">
        <p className="font-medium">The {corridors.length} corridors furthest over plan</p>
        <p className="mt-0.5 text-[var(--ink-faint)]">thickness and colour = how far over</p>
      </div>
      <Link
        href="/network/"
        className="absolute bottom-3 left-3 rounded-lg bg-[var(--accent-bg)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
      >
        Open the interactive map
      </Link>
    </div>
  );
}
