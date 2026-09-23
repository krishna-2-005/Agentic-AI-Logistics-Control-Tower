import type { Metadata } from "next";

import { ArrowLink, Card, PageHeader, Section } from "@/components/ui";
import { getEvidence, getOverview } from "@/lib/data";
import { REPO_URL } from "@/lib/repo";
import { num } from "@/lib/format";

export const metadata: Metadata = {
  title: "About",
  description:
    "How this was built, what it does not claim, and what every term on the site means.",
};

const TEAM = [
  {
    name: "Sai Krishna",
    track: "AI Agents & Automation",
    work: "The five agents, the orchestrator, the MCP server, the document corpus, this frontend.",
  },
  {
    name: "Lahari",
    track: "ML & Evaluation",
    work: "The corridor audit, every baseline and model, the evaluation harnesses, the paper.",
  },
  {
    name: "Mounika",
    track: "Data & Systems",
    work: "Cleaning, trip reconstruction, the feature pipeline, Kafka and streaming, the mock TMS, deployment.",
  },
];

const GLOSSARY = [
  {
    term: "Leg",
    definition:
      "One origin-to-destination journey. The raw data is scan-level segments; a leg is all the segments of one journey collapsed into a single row.",
  },
  {
    term: "Corridor",
    definition:
      "A named pair of facilities — everything that travels from A to B. Keyed by centre code rather than city name, because a code is never null and never spelled two ways.",
  },
  {
    term: "Dwell",
    definition:
      "Time a shipment spends parked at a facility rather than moving. Measured as the scan-to-scan interval minus the realised moving time.",
  },
  {
    term: "Support",
    definition:
      "How many legs a corridor's statistic rests on. A 13.9× overrun on 13 legs and a 1.5× on 100 are not equally trustworthy, so every ranked row prints it.",
  },
  {
    term: "Excess ratio",
    definition:
      "How much more this corridor overruns its plan than the network typically does. 1.0 means exactly as much; above is worse, below is better.",
  },
  {
    term: "FDR (false discovery rate)",
    definition:
      "Test 1,130 corridors at a 5% significance level and about 56 will look significant by luck alone. Benjamini–Hochberg control instead caps the share of false findings among those reported at 5%.",
  },
  {
    term: "Residual",
    definition:
      "What is left after subtracting a baseline. This model predicts the residual over each corridor's own median, so learning nothing reproduces the strongest baseline rather than a weaker one.",
  },
  {
    term: "MAE",
    definition:
      "Mean absolute error — the average size of a mistake in minutes. It is minimised by the median, which is why the median is the bar a model here has to beat.",
  },
  {
    term: "As-of",
    definition:
      "A feature computed only from journeys that had already finished when the leg being predicted was created. The alternative leaks the future into the past.",
  },
];

