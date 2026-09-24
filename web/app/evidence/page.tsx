import type { Metadata } from "next";

import { ModelSlices } from "@/components/charts/ModelSlices";
import {
  Card,
  Evidence,
  Kpi,
  KpiRow,
  Notice,
  PageHeader,
  Section,
  TableShell,
  Td,
  Th,
} from "@/components/ui";
import { getEvidence, getFigures, getModel } from "@/lib/data";
import { num } from "@/lib/format";

export const metadata: Metadata = {
  title: "Results",
  description:
    "The measured results behind the network map, the model and the agents.",
};

const WEEK_LABELS: Record<number, string> = {
  1: "The data",
  2: "Corridor audit",
  3: "Baselines",
  4: "Batch ML and documents",
  5: "Streaming and order entry",
  6: "The lifecycle",
  7: "Model correction, RAG, scale",
  8: "Reproducibility and the leak",
};

/** "fig3_top_bottlenecks" -> "3 · Top bottlenecks". */
function prettyFigure(id: string): string {
  const m = id.match(/^fig(\d+)_(.+)$/);
  if (!m) return id.replace(/_/g, " ");
  const words = m[2]
    .split("_")
    .map((w) => (w.toLowerCase() === "mae" ? "MAE" : w))
    .join(" ");
  return `${m[1]} · ${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

export default function EvidencePage() {
  const evidence = getEvidence();
  const model = getModel();
  const figures = getFigures();

  const byWeek = new Map<number, typeof evidence.data.entries>();
  evidence.data.entries.forEach((e) => {
    const w = e.week ?? 0;
    if (!byWeek.has(w)) byWeek.set(w, []);
    byWeek.get(w)!.push(e);
  });

  const h = model.data.headline;

  return (
    <>
      <PageHeader
        eyebrow="Results"
        title="The results"
        lede={
          <>
            Everything this project measured, in one place: how accurate the
            prediction is, where it beats a simple lookup and where it does
            not, and what the analysis of the network found.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={`${num(h.mae_min, 2)} min`}
            label="reported model error"
            sub="gradient-boosted, on the residual over a per-corridor median"
            accent
          />
          <Kpi
            value={`${num(h.baseline_mae_min, 2)} min`}
            label="the bar it must beat"
            sub="the per-corridor median — MAE is minimised by the median, not the mean"
          />
          <Kpi
            value={`${num(h.osrm_mae_min, 2)} min`}
            label="the planner's own error"
            sub="context, not a fair comparison — OSRM never sees corridor history"
          />
          <Kpi
            value="14 / 14"
            label="slices the model wins on"
            sub="by corridor history, route type, distance band and departure hour"
          />
        </KpiRow>
      </Section>

      {/* ── the served-model caveat, stated where the number appears ──── */}
      <Section>
        <Notice
          tone="warn"
          title="The live predictor uses an earlier model than this one"
        >
          The model below needs a rolling view of each lane&apos;s recent
          history that the live service cannot build yet, so the{" "}
          <a href="/predict/" className="underline">
            delay predictor
          </a>{" "}
          runs an earlier, slightly weaker model and names it on every answer.
        </Notice>
      </Section>

      <Section
        title="Where the model wins"
        description="Adopted because it wins on all fourteen slices — but most of the margin comes from corridors the training set never saw. On corridors with history it beats a median lookup by a fifth of a minute. That is a real gain and a small one."
        actions={
          <Evidence file="benchmarks/raw/w7_model_metrics_v2_stepsize.csv" />
        }
      >
        <Card>
          <ModelSlices slices={model.data.slices} />
        </Card>
      </Section>

      {/* ── the figures ───────────────────────────────────────────────── */}
      {figures.data.figures.length > 0 && (
        <Section
          title="The figures"
          description="The nine figures behind the write-up, each computed from the measurements on this page."
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {figures.data.figures.map((f) => (
              <Card key={f.id} padded={false} className="overflow-hidden">
                <div className="bg-white p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={f.file}
                    alt={f.title}
                    loading="lazy"
                    className="w-full"
                  />
                </div>
                <p className="border-t border-[var(--line)] px-4 py-2.5 text-xs text-[var(--ink-muted)]">
                  {prettyFigure(f.id)}
                </p>
              </Card>
            ))}
          </div>
        </Section>
      )}

      {/* ── the freeze, week by week ──────────────────────────────────── */}
      <Section
        title="All measurements"
        description="Every figure this project reports, grouped by the stage of work that produced it."
      >
        <div className="space-y-6">
          {[...byWeek.entries()]
            .sort((a, b) => a[0] - b[0])
            .map(([week, entries]) => (
              <div key={week}>
                <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold">
                  <span className="font-mono text-[var(--ink-faint)]">
                    W{week}
                  </span>
                  {WEEK_LABELS[week] ?? ""}
                </h3>
                <TableShell>
                  <thead>
                    <tr>
                      <Th align="left">Value</Th>
                      <Th align="right">Result</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e) => (
                      <tr
                        key={e.key}
                        className="transition-colors hover:bg-[var(--surface-sunken)]"
                      >
                        <Td>{e.label}</Td>
                        <Td align="right" mono className="whitespace-nowrap">
                          <strong>
                            {typeof e.value === "number"
                              ? e.value.toLocaleString("en-IN")
                              : String(e.value)}
                          </strong>{" "}
                          <span className="text-[var(--ink-faint)]">
                            {e.unit}
                          </span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </TableShell>
              </div>
            ))}
        </div>
      </Section>

    </>
  );
}
