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
import { num, pct } from "@/lib/format";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("Results", "The measured results behind the network map, the model and the agents.");

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
  const reported = model.data.slices.filter((s) => s.model === h.model);
  const wins = reported.filter(
    (s) => s.delta_vs_median_min !== null && s.delta_vs_median_min < 0
  ).length;

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
            label="best model's average error"
            sub="how far off a delay prediction is, on average"
            accent
          />
          <Kpi
            value={`${num(h.baseline_mae_min, 2)} min`}
            label="the bar it must beat"
            sub="what you get by just looking up this corridor's usual delay"
          />
          <Kpi
            value={`${num(h.osrm_mae_min, 2)} min`}
            label="the OSRM estimate's error"
            sub="the estimate recorded in the dataset, shown as context only: it has no access to past journeys"
          />
          <Kpi
            value={`${wins} / ${reported.length}`}
            label="slices the model wins on"
            sub="by corridor history, route type, distance band and departure hour"
          />
        </KpiRow>
      </Section>

      <Section
        title="Two baselines, and why the median is the bar"
        description="A model is only as impressive as the simple rule it beats."
      >
        <Card>
          <ul className="space-y-2 text-sm leading-relaxed text-[var(--ink-muted)]">
            <li>
              <strong className="text-[var(--ink)]">
                Mean, {num(h.mean_baseline_mae_min, 2)} min:
              </strong>{" "}
              predict each corridor&apos;s average past delay. A few very long
              legs drag an average up, so it is a weak yardstick.
            </li>
            <li>
              <strong className="text-[var(--ink)]">
                Median, {num(h.baseline_mae_min, 2)} min:
              </strong>{" "}
              predict each corridor&apos;s median past delay. Mean absolute error
              is smallest at the median, so this is the fair bar the model has to
              clear.
            </li>
            {h.backoff_mae_min != null && (
              <li>
                <strong className="text-[var(--ink)]">
                  Hierarchical back-off, {num(h.backoff_mae_min, 2)} min:
                </strong>{" "}
                the median, falling back to coarser groups rather than to the
                OSRM estimate when a corridor has no history.
              </li>
            )}
          </ul>
        </Card>
      </Section>

      {/* ── which model the live predictor runs, from the evidence file ── */}
      <Section>
        {model.data.headline.served_model === model.data.headline.model ? (
          <Notice tone="info" title="The live predictor runs this model">
            The{" "}
            <a href="/predict/" className="underline">
              delay predictor
            </a>{" "}
            and the stream score with the model below, and{" "}
            {model.data.headline.stream_equals_batch?.identical ?? 0} of{" "}
            {model.data.headline.stream_equals_batch?.legs ?? 0} sampled legs
            score exactly as they do in the offline evaluation.
          </Notice>
        ) : (
          <Notice
            tone="warn"
            title="The live predictor uses an earlier model than this one"
          >
            {model.data.headline.served_note}
          </Notice>
        )}
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
                    alt={`${f.title}. ${f.caption}`}
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
                  </span>{" "}
                  <span>{WEEK_LABELS[week] ?? ""}</span>
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
                        <Td>
                          {e.label}
                        </Td>
                        <Td align="right" mono className="whitespace-nowrap">
                          <strong>
                            {typeof e.value === "number"
                              ? e.unit === "share"
                                ? pct(e.value, 1)
                                : num(e.value, Number.isInteger(e.value) ? 0 : 2)
                              : String(e.value)}
                          </strong>{" "}
                          <span className="text-[var(--ink-faint)]">
                            {e.unit === "share"
                              ? e.n !== undefined
                                ? `(n = ${num(e.n)})`
                                : ""
                              : e.unit}
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
