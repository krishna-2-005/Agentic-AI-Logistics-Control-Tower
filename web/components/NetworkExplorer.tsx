"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

import { Card, Evidence, Notice, Pill, SeverityBadge } from "@/components/ui";
import { cx, minutes, num, pct, ratio, sci } from "@/lib/format";
import type { Corridor } from "@/lib/types";

const CorridorMap = dynamic(
  () => import("./CorridorMap").then((m) => m.CorridorMap),
  {
    ssr: false,
    loading: () => (
      <div className="h-[560px] animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]" />
    ),
  }
);

type Filter = "worse" | "better" | "both";

interface Legend {
  worse: { upto: number; color: string; label: string; range: string }[];
  better: { upto: number; color: string; label: string; range: string }[];
}

export function NetworkExplorer({
  corridors,
  located,
  legend,
}: {
  corridors: Corridor[];
  located: number;
  legend?: Legend;
}) {
  const [filter, setFilter] = useState<Filter>("worse");
  const [significantOnly, setSignificantOnly] = useState(true);
  const [minLegs, setMinLegs] = useState(10);
  const [state, setState] = useState<string>("all");
  const [selected, setSelected] = useState<Corridor | null>(null);

  const states = useMemo(() => {
    const set = new Set<string>();
    corridors.forEach((c) => {
      if (c.src.state) set.add(c.src.state);
    });
    return ["all", ...Array.from(set).sort()];
  }, [corridors]);

  const shown = useMemo(
    () =>
      corridors.filter((c) => {
        if (significantOnly && !c.is_significant) return false;
        if (filter !== "both" && c.direction !== filter) return false;
        if (c.n_legs < minLegs) return false;
        if (state !== "all" && c.src.state !== state) return false;
        return true;
      }),
    [corridors, filter, significantOnly, minLegs, state]
  );

  return (
    <>
      {/* ── controls ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-[var(--line)] p-0.5">
          {(
            [
              ["worse", "Slower"],
              ["better", "Faster"],
              ["both", "Both"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={cx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                filter === value
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm">
          <input
            type="checkbox"
            checked={significantOnly}
            onChange={(e) => setSignificantOnly(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          Significant only
        </label>

        <label className="flex items-center gap-2 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm">
          <span className="text-[var(--ink-muted)]">Min legs</span>
          <input
            type="range"
            min={10}
            max={100}
            step={5}
            value={minLegs}
            onChange={(e) => setMinLegs(Number(e.target.value))}
            className="w-24 accent-[var(--accent)]"
          />
          <span className="tabular w-7 font-mono text-xs">{minLegs}</span>
        </label>

        <select
          value={state}
          onChange={(e) => setState(e.target.value)}
          className="rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-1.5 text-sm"
        >
          {states.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All states" : s}
            </option>
          ))}
        </select>

        <Pill className="ml-auto">
          {num(shown.length)} of {num(corridors.length)} shown
        </Pill>
      </div>

      {/* ── map + side panel ─────────────────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <CorridorMap
          corridors={shown}
          height={560}
          onSelect={setSelected}
          selectedId={selected?.id ?? null}
        />

        <div className="space-y-4">
          {selected ? (
            <Card>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">
                    {selected.src.city ?? selected.src.code} →{" "}
                    {selected.dst.city ?? selected.dst.code}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-[var(--ink-faint)]">
                    {selected.id}
                  </p>
                </div>
                <button
                  onClick={() => setSelected(null)}
                  aria-label="Close"
                  className="text-[var(--ink-faint)] hover:text-[var(--ink)]"
                >
                  ✕
                </button>
              </div>

              <div className="mt-3">
                <SeverityBadge
                  color={selected.severity.color}
                  label={`${selected.severity.label} · ${selected.severity.range}`}
                  direction={selected.direction}
                />
              </div>

              <dl className="mt-4 space-y-2 text-sm">
                <Row
                  k="Overruns"
                  v={`${ratio(selected.excess_ratio)} the network's typical`}
                />
                <Row k="Legs observed" v={num(selected.n_legs)} />
                <Row
                  k="Typically late by"
                  v={minutes(selected.median_gap_min)}
                />
                <Row
                  k="Median ratio"
                  v={ratio(selected.median_gap_ratio)}
                />
                <Row k="Hub dwell" v={minutes(selected.mean_dwell_min)} />
                <Row k="Distance" v={`${num(selected.mean_osrm_km, 0)} km`} />
                <Row k="FTL share" v={pct(selected.ftl_share, 0)} />
                <Row k="q-value" v={sci(selected.q_value)} />
              </dl>

              {selected.n_legs < 20 && (
                <p className="mt-3 rounded-lg bg-[var(--surface-sunken)] px-3 py-2 text-xs leading-relaxed text-[var(--ink-muted)]">
                  Resting on {selected.n_legs} legs. With {num(corridors.length)}{" "}
                  corridors tested, the largest effect sizes are the likeliest to
                  be a lucky sample — read this as a lead, not a verdict.
                </p>
              )}

              <div className="mt-3">
                <Evidence file="benchmarks/raw/w2_corridor_audit.csv" />
              </div>
            </Card>
          ) : (
            <Notice tone="replay" title="Click any arc">
              Select a corridor on the map to see its audit verdict, how late it
              typically runs and how many legs the finding rests on.
            </Notice>
          )}

          {legend && (
            <Card>
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                Slower than the network
              </p>
              <ul className="mt-2 space-y-1.5">
                {legend.worse.map((b) => (
                  <LegendRow key={b.color} {...b} />
                ))}
              </ul>
              <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                Faster than the network
              </p>
              <ul className="mt-2 space-y-1.5">
                {[...legend.better].reverse().map((b) => (
                  <LegendRow key={b.color} {...b} />
                ))}
              </ul>
            </Card>
          )}

          <p className="text-xs leading-relaxed text-[var(--ink-muted)]">
            {num(located)} of {num(corridors.length)} corridors have both ends
            located. Position comes from the centre code, never the facility
            name — a code is never null and never spelled two ways.
          </p>
        </div>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-[var(--line)]/50 pb-1.5">
      <dt className="text-[var(--ink-muted)]">{k}</dt>
      <dd className="tabular text-right font-mono text-[13px]">{v}</dd>
    </div>
  );
}

function LegendRow({
  color,
  label,
  range,
}: {
  color: string;
  label: string;
  range: string;
}) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span
        aria-hidden
        className="h-1 w-6 shrink-0 rounded-full"
        style={{ background: color }}
      />
      <span className="tabular font-mono text-[var(--ink-muted)]">{range}</span>
      <span className="text-[var(--ink-faint)]">{label}</span>
    </li>
  );
}
