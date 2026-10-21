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

/**
 * The public API (D-072, D-073). Built in as the default because it is a public
 * address, not a credential: the browser has to know it to call it. A deployment can
 * still override it with NEXT_PUBLIC_API_URL. An *empty* value falls back to the
 * default too: Vercel can hold a variable that exists but is blank, and that must not
 * silently switch the live pages off (it did once, on the dev preview). Set it to
 * "off" to build a site with no API on purpose.
 */
export const DEFAULT_API_URL = "https://control-tower-api.onrender.com";

const configured = (process.env.NEXT_PUBLIC_API_URL ?? "").trim();

export const API_BASE = (
  configured === "off" ? "" : configured || DEFAULT_API_URL
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

  const timeoutMs = init?.timeoutMs ?? WAKE_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    // A host that is mid-boot can answer 502/503/504 before it is ready. That is
    // the same "still waking" state as a held request, so keep trying until the
    // deadline instead of reporting an error the visitor can do nothing about.
    for (;;) {
      const res = await fetch(`${API_BASE}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
      });
      if (res.ok) return { ok: true, data: (await res.json()) as T };
      if (!WAKING_STATUSES.has(res.status)) {
        return {
          ok: false,
          reason: "error",
          message: `The API answered ${res.status}.`,
        };
      }
      await sleep(WAKE_RETRY_MS, controller.signal);
    }
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
  /** Which model actually scored this — the reported v2 model since WP-11 closed D-053. */
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
  /** "replay": the API releases a recorded stream run; it runs no live stream (D-072). */
  mode?: "replay" | "live";
  note?: string;
  recorded_at?: string | null;
}

// ── calls ────────────────────────────────────────────────────────────────────

/**
 * The free API host sleeps after 15 idle minutes. The first request after that is
 * held while it boots (30-60 s) and then answered, so these wait long enough for
 * that to finish. Six seconds was too short: a sleeping server read as a missing one.
 */
export const WAKE_TIMEOUT_MS = 90_000;

/** Statuses a booting free host returns before it can serve. */
export const WAKING_STATUSES = new Set([502, 503, 504]);
const WAKE_RETRY_MS = 4_000;

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(id);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

/** What the page says while it waits, and after it gave up. One wording, every page. */
export const WAKING_TITLE = "Waking the free server (up to ~1 min)";
export const WAKING_BODY =
  "The live service runs on a free host that sleeps when idle. It is starting now and will answer on its own; nothing is wrong.";

export const getHealth = () =>
  call<{ status: string }>("/health", { timeoutMs: WAKE_TIMEOUT_MS });

export const getPredictStatus = () =>
  call<PredictStatus>("/api/predict/status", { timeoutMs: WAKE_TIMEOUT_MS });

export const postPredict = (body: PredictRequest) =>
  call<PredictResponse>("/api/predict", {
    method: "POST",
    body: JSON.stringify(body),
    // The first call after the container sleeps starts a SparkSession.
    timeoutMs: WAKE_TIMEOUT_MS,
  });

export const getAlerts = (since?: number) =>
  call<LiveAlerts>(`/api/alerts${since ? `?since=${since}` : ""}`, {
    timeoutMs: WAKE_TIMEOUT_MS,
  });

export const getTraces = (agent?: string, limit = 50) =>
  call<{ traces: TraceRow[] }>(
    `/api/traces?limit=${limit}${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`,
    { timeoutMs: WAKE_TIMEOUT_MS }
  );

export const postAsk = (question: string, useLlm = false) =>
  call<AskResponse>("/api/ask", {
    method: "POST",
    body: JSON.stringify({ question, use_llm: useLlm }),
    timeoutMs: WAKE_TIMEOUT_MS,
  });
