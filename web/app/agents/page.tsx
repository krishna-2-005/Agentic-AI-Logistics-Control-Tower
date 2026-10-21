import type { Metadata } from "next";

import { AgentConsole } from "@/components/AgentConsole";
import {
  Card,
  Evidence,
  Notice,
  PageHeader,
  Pill,
  Section,
  TableShell,
  Td,
  Th,
} from "@/components/ui";
import { getAgents, getMcpTranscript } from "@/lib/data";
import { interval, num, pct } from "@/lib/format";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("Agent workforce", "Five agents and an orchestrator, each measured against a trivial policy on its own set.");

export default function AgentsPage() {
  const agents = getAgents();
  const mcp = getMcpTranscript();
  const { agents: cards, orchestrator, ablation } = agents.data;

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

      <Section
        title="The five agents"
        description="Each card gives the metric, the number of cases behind it, a 95% Wilson interval and the score of the trivial policy on the same set."
      >
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

              <p className="mt-3 text-sm leading-relaxed text-[var(--ink-muted)]">
                {a.one_liner}
              </p>

              <div className="mt-4 flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3">
                <p className="tabular text-xl font-semibold">
                  {pct(a.score.rate, 1)}
                </p>
                <p className="mt-0.5 text-xs font-medium">{a.score.label}</p>
                <p className="tabular mt-1 font-mono text-[11px] text-[var(--ink-muted)]">
                  {num(a.score.successes)} of {num(a.score.total)} {a.score.unit}
                  {" · "}95% CI {interval(a.score.ci_low, a.score.ci_high)}
                </p>
                <p className="mt-2 border-t border-[var(--line)] pt-2 text-[11px] text-[var(--ink-muted)]">
                  <strong className="font-semibold text-[var(--ink)]">
                    Trivial policy ({a.baseline.label}):
                  </strong>{" "}
                  <span className="tabular font-mono">
                    {pct(a.baseline.value, 1)}
                  </span>
                  {a.baseline.note ? ` — ${a.baseline.note}` : ""}
                </p>
                <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--ink-muted)]">
                  {a.score.note}
                </p>
                {a.also && a.also.length > 0 && (
                  <ul className="mt-2 space-y-1.5 border-t border-[var(--line)] pt-2">
                    {a.also.map((r) => (
                      <li
                        key={r.label}
                        className="text-[11px] leading-relaxed text-[var(--ink-muted)]"
                      >
                        <span className="font-medium text-[var(--ink)]">
                          {r.label}:
                        </span>{" "}
                        <span className="tabular font-mono">
                          {pct(r.rate, 1)} ({num(r.successes)}/{num(r.total)},{" "}
                          {interval(r.ci_low, r.ci_high)})
                        </span>
                        {r.historical && (
                          <Pill tone="warn" className="ml-1.5 !px-1.5 !py-0 text-[10px]">
                            historical
                          </Pill>
                        )}
                        {r.note ? ` ${r.note}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
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

      <Section
        title="The orchestrator"
        description={orchestrator.note}
        actions={<Evidence file={orchestrator.file} />}
      >
        <Card>
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
            <div>
              <p className="tabular text-xl font-semibold">
                {pct(orchestrator.routed.rate, 1)}
              </p>
              <p className="text-xs font-medium">routed as the email deserved</p>
              <p className="tabular mt-1 font-mono text-[11px] text-[var(--ink-muted)]">
                {num(orchestrator.routed.successes)} of{" "}
                {num(orchestrator.routed.total)} lifecycles · 95% CI{" "}
                {interval(orchestrator.routed.ci_low, orchestrator.routed.ci_high)}
              </p>
            </div>
            <p className="max-w-md text-[11px] leading-relaxed text-[var(--ink-muted)]">
              <strong className="font-semibold text-[var(--ink)]">
                Trivial policy ({orchestrator.baseline.label}):
              </strong>{" "}
              <span className="tabular font-mono">
                {pct(orchestrator.baseline.value, 1)}
              </span>{" "}
              — {orchestrator.baseline.note}. All {orchestrator.paths_exercised} graph
              paths were taken.
            </p>
          </div>
        </Card>
      </Section>

      {ablation && (
        <Section
          title="Ablation: what if the language model decided?"
          description={
            ablation.note ||
            "The same cases decided by code and by the language model, side by side."
          }
          actions={<Evidence file={ablation.file} />}
        >
          <TableShell>
            <thead>
              <tr>
                <Th align="left">Arm</Th>
                <Th align="right">Accuracy</Th>
                <Th align="right">95% CI</Th>
                <Th align="right">n</Th>
                <Th align="right">Unanimity</Th>
                <Th align="right">Cost</Th>
              </tr>
            </thead>
            <tbody>
              {ablation.arms.map((arm) => (
                <tr key={arm.name}>
                  <Td>{arm.name}</Td>
                  <Td align="right" mono>
                    {arm.accuracy === null ? "—" : pct(arm.accuracy, 1)}
                  </Td>
                  <Td align="right" mono>
                    {interval(arm.ci_low, arm.ci_high)}
                  </Td>
                  <Td align="right" mono>
                    {arm.n === null ? "—" : typeof arm.n === "number" ? num(arm.n) : arm.n}
                  </Td>
                  <Td align="right" mono>
                    {arm.unanimity === null ? "—" : pct(arm.unanimity, 1)}
                  </Td>
                  <Td align="right" mono>
                    {arm.cost === null
                      ? "—"
                      : `${typeof arm.cost === "number" ? num(arm.cost, Number.isInteger(arm.cost) ? 0 : 2) : arm.cost}${arm.cost_unit ? ` ${arm.cost_unit.replace(/_/g, " ")}` : ""}`}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        </Section>
      )}

      {/* ── the lifecycle ─────────────────────────────────────────────── */}
      <Section
        title="The lifecycle, end to end"
        description={`Watch one email travel the whole graph. The earlier ${orchestrator.earlier_cases}-email demonstration booked ${orchestrator.earlier_booked} orders and ran ${orchestrator.earlier_ticketed} all the way to an exception ticket.`}
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
