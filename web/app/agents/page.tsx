import type { Metadata } from "next";

import { AgentConsole } from "@/components/AgentConsole";
import {
  Card,
  Evidence,
  Notice,
  PageHeader,
  Pill,
  Section,
} from "@/components/ui";
import { getAgents, getMcpTranscript } from "@/lib/data";
import { num, pct } from "@/lib/format";

export const metadata: Metadata = {
  title: "Agent workforce",
  description:
    "Five agents and an orchestrator, each measured against a trivial policy on its own set.",
};

export default function AgentsPage() {
  const agents = getAgents();
  const mcp = getMcpTranscript();
  const { agents: cards, orchestrator } = agents.data;

  return (
    <>
      <PageHeader
        eyebrow="Agents"
        title="A workforce that decides with arithmetic"
        lede={
          <>
            Five agents read paperwork, file orders, triage delay alerts, audit
            invoices and answer questions. Every verdict they reach is computed;
            a language model only writes the sentence a human reads — and each
            of them runs with the model switched off entirely.
          </>
        }
      />

      <Section>
        <Notice tone="info" title="Why the decisions are arithmetic, not generated">
          A verdict a language model produces can come out differently the next
          time it is asked, which makes it very hard to say how often the system
          is right. Here severity, invoice verdicts and routing are computed, so
          each one is repeatable — and therefore{" "}
          <strong>measurable</strong>. That is the trade behind every score on
          this page: less improvisation, in exchange for numbers that mean
          something.
        </Notice>
      </Section>

      <Section title="The five agents">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cards.map((a) => (
            <Card key={a.id} className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-base font-semibold tracking-tight">
                    {a.name}
                  </h3>
                  <p className="mt-0.5 text-xs text-[var(--ink-faint)]">
                    {a.role}
                  </p>
                </div>
                <Pill tone="neutral" className="shrink-0 font-mono text-[10px]">
                  {a.prompt_version}
                </Pill>
              </div>

              <p className="mt-3 flex-1 text-sm leading-relaxed text-[var(--ink-muted)]">
                {a.one_liner}
              </p>

              <div className="mt-4 rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3">
                <p className="tabular text-xl font-semibold">
                  {formatScore(a.id, a.score.value)}
                </p>
                <p className="mt-0.5 text-xs font-medium">{a.score.label}</p>
                <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--ink-muted)]">
                  {a.score.note}
                </p>
                <div className="mt-2">
                  <Evidence file={a.score.file} />
                </div>
              </div>

              <p className="mt-3 border-t border-[var(--line)] pt-2.5 text-[11px] leading-relaxed text-[var(--ink-faint)]">
                {a.deterministic}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      {/* ── the lifecycle ─────────────────────────────────────────────── */}
      <Section
        title="The lifecycle, end to end"
        description={`${orchestrator.note} Of ${orchestrator.cases} emails, ${orchestrator.booked} became booked orders and ${orchestrator.ticketed} ran all the way to an exception ticket.`}
        actions={<Evidence file={orchestrator.file} />}
      >
        <AgentConsole
          orchestrator={orchestrator}
          mcp={mcp.data}
          agents={cards}
        />
      </Section>
    </>
  );
}

function formatScore(id: string, value: number | null): string {
  if (value === null) return "—";
  if (id === "invoice") return `${num(value)} / 20`;
  if (id === "order") return pct(value, 0);
  return pct(value, 1);
}
