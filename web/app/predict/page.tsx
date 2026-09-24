import type { Metadata } from "next";

import { Predictor } from "@/components/Predictor";
import { Notice, PageHeader, Section } from "@/components/ui";
import { getCorridors, getModel } from "@/lib/data";
import { num } from "@/lib/format";

export const metadata: Metadata = {
  title: "Delay predictor",
  description: "Score a leg against the model the streaming pipeline serves.",
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
        <Notice
          tone="warn"
          title="This page uses an earlier model than the one in the results"
        >
          The best model needs a rolling view of each corridor&apos;s recent
          history, which the live service cannot build yet. So predictions here
          come from an earlier, slightly weaker model — about six minutes less
          accurate than the {num(model.data.headline.mae_min, 2)}-minute figure
          on the results page. Every answer says which model produced it.
        </Notice>
      </Section>

      <Predictor corridors={options} />
    </>
  );
}
