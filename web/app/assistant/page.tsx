import type { Metadata } from "next";

import { AssistantChat } from "@/components/AssistantChat";
import { Kpi, KpiRow, PageHeader, Section } from "@/components/ui";
import { getAssistantEval } from "@/lib/data";
import { pct } from "@/lib/format";

export const metadata: Metadata = {
  title: "Analytics assistant",
  description:
    "Ask the project about its own data — and watch it refuse what it cannot ground.",
};

export default function AssistantPage() {
  const evalData = getAssistantEval();
  const e = evalData.data;

  return (
    <>
      <PageHeader
        eyebrow="Agents"
        title="Ask the network a question"
        lede={
          <>
            It searches this project&apos;s own corridor, hub and document
            records. The interesting behaviour is not the answering — it is the{" "}
            <strong className="font-semibold text-[var(--ink)]">refusing</strong>
            : ask something the data cannot answer and it says so, rather than
            inventing a plausible reply.
          </>
        }
      />

      <Section>
        <KpiRow>
          <Kpi
            value={pct(e.no_llm?.route_accuracy, 0)}
            label="correct route"
            sub="chose the right way to answer on the fixed question set"
            file="benchmarks/raw/w7_assistant_run_no_llm.json"
            accent
          />
          <Kpi
            value={pct(e.groundedness?.rate_model_written, 1)}
            label="answers grounded"
            sub="every claim checked against the context it retrieved"
            file="benchmarks/raw/w7_groundedness_summary.json"
          />
          <Kpi
            value={`${e.groundedness?.out_of_scope_refused ?? 0} / ${e.groundedness?.out_of_scope_total ?? 0}`}
            label="out-of-scope refused"
            sub="questions the data cannot answer, correctly declined"
          />
          <Kpi
            value="30"
            label="questions in the test set"
            sub="fixed in advance, including six the data cannot answer"
          />
        </KpiRow>
      </Section>

      <AssistantChat />

      <Section
        title="What the judging found"
        description="Thirty answers were checked mechanically — every number against a rebuilt context — and then read by a person. The mechanical check found nothing; reading found both the real failure and a right answer that looked wrong."
        className="mt-10"
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-5">
            <p className="text-sm font-semibold text-amber-400">
              The one failure
            </p>
            <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">
              Asked how many corridors are statistically slower, the model
              counted the three it could see among its five retrieved passages
              and answered <strong>&ldquo;3&rdquo;</strong>. The network&apos;s
              answer is <strong>273</strong>. Every digit was in its context;
              the claim was not.
            </p>
          </div>
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/[0.06] p-5">
            <p className="text-sm font-semibold text-emerald-400">
              The answer that looked wrong and was right
            </p>
            <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">
              Asked which hub holds shipments longest, it answered{" "}
              <strong>Hubli</strong>, not the expected Aluva. It was correct —
              the question asks for dwell <em>time</em>, and the reviewer&apos;s
              own ranking had sorted by dwell <em>share</em>. The model caught a
              bug in the project.
            </p>
          </div>
        </div>
      </Section>
    </>
  );
}
