import type { Metadata } from "next";

import { CorridorTable } from "@/components/CorridorTable";
import { Evidence, Kpi, KpiRow, PageHeader, Section } from "@/components/ui";
import { frozen, getCorridors, getCorridors30, getEvidence, getOverview } from "@/lib/data";
import { num, pct } from "@/lib/format";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("Corridor audit", "Every corridor tested against the rest of the network, with Benjamini–Hochberg control at 5%.");

export default function CorridorsPage() {
  const ten = getCorridors();
  const thirty = getCorridors30();
  const o = getOverview().data;
  const legsCovered = frozen(getEvidence().data, "legs_covered") as number;

  // The headline claim of D-018: the two support floors do not merely rank the
  // same corridors differently, they describe different networks.
  const top20Ten = [...ten.data]
    .filter((c) => c.is_significant && c.direction === "worse")
    .sort((a, b) => b.excess_ratio - a.excess_ratio)
    .slice(0, 20)
    .map((c) => c.id);
  const top20Thirty = [...thirty.data]
    .filter((c) => c.is_significant && c.direction === "worse")
    .sort((a, b) => b.excess_ratio - a.excess_ratio)
    .slice(0, 20)
    .map((c) => c.id);
  const shared = top20Ten.filter((id) => top20Thirty.includes(id)).length;

  return (
    <>
      <PageHeader
        eyebrow="Network"
        title="The corridor audit"
        lede={
          <>
            Each corridor&apos;s legs are compared against the whole network
            using Welch&apos;s t-test on log time ratios. With{" "}
            {num(o.corridors_tested)} tests in one family, the
            Benjamini–Hochberg procedure holds the false discovery rate at 5% —
            on the assumption that legs are independent. They are not: legs of one recurring
            service resemble each other, so this list is a <strong>screening list</strong>.
            A placebo with meaningless corridor labels returns about{" "}
            {num(o.audit_placebo_discoveries)} &ldquo;discoveries&rdquo;, the dependence-aware
            test confirms {num(o.audit_robust_slower)}, and that test is correctly sized but
            finds only {pct(o.audit_cluster_power_shift_one, 0)} of corridors even when a
            2.7-fold overrun is planted (so its zero says little). What does hold is
            persistence: corridor means correlate at {num(o.stability_spearman, 2)} between the
            two halves of the period.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={num(o.bottlenecks)}
            label="flagged slower (screening)"
            sub="the standard test's list; the Robust column shows which survive the dependence-aware test"
            accent
          />
          <Kpi
            value={num(o.faster_corridors)}
            label="flagged faster (screening)"
            sub="the OSRM estimate looks pessimistic here, subject to the same caveat"
          />
          <Kpi
            value={num(o.corridors_tested)}
            label="corridors tested"
            sub={`of ${num(o.corridors)} in the data — those with at least 10 legs`}
          />
          <Kpi
            value={pct(legsCovered / o.legs, 1)}
            label="of legs covered"
            sub="the audit speaks for most of the network, not a busy core"
          />
        </KpiRow>
      </Section>

      {/* ── the instability, as a result ───────────────────────────────── */}
      <Section
        title="The support floor decides the answer"
        description={
          <>
            Raise the minimum from ten legs to thirty and the top-20 list shares{" "}
            <strong className="font-semibold text-[var(--ink)]">
              {shared === 0 ? "no corridor at all" : `${shared} corridors`}
            </strong>{" "}
            with the ten-leg list. The 30-leg table is metro — Mumbai, Delhi,
            Hyderabad — and reads as urban congestion. The 10-leg table is
            district feeders between towns. What the busy core suffers from and
            what the network&apos;s worst corridors suffer from are not the same
            thing.
          </>
        }
        actions={<Evidence file="benchmarks/raw/w2_support_sensitivity.csv" />}
      >
        <CorridorTable
          ten={ten.data}
          thirty={thirty.data}
          sharedTop20={shared}
        />
      </Section>
    </>
  );
}
