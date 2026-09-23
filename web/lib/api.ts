/**
 * The client for the live half of the site.
 *
 * Four pages need compute that a static bundle cannot do: a prediction, the
 * alert feed, the agent traces and the assistant. They call the FastAPI service
 * from the browser at runtime.
 *
 * The important property here is that **the API being down is a normal state,
 * not an error state**. The free container sleeps, and a visitor who arrives
 * while it is asleep should see the recorded evidence with an honest label
 * rather than a spinner or a stack trace. Every call returns a discriminated
 * result and every page renders the offline branch deliberately.
 */

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? ""
).replace(/\/$/, "");

export const API_CONFIGURED = API_BASE.length > 0;

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "unconfigured" | "offline" | "error"; message: string };

async function call<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number }
): Promise<ApiResult<T>> {
  if (!API_CONFIGURED) {
    return {
      ok: false,
      reason: "unconfigured",
      message:
        "No API URL is configured for this build, so the live pages show recorded evidence.",
    };
  }

  const timeoutMs = init?.timeoutMs ?? 12_000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      return {
        ok: false,
        reason: "error",
        message: `The API answered ${res.status}.`,
      };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    return {
      ok: false,
      reason: "offline",
      message: aborted
        ? "The API did not answer in time — the free container may be waking up."
        : "The API is not reachable right now.",
    };
  } finally {
    clearTimeout(timer);
  }
}

// ── shapes the API returns ───────────────────────────────────────────────────

export interface PredictRequest {
  corridor_id: string;
  osrm_time_min: number;
  osrm_km: number;
  route_type: string;
  departure_hour: number;
}

export interface PredictResponse {
  predicted_gap_min: number;
  predicted_total_min: number;
  is_delayed: boolean;
  /** Which model actually scored this — D-053 means it is not the reported one. */
  model_id: string;
  model_note?: string;
  cold_start: boolean;
  corridor_prior_legs?: number | null;
}

export interface PredictStatus {
  state: "ready" | "warming" | "cold";
  detail?: string;
}

export interface AskResponse {
  answer: string;
  route: "table" | "retrieval" | "refused" | string;
  sources: { label: string; file?: string }[];
  used_llm: boolean;
  quota_remaining?: number | null;
}

export interface TraceRow {
  ts?: string;
  agent?: string;
  event?: string;
  ok?: boolean;
  [key: string]: unknown;
}

export interface LiveAlerts {
  alerts: {
    seq: number;
    corridor_id: string;
    route?: string;
    predicted_gap_min: number;
    severity: string;
    n_legs?: number;
    excess_ratio?: number | null;
  }[];
  rollup?: { corridor_id: string; n: number }[];
  generated_at?: string;
}

// ── calls ────────────────────────────────────────────────────────────────────

export const getHealth = () => call<{ status: string }>("/health", { timeoutMs: 6000 });

export const getPredictStatus = () =>
  call<PredictStatus>("/api/predict/status", { timeoutMs: 6000 });

export const postPredict = (body: PredictRequest) =>
  call<PredictResponse>("/api/predict", {
    method: "POST",
    body: JSON.stringify(body),
    // The first call after the container sleeps starts a SparkSession.
    timeoutMs: 60_000,
  });

export const getAlerts = (since?: number) =>
  call<LiveAlerts>(`/api/alerts${since ? `?since=${since}` : ""}`);

export const getTraces = (agent?: string, limit = 50) =>
  call<{ traces: TraceRow[] }>(
    `/api/traces?limit=${limit}${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`
  );

export const postAsk = (question: string, useLlm = false) =>
  call<AskResponse>("/api/ask", {
    method: "POST",
    body: JSON.stringify({ question, use_llm: useLlm }),
    timeoutMs: 45_000,
  });
