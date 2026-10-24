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
  /** The facility within the city, e.g. "Nelmngla" — what tells two apart. */
  facility?: string | null;
  city: string | null;
  state: string | null;
  lat: number | null;
  lon: number | null;
}

export interface Corridor {
  id: string;
  src: Place;
  dst: Place;
  /** "Kanpur → Kanpur", built in the export from names or codes; never "nan". */
  route: string;
  /** B3: survives the dependence-aware audit. Present only when that file exists. */
  robust?: boolean;
  /** B4: empirical-Bayes rank. Present only when that file exists. */
  eb_rank?: number;
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
  /** Corridors confirmed by the dependence-aware test at its pre-registered strictness (D-080). */
  audit_robust_slower: number;
  /** Mean discoveries of the standard test on placebo data with meaningless corridor labels (D-099). */
  audit_placebo_discoveries: number;
  /** Share of the standard test's discoveries that are not planted corridors in the power study (D-099). */
  audit_welch_fdp: number;
  /** Power of the dependence-aware test when a 2.7-fold overrun is planted (D-099). */
  audit_cluster_power_shift_one: number;
  /** Rank correlation of corridor means between the two halves of the period (D-082). */
  stability_spearman: number;
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
    mean_baseline_mae_min: number | null;
    /** The hierarchical back-off baseline; present only once a freeze holds it. */
    backoff_mae_min?: number | null;
    /** The reported model (LightGBM, chosen on validation) and its margin over the back-off bar. */
    reported_mae_min?: number | null;
    reported_vs_bar_min?: number | null;
    reported_vs_bar_ci?: [number, number];
    served_vs_bar_min?: number | null;
    rolling_folds_reported?: number;
    rolling_folds_served?: number;
    rolling_folds_total?: number;
    served_model: string;
    served_note: string;
    /** Present once the running stream has reproduced the batch predictions (WP-11). */
    stream_equals_batch?: { identical: number; legs: number };
  };
  slices: ModelSlice[];
}

/** A count out of a total with its Wilson 95% interval. */
export interface Proportion {
  successes: number;
  total: number;
  rate: number;
  ci_low: number;
  ci_high: number;
}

export interface AgentRow extends Proportion {
  label: string;
  unit: string;
  note?: string;
  historical?: boolean;
}

export interface AgentCard {
  id: string;
  name: string;
  role: string;
  one_liner: string;
  score: Proportion & {
    value: number;
    label: string;
    unit: string;
    note: string;
    file: string;
  };
  baseline: { label: string; value: number; note?: string };
  also?: AgentRow[];
  prompt_version: string;
  deterministic: string;
}

export interface AblationArm {
  name: string;
  accuracy: number | null;
  ci_low: number | null;
  ci_high: number | null;
  n: number | string | null;
  unanimity: number | null;
  cost: number | string | null;
  cost_unit: string | null;
}

export interface AgentsData {
  agents: AgentCard[];
  orchestrator: {
    cases: number;
    routed: Proportion;
    paths_exercised: number;
    baseline: { label: string; value: number; note?: string };
    distribution: Record<string, number>;
    earlier_booked: number;
    earlier_ticketed: number;
    earlier_cases: number;
    file: string;
    note: string;
  };
  /** Present only when benchmarks/raw/b7_agent_ablation.json exists. */
  ablation?: { file: string; note: string; arms: AblationArm[] };
}

export interface EvidenceEntry {
  key: string;
  label: string;
  value: number | string | boolean | null;
  unit: string;
  week: number | null;
  file: string;
  /** Set for a share that is only meaningful beside its case count. */
  n?: number;
  /** True for a number from a model or run that a later one replaced. */
  superseded?: boolean;
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
  sample_note: string;
  delivery: {
    channel: string;
    recorded_at: string;
    candidates: number;
    sent: number;
    failed: number;
    suppressed_by_cap: number;
  }[];
  delivered_channels: string[];
}

export interface PaperData {
  title: string;
  abstract: string;
  abstract_is_placeholder: boolean;
  preprint_url: string | null;
  bibtex: string;
  headline: Record<string, number>;
  reproduce: { command: string; links: { label: string; path: string }[] };
}

export interface AssistantEval {
  no_llm?: {
    answered: number;
    questions: number;
    route_accuracy: number | null;
    route_correct?: number;
    route_ci_low?: number;
    route_ci_high?: number;
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
  figures: {
    file: string;
    pdf: string | null;
    id: string;
    title: string;
    caption: string;
  }[];
  readme: string;
}
