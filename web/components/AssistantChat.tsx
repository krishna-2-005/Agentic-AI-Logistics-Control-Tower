"use client";

import { useRef, useState } from "react";

import { Card, Notice, Pill } from "@/components/ui";
import { API_CONFIGURED, postAsk, type AskResponse } from "@/lib/api";
import { cx } from "@/lib/format";

const SUGGESTIONS = [
  "Which corridors are the worst bottlenecks?",
  "Which hub has the longest dwell time?",
  "How many corridors are significantly slower?",
  "What is the GST rate on road freight?",
];

interface Turn {
  question: string;
  answer?: AskResponse;
  error?: string;
  pending?: boolean;
}

const ROUTE_TONE: Record<string, "accent" | "good" | "warn" | "neutral"> = {
  table: "accent",
  retrieval: "good",
  refused: "warn",
};

export function AssistantChat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [useLlm, setUseLlm] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  async function ask(question: string) {
    if (!question.trim()) return;
    setInput("");
    const index = turns.length;
    setTurns((t) => [...t, { question, pending: true }]);

    const r = await postAsk(question, useLlm);
    setTurns((t) =>
      t.map((turn, i) =>
        i === index
          ? r.ok
            ? { question, answer: r.data }
            : { question, error: r.message }
          : turn
      )
    );
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  }

  return (
    <Card padded={false} className="overflow-hidden">
      {/* ── transcript ───────────────────────────────────────────────── */}
      <div className="max-h-[26rem] min-h-[14rem] overflow-y-auto p-5">
        {turns.length === 0 && (
          <div className="py-6 text-center">
            <p className="text-sm text-[var(--ink-muted)]">
              Ask about corridors, hubs, delays or the documents.
            </p>
            <p className="mt-1 text-xs text-[var(--ink-faint)]">
              The last suggestion is out of scope on purpose — it should be
              refused.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  className={cx(
                    "rounded-full border px-3 py-1.5 text-xs transition-colors",
                    i === SUGGESTIONS.length - 1
                      ? "border-amber-500/40 text-amber-400 hover:bg-amber-500/10"
                      : "border-[var(--line)] text-[var(--ink-muted)] hover:border-[var(--accent)]/50 hover:text-[var(--accent)]"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-5">
          {turns.map((t, i) => (
            <div key={i} className="animate-fade-up">
              <p className="text-sm font-medium">{t.question}</p>

              {t.pending && (
                <div className="mt-2 flex gap-1">
                  {[0, 1, 2].map((d) => (
                    <span
                      key={d}
                      className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-[var(--ink-faint)]"
                      style={{ animationDelay: `${d * 160}ms` }}
                    />
                  ))}
                </div>
              )}

              {t.answer && (
                <div className="mt-2 rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-1.5">
                    <Pill tone={ROUTE_TONE[t.answer.route] ?? "neutral"}>
                      {t.answer.route}
                    </Pill>
                    {!t.answer.used_llm && (
                      <Pill tone="neutral" className="font-mono text-[10px]">
                        no model call
                      </Pill>
                    )}
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {t.answer.answer}
                  </p>
                  {t.answer.sources?.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1">
                      {t.answer.sources.map((s, j) => (
                        <span
                          key={j}
                          className="rounded border border-[var(--line)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--ink-faint)]"
                        >
                          {s.label}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {t.error && (
                <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] px-3 py-2 text-xs text-[var(--ink-muted)]">
                  {t.error}
                </p>
              )}
            </div>
          ))}
        </div>
        <div ref={endRef} />
      </div>

      {/* ── composer ─────────────────────────────────────────────────── */}
      <div className="border-t border-[var(--line)] bg-[var(--surface-sunken)] p-3">
        {!API_CONFIGURED && (
          <Notice tone="replay" title="No assistant service on this build" className="mb-3">
            This static site has no API attached, so questions cannot be
            answered here. The scorecard above is the measured behaviour of the
            same assistant, and it needs no backend.
          </Notice>
        )}
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask(input)}
            disabled={!API_CONFIGURED}
            placeholder="Ask about the network…"
            className="flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] px-3 py-2 text-sm placeholder:text-[var(--ink-faint)] disabled:opacity-50"
          />
          <button
            onClick={() => ask(input)}
            disabled={!API_CONFIGURED || !input.trim()}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            Ask
          </button>
        </div>
        <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-[var(--ink-muted)]">
          <input
            type="checkbox"
            checked={useLlm}
            onChange={(e) => setUseLlm(e.target.checked)}
            disabled={!API_CONFIGURED}
            className="accent-[var(--accent)]"
          />
          Let the model phrase the answer
          <span className="text-[var(--ink-faint)]">
            — capped server-side; the free tier allows 20 calls a day
          </span>
        </label>
      </div>
    </Card>
  );
}
