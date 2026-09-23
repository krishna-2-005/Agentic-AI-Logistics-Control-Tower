"use client";

import { useEffect, useState } from "react";

import { Card, Notice, Pill, TableShell, Td, Th } from "@/components/ui";
import { API_CONFIGURED, getAlerts } from "@/lib/api";
import { cx, minutes, num, ratio, shortDate } from "@/lib/format";
import type { AlertRow, AlertsSample } from "@/lib/types";

const SEVERITY_STYLE: Record<string, { color: string; precision: string }> = {
  critical: { color: "#5e1413", precision: "85.3% precise" },
  high: { color: "#a02726", precision: "76.6% precise" },
  medium: { color: "#e34948", precision: "51.3% precise" },
  low: { color: "#ec9694", precision: "39.7% precise" },
};

/**
 * The alert feed.
 *
 * On a deployment with an API this polls it. Without one it shows the recorded
 * run, clearly labelled -- W-03. The label matters: a page that silently shows
 * old rows while implying they are live is exactly the failure mode this
 * project's own evaluation leak was.
 */
export function AlertFeed({ sample }: { sample: AlertsSample }) {
  const [live, setLive] = useState<AlertRow[] | null>(null);
  const [isLive, setIsLive] = useState(false);
  const [visible, setVisible] = useState(12);

  useEffect(() => {
    if (!API_CONFIGURED) return;
    let cancelled = false;

    async function poll() {
      const r = await getAlerts();
      if (cancelled) return;
      if (r.ok && r.data.alerts?.length) {
        setLive(
          r.data.alerts.map((a) => ({
            seq: a.seq,
            corridor_id: a.corridor_id,
            route: a.route ?? a.corridor_id,
            predicted_gap_min: a.predicted_gap_min,
            excess_ratio: a.excess_ratio ?? null,
            severity: a.severity,
            n_legs: a.n_legs ?? 0,
          }))
        );
        setIsLive(true);
      }
    }

    poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const rows = live ?? sample.alerts;
  const counts = rows.reduce<Record<string, number>>((acc, a) => {
    acc[a.severity] = (acc[a.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      {!isLive && (
        <Notice tone="replay" title="Recorded run, not a live feed" className="mb-4">
          {sample.replay_note ||
            "These alerts come from a recorded replay committed with the site."}{" "}
          {sample.recorded_at && `Recorded ${shortDate(sample.recorded_at)}.`}{" "}
          {sample.run.alerts !== null && (
            <>
              That run produced {num(sample.run.alerts)} alerts from{" "}
              {num(sample.run.events)} events.
            </>
          )}
        </Notice>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {isLive && (
          <Pill tone="good">
            <span className="inline-block h-1.5 w-1.5 animate-pulse-dot rounded-full bg-emerald-400" />
            live · polling every 5s
          </Pill>
        )}
        {(["critical", "high", "medium", "low"] as const).map((s) =>
          counts[s] ? (
            <span
              key={s}
              className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium"
              style={{
                color: SEVERITY_STYLE[s].color,
                borderColor: `${SEVERITY_STYLE[s].color}66`,
                background: `${SEVERITY_STYLE[s].color}14`,
              }}
            >
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: SEVERITY_STYLE[s].color }}
              />
              {counts[s]} {s}
            </span>
          ) : null
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <TableShell maxHeight="30rem">
          <thead>
            <tr>
              <Th align="left">Severity</Th>
              <Th align="left">Shipment</Th>
              <Th align="right">Predicted late by</Th>
              <Th align="right">Corridor overrun</Th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, visible).map((a) => {
              const style = SEVERITY_STYLE[a.severity] ?? SEVERITY_STYLE.low;
              return (
                <tr
                  key={`${a.corridor_id}-${a.seq}`}
                  className="animate-fade-up transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <Td>
                    <span
                      className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium"
                      style={{
                        color: style.color,
                        background: `${style.color}18`,
                      }}
                    >
                      <span
                        aria-hidden
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: style.color }}
                      />
                      {a.severity}
                    </span>
                  </Td>
                  <Td>
                    <p className="text-[13px] font-medium">{a.route}</p>
                    <p className="font-mono text-[10px] text-[var(--ink-faint)]">
                      {a.corridor_id}
                    </p>
                  </Td>
                  <Td align="right" mono>
                    <strong>{minutes(a.predicted_gap_min)}</strong>
                  </Td>
                  <Td align="right" mono className="text-[var(--ink-faint)]">
                    {ratio(a.excess_ratio)}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </TableShell>

        <Card>
          <p className="text-sm font-medium">Severity earns its place</p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">
            Each grade is more likely to be a real delay than the one below it.
            That monotonic rise is the justification for grading at all — and
            it survived the leak correction, at lower levels.
          </p>

          <ul className="mt-4 space-y-2">
            {(["critical", "high", "medium", "low"] as const).map((s) => (
              <li key={s} className="flex items-center gap-3">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: SEVERITY_STYLE[s].color }}
                />
                <span className="w-16 text-xs font-medium capitalize">{s}</span>
                <span className="tabular flex-1 font-mono text-[11px] text-[var(--ink-muted)]">
                  {SEVERITY_STYLE[s].precision}
                </span>
              </li>
            ))}
          </ul>

          <p className="mt-4 border-t border-[var(--line)] pt-3 text-xs leading-relaxed text-[var(--ink-muted)]">
            Alerting on <em>every</em> leg would be 54.1% precise. So notifying
            on <strong>low</strong> alone is worse than not filtering at all —
            which is a real limit, stated rather than buried.
          </p>
        </Card>
      </div>

      {visible < rows.length && (
        <button
          onClick={() => setVisible((v) => v + 20)}
          className={cx(
            "mt-3 w-full rounded-lg border border-[var(--line)] py-2 text-sm",
            "text-[var(--ink-muted)] transition-colors hover:border-[var(--ink-faint)] hover:text-[var(--ink)]"
          )}
        >
          Show more ({rows.length - visible} remaining)
        </button>
      )}
    </>
  );
}
