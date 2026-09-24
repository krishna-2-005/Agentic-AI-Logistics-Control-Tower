/**
 * Reading the exported JSON at build time.
 *
 * These run on the server during `next build` and the result is baked into the
 * static HTML, so the browser never fetches them. That is what makes eight of
 * the ten pages work with no backend at all.
 */

import fs from "node:fs";
import path from "node:path";

import type {
  AgentsData,
  AlertsSample,
  AssistantEval,
  Corridor,
  Envelope,
  EvidenceIndex,
  FiguresData,
  Hub,
  McpTranscript,
  ModelData,
  Overview,
  PromptAgent,
} from "./types";

const DATA_DIR = path.join(process.cwd(), "public", "data");

function read<T>(name: string): Envelope<T> {
  const file = path.join(DATA_DIR, name);
  return JSON.parse(fs.readFileSync(file, "utf-8")) as Envelope<T>;
}

/** Present, but empty — used where a file is optional rather than required. */
function empty<T>(fallback: T): Envelope<T> {
  return {
    source: "",
    generated_at: "",
    freeze: "",
    data: fallback,
  };
}

function readOptional<T>(name: string, fallback: T): Envelope<T> {
  try {
    return read<T>(name);
  } catch {
    return empty(fallback);
  }
}

export const getOverview = () => read<Overview>("overview.json");
export const getCorridors = () => read<Corridor[]>("corridors.json");
export const getCorridors30 = () =>
  readOptional<Corridor[]>("corridors_support30.json", []);
export const getHubs = () => read<Hub[]>("hubs.json");
export const getModel = () => read<ModelData>("model.json");
export const getAgents = () => read<AgentsData>("agents.json");
export const getEvidence = () => read<EvidenceIndex>("evidence_index.json");
export const getPrompts = () => read<PromptAgent[]>("prompts.json");
export const getFigures = () =>
  readOptional<FiguresData>("figures.json", { figures: [], readme: "" });
export const getAlertsSample = () =>
  readOptional<AlertsSample>("alerts_sample.json", {
    recorded_at: null,
    source: "file",
    is_replay: true,
    replay_note: "",
    run: {
      events: null,
      alerts: null,
      events_per_second: null,
      scoring_rate_eps: null,
    },
    alerts: [],
  });
export const getAssistantEval = () =>
  readOptional<AssistantEval>("assistant_eval.json", {});
export const getMcpTranscript = () =>
  readOptional<McpTranscript>("mcp_transcript.json", {
    transport: "",
    protocol_version: "",
    server_name: "",
    tools: [],
    summary: {},
    calls: [],
  });

/** A freeze value by id, so a page can quote the frozen number directly. */
export function frozen(
  evidence: EvidenceIndex,
  key: string
): number | string | boolean | null {
  return evidence.entries.find((e) => e.key === key)?.value ?? null;
}

/** The source file behind a freeze value, for the Evidence link. */
export function frozenFile(
  evidence: EvidenceIndex,
  key: string
): string | undefined {
  return evidence.entries.find((e) => e.key === key)?.file;
}

export { REPO_URL, repoFileUrl } from "./repo";
