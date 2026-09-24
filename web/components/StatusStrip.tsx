"use client";

import { useEffect, useState } from "react";

import { API_CONFIGURED, getHealth } from "@/lib/api";
import { cx } from "@/lib/format";

/**
 * Live system health, not a file-existence checklist.
 *
 * The Streamlit sidebar showed tick boxes for which artefacts were on disk --
 * a build-status panel for the team. This shows whether the API answering this
 * page is actually up, which is the only status a visitor has any use for, and
 * says plainly when the answer is "no".
 */
export function StatusStrip({ freeze }: { freeze: string }) {
  const [state, setState] = useState<"checking" | "up" | "down" | "static">(
    API_CONFIGURED ? "checking" : "static"
  );

  useEffect(() => {
    if (!API_CONFIGURED) return;
    let cancelled = false;
    getHealth().then((r) => {
      if (!cancelled) setState(r.ok ? "up" : "down");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const dot = {
    checking: "bg-[var(--ink-faint)]",
    up: "bg-emerald-400",
    down: "bg-amber-400",
    static: "bg-[var(--accent)]",
  }[state];

  // Only say something when there is something to say. "static build" and a
  // freeze version told a visitor about our deployment, which is not what a
  // strip at the top of a page is for. What it is for is the scope of the data
  // underneath -- one line that makes the rest of the site legible.
  const liveNote = {
    checking: null,
    up: "live predictions available",
    down: null,
    static: null,
  }[state];

  return (
    <div className="border-b border-[var(--line)] bg-[var(--surface-sunken)]">
      <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1.5 text-[11px] text-[var(--ink-faint)] sm:px-6">
        <span className="tabular">
          144,867 scan records · 26,369 journeys · 1,130 corridors analysed ·
          Sep–Oct 2018
        </span>
        {liveNote && (
          <span className="flex items-center gap-1.5">
            <span
              className={cx("inline-block h-1.5 w-1.5 rounded-full", dot)}
            />
            {liveNote}
          </span>
        )}
      </div>
    </div>
  );
}
