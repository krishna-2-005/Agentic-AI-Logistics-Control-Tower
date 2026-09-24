import type { Metadata } from "next";

import { AlertFeed } from "@/components/AlertFeed";
import { Kpi, KpiRow, Notice, PageHeader, Section } from "@/components/ui";
import { getAlertsSample, getEvidence } from "@/lib/data";
import { frozen } from "@/lib/data";
import { num, pct } from "@/lib/format";

export const metadata: Metadata = {
  title: "Live alerts",
  description:
    "What the control tower would page someone about, and how good those pages actually are.",
};

export default function AlertsPage() {
  const sample = getAlertsSample();
  const evidence = getEvidence();

  const precision = frozen(evidence.data, "exception_precision_as_of") as number;
  const scoringRate = frozen(evidence.data, "stream_scoring_eps") as number;
  const latency = frozen(evidence.data, "stream_latency_p50_s") as number;
  const events = frozen(evidence.data, "stream_events") as number;

  return (
    <>
      <PageHeader
        eyebrow="Predict"
        title="The alert stream"
        lede={
          <>
            Shipment events are scored as they arrive, and the ones predicted to
            run late become alerts an agent acts on — notifying the customer and
            filing a ticket. This is what a duty operator would see.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={num(events)}
            label="events replayed end to end"
            sub="nothing dropped"
            file="benchmarks/raw/w5_stream_throughput_full.json"
          />
          <Kpi
            value={`${num(scoringRate, 0)}/s`}
            label="saturated scoring rate"
            sub="sustained, with nothing queued or dropped"
            accent
          />
          <Kpi
            value={`${num(latency, 1)} s`}
            label="event to alert, median"
            sub="from the event arriving to the alert being raised"
          />
          <Kpi
            value={pct(precision, 1)}
            label="notification precision"
            sub="against 54.1% if you simply alerted on every leg"
            file="benchmarks/raw/w8_replay_leakage.json"
          />
        </KpiRow>
      </Section>

      {/* The correction is stated where the number lives, not in a footnote. */}
      <Section>
        <Notice tone="warn" title="This number was corrected downward, publicly">
          The first measurement said 72.1%. It came from a replay that scored
          the <em>earliest</em> 2,000 legs against history from the{" "}
          <em>end</em> of the data — 1,290 of them had no corridor history at
          their own creation time but were handed fourteen prior legs. Measured
          honestly the precision is {pct(precision, 1)}, and the gain over
          alerting on everything is 4.5 points rather than 18. A replay leak
          that inflates a headline is better found by us than by a reviewer.
        </Notice>
      </Section>

      <Section
        title="The feed"
        description="Severity is computed from the predicted gap, never generated. Precision rises monotonically with grade, which is the whole reason the grade exists."
      >
        <AlertFeed sample={sample.data} />
      </Section>
    </>
  );
}
