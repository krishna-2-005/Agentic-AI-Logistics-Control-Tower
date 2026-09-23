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
        title="How late will this leg run?"
        lede={
          <>
            Pick a corridor and a departure, and the model predicts the gap
            between the planned time and the realised one. It answers with{" "}
            <strong className="font-semibold text-[var(--ink)]">
              which model scored the request
            </strong>
            , because the model this project reports and the model it serves are
            not the same one.
          </>
        }
      />

      <Section>
        <Notice tone="warn" title="Served model, not the reported model">
          {model.data.headline.served_note} So this page answers with the{" "}
          {model.data.headline.served_model} — a genuinely weaker model than the{" "}
          {num(model.data.headline.mae_min, 2)}-minute one on the results page.
          Saying so here is cheaper than a footnote nobody reads.
        </Notice>
      </Section>

      <Predictor corridors={options} />
    </>
  );
}
