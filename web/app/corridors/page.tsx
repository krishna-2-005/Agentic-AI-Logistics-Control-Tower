import type { Metadata } from "next";

import { CorridorTable } from "@/components/CorridorTable";
import { Evidence, Kpi, KpiRow, PageHeader, Section } from "@/components/ui";
import { getCorridors, getCorridors30, getOverview } from "@/lib/data";
import { num, pct } from "@/lib/format";

export const metadata: Metadata = {
  title: "Corridor audit",
  description:
    "Every corridor tested against the rest of the network, with Benjamini–Hochberg control at 5%.",
};

export default function CorridorsPage() {
  const ten = getCorridors();
  const thirty = getCorridors30();
  const o = getOverview().data;

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
            so &ldquo;significant&rdquo; here means something specific.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={num(o.bottlenecks)}
            label="significantly slower"
            sub="corridors running over the network's own typical overrun"
            accent
          />
          <Kpi
            value={num(o.faster_corridors)}
            label="significantly faster"
            sub="the planner is pessimistic here, not optimistic"
          />
          <Kpi
            value={num(o.corridors_tested)}
            label="corridors tested"
            sub={`of ${num(o.corridors)} in the data — those with at least 10 legs`}
          />
          <Kpi
            value={pct(20739 / o.legs, 1)}
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
