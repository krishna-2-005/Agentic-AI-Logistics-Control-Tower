/**
 * The shapes `src/report/export_web.py` writes.
 *
 * Every file arrives wrapped in an Envelope carrying its source file and the
 * results-freeze version it was built from, so the Evidence link on screen is
 * generated rather than typed (D-059).
 */

export interface Envelope<T> {
  source: string | string[];
  generated_at: string;
  freeze: string;
  data: T;
  [extra: string]: unknown;
}

export interface Severity {
  bin: number;
  color: string;
  weight: number;
  /** A word, because colour is never the only carrier of meaning (W-11). */
  label: string;
  range: string;
}

export interface Place {
  code: string;
  city: string | null;
  state: string | null;
  lat: number | null;
  lon: number | null;
}

export interface Corridor {
  id: string;
  src: Place;
  dst: Place;
  intra_city: boolean;
  n_legs: number;
  excess_ratio: number;
  direction: "worse" | "better" | string;
  is_significant: boolean;
  q_value: number | null;
  median_gap_min: number | null;
  mean_gap_min: number | null;
  median_gap_ratio: number | null;
  mean_dwell_min: number | null;
  mean_osrm_km: number | null;
  ftl_share: number | null;
  rank: number | null;
  severity: Severity;
}

export interface Overview {
  legs: number;
  corridors: number;
  corridors_tested: number;
  bottlenecks: number;
  faster_corridors: number;
  share_over_plan: number;
  median_ratio: number;
  median_gap_min: number;
  share_above_clip: number;
  clip_at: number;
  histogram: { x: number; n: number }[];
}

export interface Hub {
  code: string;
  name: string | null;
  city: string | null;
  state: string | null;
  lat: number | null;
  lon: number | null;
  outbound_legs: number;
  corridors_out: number | null;
  median_dwell_min: number | null;
  p90_dwell_min: number | null;
  dwell_share: number | null;
  median_gap_ratio: number | null;
  friction_rank: number;
}

export interface ModelSlice {
  dimension: string;
  slice: string;
  n: number;
  model: string;
  mae_min: number | null;
  baseline_mae_min: number | null;
  delta_vs_median_min: number | null;
}

export interface ModelData {
  headline: {
    model: string;
    mae_min: number | null;
    baseline_mae_min: number | null;
    osrm_mae_min: number | null;
    served_model: string;
    served_note: string;
  };
  slices: ModelSlice[];
}

export interface AgentCard {
  id: string;
  name: string;
  role: string;
  one_liner: string;
  score: {
    value: number | null;
    label: string;
    note: string;
    file: string;
  };
  prompt_version: string;
  deterministic: string;
}

export interface AgentsData {
  agents: AgentCard[];
  orchestrator: {
    cases: number;
    booked: number;
    ticketed: number;
    file: string;
    note: string;
  };
}

export interface EvidenceEntry {
  key: string;
  label: string;
  value: number | string | boolean | null;
  unit: string;
  week: number | null;
  file: string;
}

export interface EvidenceIndex {
  frozen_at: string;
  n_values: number;
  entries: EvidenceEntry[];
}

export interface PromptAgent {
  agent: string;
  notes: string | null;
  versions: { version: string; text: string }[];
}

export interface AlertRow {
  seq: number;
  corridor_id: string;
  route: string;
  predicted_gap_min: number;
  excess_ratio: number | null;
  severity: "low" | "medium" | "high" | "critical" | string;
  n_legs: number;
}

export interface AlertsSample {
  recorded_at: string | null;
  source: string;
  is_replay: boolean;
  replay_note: string;
  run: {
    events: number | null;
    alerts: number | null;
    events_per_second: number | null;
    scoring_rate_eps: number | null;
  };
  alerts: AlertRow[];
}

export interface AssistantEval {
  no_llm?: {
    answered: number;
    questions: number;
    route_accuracy: number | null;
    source_accuracy: number | null;
    refusal_recall: number | null;
    refusal_precision: number | null;
    by_category?: Record<string, unknown>;
    misses?: unknown[];
  };
  llm?: AssistantEval["no_llm"];
  groundedness?: {
    judged: number;
    grounded: number;
    partly_grounded: number;
    not_grounded: number;
    rate_model_written: number | null;
    out_of_scope_refused: number;
    out_of_scope_total: number;
    extractive_fallbacks: number;
    method: string;
  };
}

export interface McpCall {
  [key: string]: unknown;
}

export interface McpTranscript {
  transport: string;
  protocol_version: string;
  server_name: string;
  tools: unknown;
  summary: Record<string, unknown>;
  calls: McpCall[];
}

export interface FiguresData {
  figures: { file: string; id: string; title: string }[];
  readme: string;
}
