"use client";

import { useEffect, useMemo, useState } from "react";

import { Card, Notice, Pill } from "@/components/ui";
import {
  API_CONFIGURED,
  getPredictStatus,
  postPredict,
  type PredictResponse,
} from "@/lib/api";
import { cx, minutes, num } from "@/lib/format";

interface Option {
  id: string;
  label: string;
  state: string;
  legs: number;
  km: number | null;
}

/** The service reports a model by its internal name; a reader wants a phrase. */
function friendlyModel(id: string): string {
  if (/random_forest/i.test(id)) return "a random-forest model";
  if (/gbt|gradient/i.test(id)) return "a gradient-boosted model";
  if (/median/i.test(id)) return "this lane's own median";
  return "the delay model";
}

/**
 * The one page that needs a model in the loop.
 *
 * The free container sleeps and a cold SparkSession takes 20-40 seconds, so the
 * warming state is a first-class thing the UI shows rather than a spinner that
 * looks like a hang. If the API never answers, the page says so plainly instead
 * of pretending.
 */
export function Predictor({ corridors }: { corridors: Option[] }) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Option | null>(corridors[0] ?? null);
  const [osrmMin, setOsrmMin] = useState(180);
  const [km, setKm] = useState(250);
  const [routeType, setRouteType] = useState("FTL");
  const [hour, setHour] = useState(9);

  const [status, setStatus] = useState<"unknown" | "ready" | "warming" | "down">(
    "unknown"
  );
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!API_CONFIGURED) {
      setStatus("down");
      return;
    }
    getPredictStatus().then((r) => {
      if (r.ok) setStatus(r.data.state === "ready" ? "ready" : "warming");
      else setStatus("down");
    });
  }, []);

  // Seed the form from the corridor's own measured distance, so the default is
  // a plausible leg rather than an arbitrary one.
  useEffect(() => {
    if (picked?.km) {
      setKm(Math.round(picked.km));
      setOsrmMin(Math.round(picked.km * 0.72));
    }
  }, [picked]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return corridors.slice(0, 8);
    return corridors
      .filter(
        (c) =>
          c.label.toLowerCase().includes(q) ||
          c.state.toLowerCase().includes(q)
      )
      .slice(0, 8);
  }, [corridors, query]);

  async function submit() {
    if (!picked) return;
    setPending(true);
    setError(null);
    setResult(null);
    const r = await postPredict({
      corridor_id: picked.id,
      osrm_time_min: osrmMin,
      osrm_km: km,
      route_type: routeType,
      departure_hour: hour,
    });
    setPending(false);
    if (r.ok) {
      setResult(r.data);
      setStatus("ready");
    } else {
      setError(r.message);
      if (r.reason !== "unconfigured") setStatus("down");
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      {/* ── the form ─────────────────────────────────────────────────── */}
      <Card>
        <label className="mb-1.5 block text-sm font-medium">Corridor</label>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a city — Mumbai, Kanpur, Gurugram…"
          className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] px-3 py-2 text-sm placeholder:text-[var(--ink-faint)]"
        />
        <div className="mt-2 max-h-44 space-y-1 overflow-y-auto">
          {matches.map((c) => (
            <button
              key={c.id}
              onClick={() => setPicked(c)}
              className={cx(
                "flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                picked?.id === c.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "hover:bg-[var(--surface-sunken)]"
              )}
            >
              <span className="truncate">{c.label}</span>
              <span className="tabular shrink-0 font-mono text-[11px] text-[var(--ink-faint)]">
                {c.legs} legs
              </span>
            </button>
          ))}
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <Field
            label="Planned time"
            suffix="min"
            value={osrmMin}
            onChange={setOsrmMin}
            min={10}
            max={2000}
          />
          <Field
            label="Distance"
            suffix="km"
            value={km}
            onChange={setKm}
            min={1}
            max={3000}
          />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">
              Route type
            </label>
            <div className="flex rounded-lg border border-[var(--line)] p-0.5">
              {["FTL", "Carting"].map((t) => (
                <button
                  key={t}
                  onClick={() => setRouteType(t)}
                  className={cx(
                    "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                    routeType === t
                      ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                      : "text-[var(--ink-muted)]"
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">
              Departure hour
              <span className="tabular ml-2 font-mono text-xs text-[var(--ink-faint)]">
                {String(hour).padStart(2, "0")}:00
              </span>
            </label>
            <input
              type="range"
              min={0}
              max={23}
              value={hour}
              onChange={(e) => setHour(Number(e.target.value))}
              className="mt-2 w-full accent-[var(--accent)]"
            />
          </div>
        </div>

        <button
          onClick={submit}
          disabled={pending || !picked}
          className="mt-5 w-full rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Scoring…" : "Predict the delay"}
        </button>

        {status === "warming" && (
          <p className="mt-2 text-center font-mono text-[11px] text-amber-400">
            model warming — the first call starts a Spark session
          </p>
        )}
      </Card>

      {/* ── the answer ───────────────────────────────────────────────── */}
      <div className="space-y-4">
        {result ? (
          <Card>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wider text-[var(--ink-muted)]">
                  Predicted delay
                </p>
                <p
                  className={cx(
                    "tabular mt-1 text-4xl font-semibold tracking-tight",
                    result.is_delayed ? "text-[#e34948]" : "text-emerald-400"
                  )}
                >
                  {minutes(result.predicted_gap_min)}
                </p>
              </div>
              <Pill tone={result.is_delayed ? "warn" : "good"}>
                {result.is_delayed ? "flagged late" : "on plan"}
              </Pill>
            </div>

            <dl className="mt-5 space-y-2 text-sm">
              <Row
                k="Total journey"
                v={minutes(result.predicted_total_min)}
              />
              <Row k="Planned" v={minutes(osrmMin)} />
              <Row
                k="Past journeys on this lane"
                v={
                  result.cold_start
                    ? "none on record"
                    : num(result.corridor_prior_legs ?? 0)
                }
              />
            </dl>

            <p className="mt-4 text-xs text-[var(--ink-faint)]">
              Estimated by {friendlyModel(result.model_id)}.
            </p>

            {result.cold_start && (
              <p className="mt-3 text-xs leading-relaxed text-[var(--ink-muted)]">
                Nothing has travelled this lane before in the data, so the
                estimate rests on the route itself — distance, vehicle type and
                departure hour — rather than on history. This is where the model
                is most useful and also least certain.
              </p>
            )}
          </Card>
        ) : (
          <Notice
            tone={status === "down" ? "replay" : "info"}
            title={
              status === "down"
                ? "The prediction service is not attached to this build"
                : "Set the leg up and press predict"
            }
          >
            {status === "down" ? (
              <>
                {error ??
                  "This static site has no API URL configured, so nothing can score a leg right now."}{" "}
                The model itself and every number measured from it are on the{" "}
                <a href="/evidence/" className="text-[var(--accent)] underline">
                  results page
                </a>
                , which needs no backend at all.
              </>
            ) : (
              <>
                The model predicts the <em>gap</em> — how far past the plan a leg
                actually runs — rather than the total, because that is the
                quantity the corridor audit is about.
              </>
            )}
          </Notice>
        )}

        {error && result === null && status !== "down" && (
          <Notice tone="warn" title="That request did not come back">
            {error}
          </Notice>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  suffix,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  suffix: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <div className="flex items-center rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] px-3">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          onChange={(e) => onChange(Number(e.target.value))}
          className="tabular w-full bg-transparent py-2 font-mono text-sm outline-none"
        />
        <span className="ml-1 text-xs text-[var(--ink-faint)]">{suffix}</span>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-[var(--line)]/50 pb-1.5">
      <dt className="text-[var(--ink-muted)]">{k}</dt>
      <dd className="tabular font-mono text-[13px]">{v}</dd>
    </div>
  );
}