export default function AboutPage() {
  const o = getOverview().data;
  const evidence = getEvidence();

  return (
    <>
      <PageHeader
        eyebrow="Evidence"
        title="About this project"
        lede={
          <>
            An eight-week team project over Delhivery&apos;s public trip
            records: a distributed pipeline that localises where a production
            routing engine is wrong, and an agent layer that acts on what it
            finds.
          </>
        }
      />

      {/* ── architecture ─────────────────────────────────────────────── */}
      <Section
        title="How it fits together"
        description="Four planes. Each exists because the one below it produced something worth acting on."
      >
        <Card>
          <div className="space-y-2.5">
            {[
              {
                n: "Agent plane",
                d: "Five LangGraph agents and an orchestrator, reaching the pipeline through an MCP tool server.",
                c: "#4d9fff",
              },
              {
                n: "Real-time plane",
                d: "Kafka producer → Spark Structured Streaming → broadcast feature join → model → alert stream.",
                c: "#2a78d6",
              },
              {
                n: "Intelligence plane",
                d: "MLlib models on the corridor-median residual, plus the audit statistics and an auto-retraining loop.",
                c: "#e34948",
              },
              {
                n: "Data plane",
                d: "Raw CSV → Spark cleaning → trip reconstruction → cached Parquet → as-of feature tables → vector index.",
                c: "#a02726",
              },
            ].map((layer) => (
              <div
                key={layer.n}
                className="flex gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3"
              >
                <span
                  aria-hidden
                  className="w-1 shrink-0 rounded-full"
                  style={{ background: layer.c }}
                />
                <div>
                  <p className="text-sm font-medium">{layer.n}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-[var(--ink-muted)]">
                    {layer.d}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── honest scope ─────────────────────────────────────────────── */}
      <Section title="Honest scope">
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <h3 className="text-sm font-semibold">What is real</h3>
            <ul className="mt-2.5 space-y-2 text-sm leading-relaxed text-[var(--ink-muted)]">
              <li>
                {num(o.legs)} legs reconstructed from 144,867 real scan records
                across a national freight network.
              </li>
              <li>
                Every corridor statistic, model number and streaming measurement
                on this site, each traceable to a file.
              </li>
              <li>
                Kafka has run against a live broker; the MCP server has been
                driven by a real client over stdio.
              </li>
            </ul>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold">What is scaffolding</h3>
            <ul className="mt-2.5 space-y-2 text-sm leading-relaxed text-[var(--ink-muted)]">
              <li>
                The documents the agents read are synthetic, generated with
                deliberately seeded errors so extraction can be scored.
              </li>
              <li>
                The TMS the agents book into is a mock FastAPI service — though
                its 1,657 facility codes are the real ones.
              </li>
              <li>
                No real alert has ever been sent. The email and Telegram
                channels are implemented and unconfigured, because no credential
                was committed to the repository.
              </li>
            </ul>
          </Card>
        </div>

        <Card className="mt-4 border-dashed">
          <h3 className="text-sm font-semibold">
            Two things this project got wrong, and fixed in public
          </h3>
          <div className="mt-2.5 space-y-3 text-sm leading-relaxed text-[var(--ink-muted)]">
            <p>
              <strong className="text-[var(--ink)]">
                A default that disabled the objective.
              </strong>{" "}
              The gradient-booster was chosen for absolute loss, then run at a
              step size where its corrective trees could move a prediction by at
              most ten minutes in total. The loss it was picked for was barely
              switched on. Fixing the step size took the error from 32.52 to
              30.90 minutes.
            </p>
            <p>
              <strong className="text-[var(--ink)]">
                An evaluation that leaked the future.
              </strong>{" "}
              Alert precision was published at 72.1%. The replay scored the
              earliest legs against history from the end of the data — most of
              them had no history at all at the time they claimed to. Measured
              honestly it is 58.6%, and that is the number reported everywhere
              on this site.
            </p>
          </div>
        </Card>
      </Section>

      {/* ── glossary ─────────────────────────────────────────────────── */}
      <Section
        title="Glossary"
        description="Every term this site uses, in plain English."
      >
        <div className="grid gap-3 md:grid-cols-2">
          {GLOSSARY.map((g) => (
            <div
              key={g.term}
              className="rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] p-4"
            >
              <p className="text-sm font-semibold">{g.term}</p>
              <p className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]">
                {g.definition}
              </p>
            </div>
          ))}
        </div>
      </Section>

      {/* ── team ─────────────────────────────────────────────────────── */}
      <Section title="The team">
        <div className="grid gap-4 md:grid-cols-3">
          {TEAM.map((m) => (
            <Card key={m.name}>
              <p className="text-sm font-semibold">{m.name}</p>
              <p className="mt-0.5 text-xs text-[var(--accent)]">{m.track}</p>
              <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">
                {m.work}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      <Section>
        <Card>
          <h3 className="text-sm font-semibold">Read further</h3>
          <div className="mt-3 flex flex-col gap-2">
            <ArrowLink href={`${REPO_URL}/blob/main/docs/paper_draft.md`} external>
              The paper draft
            </ArrowLink>
            <ArrowLink href={`${REPO_URL}/blob/main/docs/decisions.md`} external>
              The decision log — every choice, and why
            </ArrowLink>
            <ArrowLink href={`${REPO_URL}/blob/main/docs/problems.md`} external>
              The problems log — every bug and what it cost
            </ArrowLink>
            <ArrowLink href={REPO_URL} external>
              The repository
            </ArrowLink>
          </div>
          <p className="mt-4 border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--ink-faint)]">
            results freeze {evidence.freeze} · {evidence.data.n_values} values ·
            academic coursework · Delhivery dataset under its original licence
          </p>
        </Card>
      </Section>
    </>
  );
}
