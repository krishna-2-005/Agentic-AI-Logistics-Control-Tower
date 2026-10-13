"use client";

import { useMemo, useState } from "react";

import { Card, Pill } from "@/components/ui";
import { cx } from "@/lib/format";
import type { PromptAgent } from "@/lib/types";

/**
 * A viewer with a real diff between versions.
 *
 * The line-level diff is deliberately simple -- a longest-common-subsequence
 * over lines. It is enough to see what changed between v1 and v2 of a prompt,
 * which is the only question this page needs to answer.
 */
function diffLines(a: string, b: string) {
  const A = a.split("\n");
  const B = b.split("\n");
  const n = A.length;
  const m = B.length;

  // LCS table. Prompts are a few hundred lines, so the quadratic table is fine.
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0)
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: { kind: "same" | "add" | "del"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      out.push({ kind: "same", text: A[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "del", text: A[i] });
      i++;
    } else {
      out.push({ kind: "add", text: B[j] });
      j++;
    }
  }
  while (i < n) out.push({ kind: "del", text: A[i++] });
  while (j < m) out.push({ kind: "add", text: B[j++] });
  return out;
}

/** Folder names are how the repository stores these; a reader wants the agent. */
const AGENT_NAMES: Record<string, string> = {
  analytics_assistant: "Analytics Assistant",
  doc_extraction: "Document Intelligence",
  exception_triage: "Tracking & Exception",
  invoice_audit: "Invoice Auditor",
  order_entry: "Order Entry",
};

function agentName(slug: string): string {
  return (
    AGENT_NAMES[slug] ??
    slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function PromptLibrary({ agents }: { agents: PromptAgent[] }) {
  const [agentIdx, setAgentIdx] = useState(0);
  const [mode, setMode] = useState<"read" | "diff">("read");
  const [versionIdx, setVersionIdx] = useState(0);

  const agent = agents[agentIdx];
  const versions = agent?.versions ?? [];
  const canDiff = versions.length > 1;

  const diff = useMemo(() => {
    if (!canDiff) return [];
    return diffLines(versions[0].text, versions[versions.length - 1].text);
  }, [versions, canDiff]);

  const added = diff.filter((d) => d.kind === "add").length;
  const removed = diff.filter((d) => d.kind === "del").length;

  if (!agent) return null;

  return (
    <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
      {/* ── agent list ───────────────────────────────────────────────── */}
      <nav className="space-y-1">
        {agents.map((a, i) => (
          <button
            key={a.agent}
            onClick={() => {
              setAgentIdx(i);
              setVersionIdx(0);
              setMode("read");
            }}
            className={cx(
              "flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors",
              i === agentIdx
                ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                : "text-[var(--ink-muted)] hover:bg-[var(--surface-raised)] hover:text-[var(--ink)]"
            )}
          >
            <span className="truncate text-[13px]">{agentName(a.agent)}</span>
            <span className="tabular shrink-0 text-[10px] text-[var(--ink-faint)]">
              {a.versions.length === 1
                ? "1 version"
                : `${a.versions.length} versions`}
            </span>
          </button>
        ))}
      </nav>

      {/* ── viewer ───────────────────────────────────────────────────── */}
      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--line)] bg-[var(--surface-sunken)] px-4 py-2.5">
          <div className="flex rounded-lg border border-[var(--line)] p-0.5">
            {versions.map((v, i) => (
              <button
                key={v.version}
                onClick={() => {
                  setVersionIdx(i);
                  setMode("read");
                }}
                className={cx(
                  "rounded-md px-2.5 py-1 font-mono text-xs transition-colors",
                  mode === "read" && i === versionIdx
                    ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
                )}
              >
                {v.version}
              </button>
            ))}
          </div>

          {canDiff && (
            <button
              onClick={() => setMode("diff")}
              className={cx(
                "rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
                mode === "diff"
                  ? "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
              )}
            >
              diff {versions[0].version} → {versions[versions.length - 1].version}
            </button>
          )}

          {mode === "diff" && (
            <div className="ml-auto flex gap-1.5">
              <Pill tone="good" className="font-mono text-[10px]">
                +{added}
              </Pill>
              <Pill tone="warn" className="font-mono text-[10px]">
                −{removed}
              </Pill>
            </div>
          )}
        </div>

        <div className="max-h-[36rem] overflow-auto">
          {mode === "read" ? (
            <pre className="whitespace-pre-wrap px-4 py-4 font-mono text-[12px] leading-relaxed text-[var(--ink-muted)]">
              {versions[versionIdx]?.text}
            </pre>
          ) : (
            <div className="font-mono text-[12px] leading-relaxed">
              {diff.map((d, i) => (
                <div
                  key={i}
                  className={cx(
                    "whitespace-pre-wrap px-4",
                    d.kind === "add" &&
                      "bg-emerald-500/10 text-emerald-300 before:content-['+_']",
                    d.kind === "del" &&
                      "bg-red-500/10 text-red-300 line-through opacity-70 before:content-['−_']",
                    d.kind === "same" && "text-[var(--ink-faint)]"
                  )}
                >
                  {d.text || " "}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
