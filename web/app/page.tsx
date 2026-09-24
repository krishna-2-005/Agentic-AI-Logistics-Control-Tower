import Link from "next/link";

import { GapHistogram } from "@/components/charts/GapHistogram";
import { HeroMap } from "@/components/HeroMap";
import {
  ArrowLink,
  Card,
  Evidence,
  Kpi,
  KpiRow,
  Pill,
  Section,
} from "@/components/ui";
import { getCorridors, getModel, getOverview } from "@/lib/data";
import { minutes, num, pct, ratio } from "@/lib/format";

export default function HomePage() {
  const overview = getOverview();
  const corridors = getCorridors();
  const model = getModel();

  const o = overview.data;
  const worst = [...corridors.data]
    .filter((c) => c.is_significant && c.direction === "worse")
    .sort((a, b) => b.excess_ratio - a.excess_ratio)
    .slice(0, 8);

  return (
    <>
      {/* ── hero ───────────────────────────────────────────────────────── */}
      <section className="mb-14 animate-fade-up">
        <Pill tone="accent" className="mb-5">
          <span className="inline-block h-1.5 w-1.5 animate-pulse-dot rounded-full bg-[var(--accent)]" />
          {num(o.corridors_tested)} corridors tested · FDR 5%
        </Pill>

        <h1 className="max-w-4xl text-balance text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl lg:text-[3.4rem]">
          Where is the{" "}
          <span className="text-[var(--accent)]">planner wrong</span>?
        </h1>

        <p className="mt-5 max-w-2xl text-pretty text-lg leading-relaxed text-[var(--ink-muted)]">
          A production routing engine estimates how long every freight leg
          should take. Across {num(o.legs)} real legs it is wrong in one
          direction almost every time — so we found{" "}
          <strong className="font-semibold text-[var(--ink)]">exactly where</strong>.
        </p>

        <div className="mt-7 flex flex-wrap gap-3">
          <Link
            href="/network/"
            className="rounded-lg bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Open the map
          </Link>
          <Link
            href="/evidence/"
            className="rounded-lg border border-[var(--line)] px-5 py-2.5 text-sm font-semibold transition-colors hover:border-[var(--ink-faint)]"
          >
            See the results
          </Link>
        </div>
      </section>

      {/* ── the map, as the front door ─────────────────────────────────── */}
      <Section className="mb-14">
        <HeroMap corridors={worst} />
      </Section>

      {/* ── four headline numbers ──────────────────────────────────────── */}
      <Section
        title="The finding"
        description="If the error were random it would cancel out across a corridor. It does not — so it concentrates, and it can be found."
      >
        <KpiRow>
          <Kpi
            value={pct(o.share_over_plan, 1)}
            label="of legs run over plan"
            sub={`The median leg takes ${ratio(o.median_ratio)} its planned time.`}
            file="benchmarks/raw/w1_leg_summary.csv"
            accent
          />
          <Kpi
            value={num(o.bottlenecks)}
            label="corridors significantly slower"
            sub={`of ${num(o.corridors_tested)} tested, at a 5% false discovery rate`}
            file="benchmarks/raw/w2_corridor_audit.csv"
          />
          <Kpi
            value={num(o.faster_corridors)}
            label="corridors significantly faster"
            sub="The planner is not uniformly optimistic — it is wrong in both directions."
            file="benchmarks/raw/w2_corridor_audit.csv"
          />
          <Kpi
            value={`${num(model.data.headline.mae_min, 2)} min`}
            label="best model error"
            sub={`against a ${num(model.data.headline.baseline_mae_min, 2)}-minute per-corridor median baseline`}
            file="benchmarks/raw/w7_model_metrics_v2_stepsize.csv"
          />
        </KpiRow>
      </Section>

      {/* ── the premise, drawn ─────────────────────────────────────────── */}
      <Section
        title="The premise, in one chart"
        description={
          <>
            Realised time ÷ planned time, across every leg. If the planner&apos;s
            error were noise it would centre on 1.0 and cancel out. It does not
            centre and it does not cancel — so it has to concentrate somewhere.
          </>
        }
        actions={<Evidence file="benchmarks/raw/w1_leg_summary.csv" />}
      >
        <Card>
          <GapHistogram
            bins={o.histogram}
            median={o.median_ratio}
            clipAt={o.clip_at}
            aboveClip={o.share_above_clip}
          />
        </Card>
      </Section>

      {/* ── the three-act story ────────────────────────────────────────── */}
      <Section
        title="Audit → Predict → Act"
        description="Three layers, causally connected. Each one exists because the one below it produced something to act on."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <StoryCard
            step="01"
            title="Audit"
            body={
              <>
                Every corridor with at least ten legs is tested against the rest
                of the network — Welch&apos;s t-test on log time ratios, with
                Benjamini–Hochberg control at 5%. That turns &ldquo;this corridor
                looks unreliable&rdquo; into a false-discovery-controlled claim.
              </>
            }
            stat={`${num(o.bottlenecks)} slower · ${num(o.faster_corridors)} faster`}
            href="/corridors/"
            cta="See the audit"
          />
          <StoryCard
            step="02"
            title="Predict"
            body={
              <>
                A gradient-boosted model learns the residual over each
                corridor&apos;s own median — the baseline an honest MAE table has
                to beat. It wins on all fourteen evaluation slices, with most of
                the margin on corridors nobody has seen before.
              </>
            }
            stat={`${minutes(model.data.headline.mae_min)} error vs ${minutes(model.data.headline.osrm_mae_min)} for the planner`}
            href="/predict/"
            cta="Try a prediction"
          />
          <StoryCard
            step="03"
            title="Act"
            body={
              <>
                Five agents consume that intelligence: they read freight
                paperwork, file orders, triage live delay alerts, audit invoices
                and answer questions. Every verdict is computed; the language
                model only writes the sentence.
              </>
            }
            stat="5 agents + an orchestrator, each scored"
            href="/agents/"
            cta="Meet the workforce"
          />
        </div>
      </Section>

      {/* ── worst corridors, as a teaser ───────────────────────────────── */}
      <Section
        title="The worst corridors in the network"
        description="Ranked by how much more a corridor overruns than the network typically does. The leg count matters — a 13.9× on 13 legs is a lead, not a verdict."
        actions={<ArrowLink href="/corridors/">All {num(o.corridors_tested)} corridors</ArrowLink>}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {worst.slice(0, 6).map((c, i) => (
            <Card key={c.id} className="flex items-center gap-4 py-3.5">
              <span className="tabular w-6 shrink-0 font-mono text-sm text-[var(--ink-faint)]">
                {i + 1}
              </span>
              <span
                aria-hidden
                className="h-8 w-1 shrink-0 rounded-full"
                style={{ background: c.severity.color }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {c.src.city ?? c.src.code} → {c.dst.city ?? c.dst.code}
                  {c.intra_city && (
                    <span className="ml-2 text-xs font-normal text-[var(--ink-faint)]">
                      intra-city
                    </span>
                  )}
                </p>
                <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
                  {c.src.state ?? "—"} · {num(c.n_legs)} legs ·{" "}
                  {minutes(c.median_gap_min)} typically late
                </p>
              </div>
              <span className="tabular shrink-0 font-mono text-base font-semibold">
                {ratio(c.excess_ratio)}
              </span>
            </Card>
          ))}
        </div>
      </Section>

      {/* ── the honest note ────────────────────────────────────────────── */}
      <Section>
        <Card className="border-dashed">
          <h3 className="text-sm font-semibold">What this does not claim</h3>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--ink-muted)]">
            Not &ldquo;beats the planner&rdquo;. The routing engine has no access
            to corridor history, so a model that has seen it is not a fair
            comparison — every model result here is reported against the
            per-corridor median instead. The agents operate on synthetic
            documents and a mock TMS, declared as scaffolding. The{" "}
            {num(o.legs)} legs underneath are real.
          </p>
          <div className="mt-3">
            <ArrowLink href="/about/">Honest scope in full</ArrowLink>
          </div>
        </Card>
      </Section>

      <p className="text-center text-xs text-[var(--ink-faint)]">
        Built on {num(o.legs)} real freight journeys recorded across India,
        September–October 2018.
      </p>
    </>
  );
}

function StoryCard({
  step,
  title,
  body,
  stat,
  href,
  cta,
}: {
  step: string;
  title: string;
  body: React.ReactNode;
  stat: string;
  href: string;
  cta: string;
}) {
  return (
    <Card className="flex flex-col">
      <span className="font-mono text-xs text-[var(--ink-faint)]">{step}</span>
      <h3 className="mt-1 text-lg font-semibold tracking-tight">{title}</h3>
      <p className="mt-2 flex-1 text-sm leading-relaxed text-[var(--ink-muted)]">
        {body}
      </p>
      <p className="tabular mt-4 border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--ink)]">
        {stat}
      </p>
      <div className="mt-3">
        <ArrowLink href={href}>{cta}</ArrowLink>
      </div>
    </Card>
  );
}
