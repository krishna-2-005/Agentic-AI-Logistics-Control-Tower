import type { Metadata } from "next";

import { HubExplorer } from "@/components/HubExplorer";
import { Kpi, KpiRow, PageHeader, Section } from "@/components/ui";
import { getHubs } from "@/lib/data";
import { minutes, num, pct } from "@/lib/format";

export const metadata: Metadata = {
  title: "Hub friction",
  description:
    "Which facilities hold shipments longest — dwell is a third of a leg's wall clock.",
};

export default function HubsPage() {
  const hubs = getHubs();
  const rows = hubs.data;

  const medianDwell = median(
    rows.map((h) => h.median_dwell_min).filter((v): v is number => v !== null)
  );
  const medianShare = median(
    rows.map((h) => h.dwell_share).filter((v): v is number => v !== null)
  );

  return (
    <>
      <PageHeader
        eyebrow="Network"
        title="Where shipments sit still"
        lede={
          <>
            A leg&apos;s realised time is moving time. The gap between scans is
            something else — the shipment parked at a facility. Across the
            network that dwell is about a third of the wall clock, which makes
            it worth ranking on its own.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={num(rows.length)}
            label="hubs ranked"
            sub="of 1,657 facilities — those with at least 30 outbound legs"
            file="benchmarks/raw/w2_hub_dwell.csv"
          />
          <Kpi
            value={minutes(medianDwell)}
            label="median hub dwell"
            sub="per outbound leg"
            accent
          />
          <Kpi
            value={pct(medianShare, 1)}
            label="of wall clock is dwell"
            sub="time parked rather than moving"
          />
          <Kpi
            value="2"
            label="metrics that disagree"
            sub="ranking by share and by minutes give different worst hubs"
          />
        </KpiRow>
      </Section>

      <Section
        title="The leaderboard"
        description={
          <>
            Two honest rankings of the same data. By dwell <em>share</em> the
            worst hub is the one that spends the largest fraction of its legs
            parked; by dwell <em>minutes</em> it is the one that parks them
            longest. They do not agree, and the difference is not cosmetic — the
            project&apos;s own assistant once answered this question with the
            wrong metric and had to be corrected.
          </>
        }
      >
        <HubExplorer hubs={rows} />
      </Section>
    </>
  );
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}
