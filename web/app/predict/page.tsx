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

  // A searchable picker needs the corridor's identity and label, nothing else.
  const options = corridors.data
    .map((c) => ({
      id: c.id,
      label: `${c.src.city ?? c.src.code} → ${c.dst.city ?? c.dst.code}`,
      state: c.src.state ?? "",
      legs: c.n_legs,
      km: c.mean_osrm_km,
    }))
    .sort((a, b) => b.legs - a.legs);

  return (
    <>
      <PageHeader
        eyebrow="Predict"
        title="How late will this journey run?"
        lede={
          <>
            Pick a lane and a departure, and the model estimates how far past
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
          The best model needs a rolling view of each lane&apos;s recent
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
