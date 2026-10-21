import type { Metadata } from "next";

import { Card, PageHeader, Section } from "@/components/ui";
import { getEvidence, getOverview, repoFileUrl } from "@/lib/data";
import { num } from "@/lib/format";
import { GLOSSARY } from "@/lib/glossary";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("About", "How this was built, what it does not claim, and what every term on the site means.");

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

export default function AboutPage() {
  const o = getOverview().data;
  const evidence = getEvidence();

  return (
    <>
      <PageHeader
        eyebrow="Results"
        title="About this project"
        lede={
          <>
            An eight-week team project over Delhivery&apos;s public trip
            records: a distributed pipeline that localises where the OSRM
            estimate recorded in the dataset is wrong, and an agent layer that
            acts on what it finds. What the dataset cannot tell us is how
            Delhivery itself used that estimate.
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
              <li>
                Real alerts have reached real people. The bot sent the three
                most severe alerts of the recorded run to a Telegram chat and,
                separately, to a mailbox, and the provider receipts are kept
                (identifiers masked) in{" "}
                <code className="font-mono text-xs">
                  benchmarks/raw/f2_alert_channel_live.json
                </code>
                .
              </li>
              <li>
                The delay model is the v2 residual gradient-boosted model, and
                the stream and the predictor serve exactly that model on
                event-time state.
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
                The public API is a free-tier host that replays the stream&apos;s
                recorded alerts. It does not run a live stream, and it sleeps
                when idle. The live Telegram and email run happened once,
                offline, with a cap of three alerts per channel.
              </li>
              <li>
                Nothing runs on AWS or any other paid cloud: the site is on
                Vercel and the API on Render, both on free plans.
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

      {/* ── model and data cards ─────────────────────────────────────── */}
      <Section
        title="Model and data cards"
        description="The two documents a reviewer reads first: what the model is for and how it fails, and what the data is and cannot support."
      >
        <div className="grid gap-4 md:grid-cols-2">
          {[
            {
              title: "Model card",
              file: "docs/model_card.md",
              body: "Intended use, training split, the 38 features, error by slice, the proof that the served model is the reported one, and six failure modes.",
            },
            {
              title: "Data card",
              file: "docs/data_card.md",
              body: "Source, the 144,867 records and what cleaning did to them, what a leg is, and what three weeks of one carrier's data cannot support.",
            },
          ].map((c) => (
            <a
              key={c.file}
              href={repoFileUrl(c.file)}
              target="_blank"
              rel="noreferrer"
              className="block rounded-xl border border-[var(--line)] bg-[var(--surface-raised)] p-4 transition-colors hover:border-[var(--accent)]"
            >
              <p className="text-sm font-semibold text-[var(--accent)]">{c.title} →</p>
              <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-muted)]">{c.body}</p>
            </a>
          ))}
        </div>
      </Section>

      {/* ── glossary ─────────────────────────────────────────────────── */}
      <Section
        title="Glossary"
        description="Every technical term this site uses, in plain English."
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
          <p className="text-sm leading-relaxed text-[var(--ink-muted)]">
            Every figure on this site is computed from the project&apos;s own
            measurements and checked against a frozen set of{" "}
            {evidence.data.n_values} values before each release, so a number
            here and a number in the write-up cannot drift apart.
          </p>
          <p className="mt-3 border-t border-[var(--line)] pt-3 text-xs text-[var(--ink-faint)]">
            Academic coursework · Delhivery dataset used under its original
            licence
          </p>
        </Card>
      </Section>
    </>
  );
}
