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

  const text = {
    checking: "checking the live service…",
    up: "live service up",
    down: "live service asleep — recorded evidence shown",
    static: "static build — recorded evidence",
  }[state];

  return (
    <div className="border-b border-[var(--line)] bg-[var(--surface-sunken)]">
      <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1.5 font-mono text-[11px] text-[var(--ink-faint)] sm:px-6">
        <span className="flex items-center gap-1.5">
          <span
            className={cx(
              "inline-block h-1.5 w-1.5 rounded-full",
              dot,
              state === "checking" && "animate-pulse-dot"
            )}
          />
          {text}
        </span>
        <span className="hidden sm:inline">
          results freeze <span className="text-[var(--ink-muted)]">{freeze}</span>
        </span>
        <span className="hidden md:inline">
          145K segments · 26,369 legs · 1,130 corridors tested
        </span>
      </div>
    </div>
  );
}
