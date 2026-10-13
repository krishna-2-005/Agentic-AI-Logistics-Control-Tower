import type { Metadata } from "next";

import { Predictor } from "@/components/Predictor";
import { Notice, PageHeader, Section } from "@/components/ui";
import { getCorridors, getModel } from "@/lib/data";
import { num } from "@/lib/format";

export const metadata: Metadata = {
  title: "Delay predictor",
  description: "Score a leg against the reported model the streaming pipeline serves.",
};

export default function PredictPage() {
  const corridors = getCorridors();
  const model = getModel();

  // A city pair does not identify a corridor. 70 of the significant ones run
  // between two facilities inside the same city, so several collapse to the
  // same "Bengaluru → Bengaluru" label and the picker showed what looked like
  // duplicate rows with different leg counts. Where a label repeats, the
  // facilities are named so the rows are telling apart.
  const labelled = corridors.data.map((c) => ({
    id: c.id,
    label: `${c.src.city ?? c.src.code} → ${c.dst.city ?? c.dst.code}`,
    facilities:
      c.src.facility && c.dst.facility
        ? `${c.src.facility} → ${c.dst.facility}`
        : "",
    state: c.src.state ?? "",
    legs: c.n_legs,
    km: c.mean_osrm_km,
  }));

  const seen = new Map<string, number>();
  labelled.forEach((o) => seen.set(o.label, (seen.get(o.label) ?? 0) + 1));

  const options = labelled
    .map((o) => ({
      ...o,
      // The centre code's last four characters are what distinguishes two
      // facilities in one city; the PIN prefix is shared.
      hint: (seen.get(o.label) ?? 0) > 1 ? o.facilities : "",
    }))
    .sort((a, b) => b.legs - a.legs);

  return (
    <>
      <PageHeader
        eyebrow="Predict"
        title="How late will this leg run?"
        lede={
          <>
            Pick a corridor and a departure, and the model estimates how far past
            its planned time the journey will actually take — the quantity the
            whole analysis is about.
          </>
        }
      />

      <Section>
        {model.data.headline.served_model === model.data.headline.model ? (
          <Notice tone="info" title="Scored by the model in the results">
            Predictions here come from the same model behind the{" "}
            {num(model.data.headline.mae_min, 2)}-minute figure on the results
            page. Each lane&apos;s rolling history is rebuilt from events as they
            arrive, and{" "}
            {model.data.headline.stream_equals_batch?.identical ?? 0} of{" "}
            {model.data.headline.stream_equals_batch?.legs ?? 0} sampled legs
            score exactly as they do offline. Every answer says which model
            produced it.
          </Notice>
        ) : (
          <Notice
            tone="warn"
            title="This page uses an earlier model than the one in the results"
          >
            {model.data.headline.served_note}
          </Notice>
        )}
      </Section>

      <Predictor corridors={options} />
    </>
  );
}
