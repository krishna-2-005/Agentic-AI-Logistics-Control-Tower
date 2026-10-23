import type { Metadata } from "next";

import { AlertFeed } from "@/components/AlertFeed";
import {
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
import { getAlertsSample, getEvidence } from "@/lib/data";
import { frozen } from "@/lib/data";
import { num, pct } from "@/lib/format";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("Alert replay", "A recorded run of the alert stream: what the control tower would page someone about, and how good those pages actually are.");

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
        title="Alert replay"
        lede={
          <>
            Shipment events are scored as they arrive, and the ones predicted to
            run late become alerts an agent acts on — notifying the customer and
            filing a ticket. This page replays a <strong>recorded</strong> run of
            that stream; it is not a feed of today&apos;s shipments.
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
        title="The recorded feed"
        description={`Severity is computed from the predicted gap, never generated. Precision rises monotonically with grade, which is the whole reason the grade exists. The run raised ${num(sample.data.run.alerts)} alerts; the table shows a sample of them, explained below it.`}
      >
        <AlertFeed sample={sample.data} />
        <p className="mt-3 text-xs leading-relaxed text-[var(--ink-muted)]">
          {sample.data.sample_note}
        </p>
      </Section>

      {sample.data.delivery.length > 0 && (
        <Section
          title="Did anyone actually receive one?"
          description="Yes, once, deliberately. The agent sent the three most severe alerts of this same recorded run to a real Telegram chat and a real mailbox, and kept the provider's receipt for each."
          actions={<Evidence file="benchmarks/raw/f2_alert_channel_live.json" />}
        >
          <TableShell>
            <thead>
              <tr>
                <Th align="left">Channel</Th>
                <Th align="right">Candidates</Th>
                <Th align="right">Sent</Th>
                <Th align="right">Failed</Th>
                <Th align="right">Held back by the cap</Th>
              </tr>
            </thead>
            <tbody>
              {sample.data.delivery.map((d) => (
                <tr key={d.channel}>
                  <Td className="capitalize">{d.channel}</Td>
                  <Td align="right" mono>{num(d.candidates)}</Td>
                  <Td align="right" mono>{num(d.sent)}</Td>
                  <Td align="right" mono>{num(d.failed)}</Td>
                  <Td align="right" mono>{num(d.suppressed_by_cap)}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
          <p className="mt-3 text-xs leading-relaxed text-[var(--ink-muted)]">
            Three per channel is a cap on purpose: the run proves the channel
            works without paging a person {num(sample.data.run.alerts)} times.
            Identifiers in the committed receipts are masked.
          </p>
        </Section>
      )}
    </>
  );
}
