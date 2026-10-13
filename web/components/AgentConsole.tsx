"use client";

import { useEffect, useState } from "react";

import { Card, Notice, Pill, TableShell, Td, Th } from "@/components/ui";
import { API_CONFIGURED, getTraces, type TraceRow } from "@/lib/api";
import { cx, num } from "@/lib/format";
import type { AgentCard, AgentsData, McpTranscript } from "@/lib/types";

/**
 * The lifecycle drawn as a graph, plus whatever live trace the API can supply.
 *
 * The old page showed agent activity as a pandas DataFrame of trace rows --
 * accurate, and it told a visitor nothing about five autonomous agents. The
 * graph is the same information arranged so the three distinct paths through
 * the system are visible at a glance.
 */

const NODES = [
  { id: "email", label: "Email arrives", x: 0 },
  { id: "order", label: "Order Entry", x: 1 },
  { id: "tms", label: "Booked in TMS", x: 2 },
  { id: "stream", label: "Streaming score", x: 3 },
  { id: "exception", label: "Exception triage", x: 4 },
  { id: "ticket", label: "Ticket filed", x: 5 },
];

export function AgentConsole({
  orchestrator,
  mcp,
  agents,
}: {
  orchestrator: AgentsData["orchestrator"];
  mcp: McpTranscript;
  agents: AgentCard[];
}) {
  const [tab, setTab] = useState<"lifecycle" | "mcp" | "traces">("lifecycle");

  return (
    <>
      <div className="mb-4 flex rounded-lg border border-[var(--line)] p-0.5">
        {(
          [
            ["lifecycle", "Lifecycle"],
            ["mcp", "MCP tools"],
            ["traces", "Live traces"],
          ] as const
        ).map(([v, label]) => (
          <button
            key={v}
            onClick={() => setTab(v)}
            className={cx(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              tab === v
                ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "lifecycle" && (
        <Lifecycle orchestrator={orchestrator} agents={agents} />
      )}
      {tab === "mcp" && <McpPanel mcp={mcp} />}
      {tab === "traces" && <TracePanel />}
    </>
  );
}

function Lifecycle({
  orchestrator,
  agents,
}: {
  orchestrator: AgentsData["orchestrator"];
  agents: AgentCard[];
}) {
  const stopped = orchestrator.cases - orchestrator.booked;
  const booked = orchestrator.booked - orchestrator.ticketed;

  return (
    <Card>
      {/* The graph */}
      <div className="overflow-x-auto pb-2">
        <svg viewBox="0 0 720 150" className="h-[150px] w-full min-w-[640px]">
          {/* edges */}
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto"
            >
              <path d="M0 0 L10 5 L0 10 z" fill="var(--ink-faint)" />
            </marker>
          </defs>

          {NODES.slice(0, -1).map((n, i) => (
            <line
              key={n.id}
              x1={n.x * 130 + 78}
              y1={72}
              x2={NODES[i + 1].x * 130 + 34}
              y2={72}
              stroke="var(--ink-faint)"
              strokeWidth="1.4"
              markerEnd="url(#arrow)"
              opacity="0.55"
            />
          ))}

          {/* the branch: an agent decides to stop and ask */}
          <path
            d="M 208 72 Q 250 118 292 118"
            fill="none"
            stroke="#e0a232"
            strokeWidth="1.6"
            strokeDasharray="4 3"
            markerEnd="url(#arrow)"
          />
          <text
            x="300"
            y="122"
            fill="#e0a232"
            fontSize="11"
            fontFamily="var(--font-mono)"
          >
            {stopped} stopped to ask a question
          </text>

          {NODES.map((n) => (
            <g key={n.id}>
              <rect
                x={n.x * 130}
                y={56}
                width={110}
                height={32}
                rx={7}
                fill="var(--surface-sunken)"
                stroke="var(--line)"
              />
              <text
                x={n.x * 130 + 55}
                y={76}
                textAnchor="middle"
                fill="var(--ink)"
                fontSize="11.5"
                fontFamily="var(--font-sans)"
              >
                {n.label}
              </text>
            </g>
          ))}

          <text
            x="0"
            y="26"
            fill="var(--ink-muted)"
            fontSize="12"
            fontFamily="var(--font-sans)"
          >
            {orchestrator.cases} emails · 3 distinct paths · no human in the middle
          </text>
        </svg>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <PathStat
          n={stopped}
          label="stopped at a question"
          detail="The email did not state something the order needs. The agent asks rather than inventing it."
          color="#e0a232"
        />
        <PathStat
          n={booked}
          label="booked and never flagged"
          detail="Order filed, shipment scored by the stream, predicted on time."
          color="#4d9fff"
        />
        <PathStat
          n={orchestrator.ticketed}
          label="booked → flagged → ticketed"
          detail="Predicted late, severity graded, customer notified, ticket filed."
          color="#e34948"
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5 border-t border-[var(--line)] pt-3">
        {agents.map((a) => (
          <Pill key={a.id} tone="neutral" className="text-[11px]">
            {a.name}
          </Pill>
        ))}
      </div>
    </Card>
  );
}

function PathStat({
  n,
  label,
  detail,
  color,
}: {
  n: number;
  label: string;
  detail: string;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3">
      <p className="tabular text-xl font-semibold" style={{ color }}>
        {n}
      </p>
      <p className="mt-0.5 text-xs font-medium">{label}</p>
      <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-muted)]">
        {detail}
      </p>
    </div>
  );
}

function McpPanel({ mcp }: { mcp: McpTranscript }) {
  const tools = Array.isArray(mcp.tools) ? (mcp.tools as unknown[]) : [];
  const calls = Array.isArray(mcp.calls) ? mcp.calls : [];

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Pill tone="good">{tools.length} tools discovered</Pill>
        <Pill tone="neutral">{calls.length} calls</Pill>
        {mcp.protocol_version && (
          <Pill tone="neutral" className="font-mono text-[10px]">
            MCP {mcp.protocol_version}
          </Pill>
        )}
        {mcp.transport && (
          <Pill tone="neutral" className="font-mono text-[10px]">
            {mcp.transport}
          </Pill>
        )}
      </div>

      <p className="mb-3 text-sm leading-relaxed text-[var(--ink-muted)]">
        The agents reach the pipeline through an MCP tool server — corridor
        statistics, predictions, the TMS and vector search. This is a real
        client driving it over stdio, not a description of one.
      </p>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {tools.map((t, i) => {
          const name =
            typeof t === "string"
              ? t
              : ((t as { name?: string })?.name ?? `tool ${i + 1}`);
          return (
            <span
              key={i}
              className="rounded-md border border-[var(--line)] bg-[var(--surface-sunken)] px-2 py-1 font-mono text-[11px] text-[var(--ink-muted)]"
            >
              {name}
            </span>
          );
        })}
      </div>

      {calls.length > 0 && (
        <TableShell maxHeight="22rem">
          <thead>
            <tr>
              <Th align="left">#</Th>
              <Th align="left">Tool</Th>
              <Th align="left">Result</Th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c, i) => {
              const rec = c as Record<string, unknown>;
              const tool =
                (rec.tool as string) ?? (rec.name as string) ?? "—";
              const ok = rec.error === undefined && rec.ok !== false;
              return (
                <tr key={i}>
                  <Td mono className="text-[var(--ink-faint)]">
                    {i + 1}
                  </Td>
                  <Td mono>{tool}</Td>
                  <Td>
                    <span
                      className={cx(
                        "font-mono text-[11px]",
                        ok ? "text-emerald-400" : "text-amber-400"
                      )}
                    >
                      {ok ? "ok" : "error"}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </TableShell>
      )}
    </Card>
  );
}

function TracePanel() {
  const [traces, setTraces] = useState<TraceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTraces(undefined, 40).then((r) => {
      if (r.ok) setTraces(r.data.traces ?? []);
      else setError(r.message);
    });
  }, []);

  if (error || !API_CONFIGURED) {
    return (
      <Notice tone="replay" title="No live trace log on this build">
        {error ??
          "This is a static build with no API attached, so there is no running agent to trace."}{" "}
        The lifecycle and MCP tabs show the recorded runs instead, which is what
        every number on this page was measured from.
      </Notice>
    );
  }

  if (traces === null) {
    return (
      <div className="h-40 animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]" />
    );
  }

  return (
    <TableShell maxHeight="26rem">
      <thead>
        <tr>
          <Th align="left">When</Th>
          <Th align="left">Agent</Th>
          <Th align="left">Event</Th>
          <Th align="left">Status</Th>
        </tr>
      </thead>
      <tbody>
        {traces.map((t, i) => (
          <tr key={i}>
            <Td mono className="whitespace-nowrap text-[var(--ink-faint)]">
              {t.ts ?? "—"}
            </Td>
            <Td mono>{t.agent ?? "—"}</Td>
            <Td>{t.event ?? "—"}</Td>
            <Td>
              <span
                className={cx(
                  "font-mono text-[11px]",
                  t.ok === false ? "text-amber-400" : "text-emerald-400"
                )}
              >
                {t.ok === false ? "failed" : "ok"}
              </span>
            </Td>
          </tr>
        ))}
        {traces.length === 0 && (
          <tr>
            <Td className="py-6 text-center text-[var(--ink-muted)]">
              The API is up but has no traces recorded yet.
            </Td>
          </tr>
        )}
      </tbody>
    </TableShell>
  );
}
