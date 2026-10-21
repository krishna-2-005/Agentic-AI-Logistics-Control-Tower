"""Deterministic core vs LLM-decides, three agents (B7, D-086).

    python -m src.ml.agent_ablation                 # deterministic arm only, zero calls
    python -m src.ml.agent_ablation --llm-verdict   # plus the LLM-decides arm (cached)
    python -m src.ml.agent_ablation --llm-verdict --agents order,invoice --n 40

The same inputs go to the code and to a language model that must emit the verdict in a strict
JSON schema (`prompts/<agent>/llm_verdict_v1.md`). The model also receives the policy in prose,
so the ablation isolates who *executes* the policy. Per case: 5 calls at temperature 0.7 and 2
at temperature 0. Every response is cached on disk by (agent, case, run, temperature, prompt
hash, model), so a rerun costs nothing, and a ledger records calls, tokens and latency.

The provider is a free-tier open model (`openai/gpt-oss-120b` on Groq), not the Gemini model
that writes the project's prose; results say so. Nothing here calls the network unless the
default caller is used, and tests inject a fake one.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.agents.exception_agent import SLOWER_THAN_NETWORK, Investigation, severity_for
from src.agents.invoice_auditor import audit_invoice, corridor_km_lookup, verdict_for
from src.agents.order_rules import extract_order_rules
from src.agents.prompts.registry import Prompt, load_variant
from src.common import config
from src.ml.order_eval_scale import Case, build_cases, score_case
from src.ml.stats import wilson

RAW = config.BENCHMARKS_RAW_DIR
OUT_JSON = RAW / "b7_agent_ablation.json"
OUT_CSV = RAW / "b7_agent_ablation_cases.csv"
OUT_LEDGER = RAW / "b7_llm_ledger.json"
CACHE_DIR = config.DATA_DIR / "b7_cache"

PROVIDER = "groq"
MODEL = "openai/gpt-oss-120b"
SUBSET_SEED = 8602
SAMPLED_TEMPERATURE = 0.7
SAMPLED_RUNS = ["s0", "s1", "s2", "s3", "s4"]
TEMP0_RUNS = ["t0a", "t0b"]
ALL_RUNS = SAMPLED_RUNS + TEMP0_RUNS
SEVERITIES = ("low", "medium", "high", "critical")
ORDER_FIELDS_VOCAB = {"customer_name", "origin_centre", "dest_centre", "route_type", "pieces",
                      "weight_kg", "consignment"}
INVOICE_CODES = {"total_mismatch", "rate_above_band", "rate_below_band", "other_charges_out_of_band",
                 "duplicate_invoice_number", "unexpected_currency"}
LEDGER_SIZE = 20
#: Groq's published list price for this model, USD per million tokens (input, output). It is an
#: assumption entered by hand from the provider's public pricing page, used only for the
#: paid-equivalent estimate; the measured cost on the free tier is zero.
PRICE_PER_M_TOKENS = (0.15, 0.60)

CALLER = Callable[[str, float], tuple[str, int, int]]


# ── statistics ───────────────────────────────────────────────────────────────
def fleiss_kappa(ratings: list[list[str]]) -> float | None:
    """Fleiss' kappa for n subjects each rated by the same number of raters.

    `ratings[i]` is the list of category labels the raters gave subject i. Returns None when
    chance agreement is 1 (every rating is the same category), where kappa is undefined.
    """
    if not ratings:
        return None
    m = len(ratings[0])
    if m < 2 or any(len(r) != m for r in ratings):
        raise ValueError("need the same number (>= 2) of ratings for every subject")
    categories = sorted({c for r in ratings for c in r})
    n = len(ratings)
    counts = np.array([[Counter(r)[c] for c in categories] for r in ratings], dtype=float)
    p_i = (np.square(counts).sum(axis=1) - m) / (m * (m - 1))
    p_bar = float(p_i.mean())
    p_j = counts.sum(axis=0) / (n * m)
    p_e = float(np.square(p_j).sum())
    if math.isclose(p_e, 1.0):
        return None
    return (p_bar - p_e) / (1 - p_e)


def unanimity(ratings: list[list[str]]) -> dict:
    unanimous = sum(1 for r in ratings if len(set(r)) == 1)
    return wilson(unanimous, len(ratings)).as_dict()


def bootstrap_diff(llm: list[float], det: list[float], resamples: int = 5000, seed: int = 8603) -> dict:
    """Case-level bootstrap of mean(llm) - mean(det) on the same cases."""
    a, b = np.asarray(llm, float), np.asarray(det, float)
    if len(a) != len(b) or len(a) == 0:
        raise ValueError("need equal, non-empty case lists")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(resamples, len(a)))
    diffs = (a[idx] - b[idx]).mean(axis=1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"difference": round(float((a - b).mean()), 4), "ci_low": round(float(lo), 4),
            "ci_high": round(float(hi), 4), "cases": len(a), "resamples": resamples, "seed": seed}


# ── parsing (strict: anything else is an error, counted, never repaired) ─────
class VerdictParseError(ValueError):
    pass


def _json_object(text: str) -> dict:
    try:
        obj = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise VerdictParseError(f"not a single JSON object: {text[:80]!r}") from exc
    if not isinstance(obj, dict):
        raise VerdictParseError("JSON value is not an object")
    return obj


def parse_order_verdict(text: str) -> dict:
    obj = _json_object(text)
    verdict = obj.get("verdict")
    if verdict not in ("file", "ask", "reject"):
        raise VerdictParseError(f"verdict {verdict!r} not in file/ask/reject")
    order = obj.get("order")
    if order is not None and not isinstance(order, dict):
        raise VerdictParseError("order is not an object")
    missing = obj.get("missing_field")
    if missing is not None and missing not in ORDER_FIELDS_VOCAB:
        raise VerdictParseError(f"missing_field {missing!r} not in vocabulary")
    if verdict == "ask" and missing is None:
        raise VerdictParseError("ask without missing_field")
    return {"verdict": verdict, "order": order or {}, "missing_field": missing}


def parse_invoice_verdict(text: str) -> dict:
    obj = _json_object(text)
    verdict, code = obj.get("verdict"), obj.get("reason_code")
    if verdict not in ("approve", "dispute"):
        raise VerdictParseError(f"verdict {verdict!r} not in approve/dispute")
    if code is not None and code not in INVOICE_CODES:
        raise VerdictParseError(f"reason_code {code!r} not in vocabulary")
    if (verdict == "approve") != (code is None):
        raise VerdictParseError("reason_code must be null exactly when the verdict is approve")
    return {"verdict": verdict, "reason_code": code}


def parse_exception_verdict(text: str) -> dict:
    obj = _json_object(text)
    severity = obj.get("severity")
    if severity not in SEVERITIES:
        raise VerdictParseError(f"severity {severity!r} not in vocabulary")
    return {"verdict": severity}


# ── cache and ledger ─────────────────────────────────────────────────────────
@dataclass
class Ledger:
    calls: int = 0
    cache_hits: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    by_agent: dict = field(default_factory=dict)

    def add(self, agent: str, record: dict, cached: bool) -> None:
        slot = self.by_agent.setdefault(agent, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                "latency_s": 0.0, "errors": 0})
        if cached:
            self.cache_hits += 1
        self.calls += 1
        slot["calls"] += 1
        for key, name in (("in_tok", "input_tokens"), ("out_tok", "output_tokens")):
            self.__dict__[name] += record.get(key, 0)
            slot[name] += record.get(key, 0)
        self.latency_s += record.get("latency_s", 0.0)
        slot["latency_s"] += record.get("latency_s", 0.0)
        if record.get("call_error"):
            self.errors += 1
            slot["errors"] += 1


def cache_key(agent: str, case_id: str, run: str, temperature: float, prompt_text: str, model: str) -> str:
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
    raw = "|".join([agent, case_id, run, f"{temperature:g}", digest, model])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def cached_call(agent: str, case_id: str, run: str, temperature: float, prompt_text: str,
                caller: CALLER, ledger: Ledger, model: str = MODEL, cache_dir: Path | None = None) -> dict:
    """One LLM call through the disk cache. Provider failures raise; they are never cached."""
    cache_dir = cache_dir or CACHE_DIR
    path = cache_dir / agent / f"{cache_key(agent, case_id, run, temperature, prompt_text, model)}.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        ledger.add(agent, record, cached=True)
        return record
    started = time.perf_counter()
    text, in_tok, out_tok = caller(prompt_text, temperature)
    record = {"agent": agent, "case_id": case_id, "run": run, "temperature": temperature, "model": model,
              "text": text, "in_tok": in_tok, "out_tok": out_tok,
              "latency_s": round(time.perf_counter() - started, 3)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    ledger.add(agent, record, cached=False)
    return record


class Throttle:
    """Keeps a sliding 60 s token total under the provider's per-minute limit."""

    def __init__(self, tokens_per_minute: int = 7600, estimate: int = 900):
        self.limit, self.estimate = tokens_per_minute, estimate
        self.events: list[tuple[float, int]] = []

    def wait(self) -> None:
        while True:
            now = time.monotonic()
            self.events = [(t, n) for t, n in self.events if now - t < 60]
            if sum(n for _, n in self.events) + self.estimate <= self.limit:
                return
            time.sleep(max(0.5, 60 - (now - self.events[0][0])) if self.events else 1)

    def record(self, tokens: int) -> None:
        self.events.append((time.monotonic(), tokens))
        self.estimate = max(300, int(0.8 * self.estimate + 0.2 * tokens))


def default_caller() -> CALLER:
    """The live Groq caller. Imported lazily so tests never touch the network or the key."""
    from dotenv import load_dotenv

    from src.agents.llm import get_llm

    load_dotenv()
    throttle = Throttle()

    def call(prompt: str, temperature: float) -> tuple[str, int, int]:
        throttle.wait()
        llm = get_llm(PROVIDER, MODEL, temperature=temperature)
        response = llm.invoke(prompt)
        usage = getattr(response, "usage_metadata", None) or {}
        in_tok, out_tok = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        throttle.record(in_tok + out_tok)
        content = response.content
        text = content if isinstance(content, str) else "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return text, in_tok, out_tok

    return call


# ── case sets ────────────────────────────────────────────────────────────────
@dataclass
class AblationCase:
    agent: str
    case_id: str
    stratum: str
    prompt_text: str
    det_verdict: str
    det_correct: bool
    truth: dict
    meta: dict = field(default_factory=dict)


def pick_subset(items: list, strata: list[str], per_stratum: int, seed: int = SUBSET_SEED) -> list:
    """`per_stratum` per stratum with a fixed seed, ordered round-robin so any prefix is balanced."""
    rng = random.Random(seed)
    buckets: dict[str, list] = {}
    for item, s in zip(items, strata, strict=True):
        buckets.setdefault(s, []).append(item)
    chosen = {s: rng.sample(b, min(per_stratum, len(b))) for s, b in sorted(buckets.items())}
    ordered = []
    for i in range(per_stratum):
        for s in sorted(chosen):
            if i < len(chosen[s]):
                ordered.append(chosen[s][i])
    return ordered


def order_cases(n_total: int = 40) -> tuple[list[AblationCase], dict]:
    prompt = load_variant("order_entry", "llm_verdict_v1")
    cases = build_cases()
    per = max(1, n_total // len({c.template for c in cases}))
    subset = pick_subset(cases, [c.template for c in cases], per)
    out = []
    for c in subset:
        det = extract_order_rules(c.subject, c.body)
        sc = score_case(c, det)
        out.append(AblationCase("order", f"order-{c.seq}", c.template,
                                prompt.render(email_subject=c.subject, email_body=c.body),
                                det["action"], bool(sc["correct"]),
                                {"case": asdict(c)}, {"adversarial": c.adversarial, "invented": bool(sc["invented_fields"])}))
    full_det = [score_case(c, extract_order_rules(c.subject, c.body))["correct"] for c in cases]
    return out, {"full_set_n": len(cases), "full_set_deterministic": wilson(int(sum(full_det)), len(full_det)).as_dict()}


def _invoice_prompt(prompt: Prompt, case, km: float | None, ledger_numbers: list[str]) -> str:
    return prompt.render(
        invoice_number=case.external_invoice_number, corridor_id=case.corridor_id, route_type=case.route_type,
        weight_kg=case.weight_kg, freight_charge=f"{case.freight_charge:,.2f}",
        other_charges=f"{case.other_charges:,.2f}", total_amount=f"{case.total_amount:,.2f}",
        currency=case.currency, corridor_km=f"{km:.1f} km" if km else "not available",
        ledger=", ".join(ledger_numbers),
    )


def invoice_ledger(entries: list, index: int, rng: random.Random) -> list[str]:
    """20 prior numbers: the duplicate's source if the case is a duplicate, plus fixed decoys."""
    case = entries[index].case
    others = [e.case.external_invoice_number for j, e in enumerate(entries)
              if j != index and e.case.external_invoice_number != case.external_invoice_number]
    decoys = rng.sample(sorted(set(others)), LEDGER_SIZE - (1 if entries[index].kind == "duplicate_number" else 0))
    if entries[index].kind == "duplicate_number":
        decoys.append(case.external_invoice_number)
    rng.shuffle(decoys)
    return decoys


def invoice_cases(n_total: int = 40) -> tuple[list[AblationCase], dict]:
    from src.agents.exception_agent import load_audit
    from src.ml.invoice_eval import build_eval_set, score
    from src.ml.invoice_eval_scale import SEED, stratified_kinds

    prompt = load_variant("invoice_audit", "llm_verdict_v1")
    entries = build_eval_set(count=200, seed=SEED, kinds=stratified_kinds(20))
    km = corridor_km_lookup(load_audit())
    frame, _ = score(entries)
    rng = random.Random(SUBSET_SEED)
    idx = list(range(len(entries)))
    kinds = [entries[i].kind for i in idx]
    per = max(1, n_total // len(set(kinds)))
    chosen = pick_subset(idx, kinds, per)
    out = []
    for i in chosen:
        e = entries[i]
        ledger_numbers = invoice_ledger(entries, i, rng)
        findings = audit_invoice(e.case, km.get(e.case.corridor_id), set(ledger_numbers))
        det = verdict_for(findings)
        codes = [f.code for f in findings]
        out.append(AblationCase("invoice", f"invoice-{e.case.seq}", e.kind,
                                _invoice_prompt(prompt, e.case, km.get(e.case.corridor_id), ledger_numbers),
                                det, det == e.expected_verdict,
                                {"expected_verdict": e.expected_verdict, "expected_finding": e.expected_finding},
                                {"det_codes": codes, "det_right_reason": (e.expected_finding in codes) if e.expected_finding else None}))
    return out, {"full_set_n": len(entries),
                 "full_set_deterministic": wilson(int(frame["verdict_correct"].sum()), len(frame)).as_dict()}


def exception_cases(n_total: int = 40) -> tuple[list[AblationCase], dict]:
    prompt = load_variant("exception_triage", "llm_verdict_v1")
    frame = pd.read_csv(RAW / "w6_exception_eval_cases.csv")
    frame["threshold_gap_min"] = (frame["predicted_gap_min"] / frame["excess_ratio"]).round(1)

    def det_sev(row) -> str:
        inv = Investigation(corridor_id=row["corridor_id"], audit_is_significant=bool(row["confirmed_slow"]),
                            audit_direction=SLOWER_THAN_NETWORK if row["confirmed_slow"] else None)
        return severity_for(row["predicted_gap_min"] / row["threshold_gap_min"], inv)

    frame["det"] = frame.apply(det_sev, axis=1)
    rows = [r for _, r in frame.iterrows()]
    per = max(1, n_total // 4)
    subset = pick_subset(rows, [r["det"] for r in rows], per)
    out = []
    for r in subset:
        text = prompt.render(corridor_id=r["corridor_id"], predicted_gap_min=r["predicted_gap_min"],
                             threshold_gap_min=r["threshold_gap_min"], confirmed_slow=str(bool(r["confirmed_slow"])).lower())
        out.append(AblationCase("exception", str(r["alert_id"])[-40:], r["det"], text, r["det"], True,
                                {"truly_delayed": int(r["truly_delayed"])}, {"published_severity": r["severity"]}))
    return out, {"full_set_n": len(frame), "deterministic_matches_published_grade":
                 int((frame["det"] == frame["severity"]).sum())}


# ── scoring one LLM verdict ──────────────────────────────────────────────────
def interpret(case: AblationCase, parsed: dict) -> dict:
    """Turn a parsed verdict into (label, correct, extras) for the agent."""
    if case.agent == "order":
        c = Case(**case.truth["case"])
        action = {"file": "file", "ask": "clarify", "reject": None}[parsed["verdict"]]
        sc = score_case(c, {"action": action, "order": parsed["order"], "missing_field": parsed["missing_field"]})
        text = f"{c.subject}\n{c.body}"
        codes = [parsed["order"].get(k) for k in ("origin_centre", "dest_centre") if parsed["order"].get(k)]
        unseen = [x for x in codes if str(x) not in text] if parsed["verdict"] == "file" else []
        return {"label": parsed["verdict"], "correct": bool(sc["correct"]),
                "invented": bool(sc["invented_fields"] or unseen) if parsed["verdict"] == "file" else False,
                "filed": parsed["verdict"] == "file"}
    if case.agent == "invoice":
        ok = parsed["verdict"] == case.truth["expected_verdict"]
        reason = None
        if case.truth["expected_finding"]:
            reason = parsed["reason_code"] == case.truth["expected_finding"]
        return {"label": parsed["verdict"], "correct": ok, "right_reason": reason}
    sev = parsed["verdict"]
    return {"label": sev, "correct": sev == case.det_verdict,
            "within_one": abs(SEVERITIES.index(sev) - SEVERITIES.index(case.det_verdict)) <= 1}


PARSERS = {"order": parse_order_verdict, "invoice": parse_invoice_verdict, "exception": parse_exception_verdict}


def run_case(case: AblationCase, caller: CALLER, ledger: Ledger, cache_dir: Path | None = None) -> dict:
    results = {}
    for run in ALL_RUNS:
        temperature = SAMPLED_TEMPERATURE if run in SAMPLED_RUNS else 0.0
        record = cached_call(case.agent, case.case_id, run, temperature, case.prompt_text, caller, ledger, cache_dir=cache_dir)
        try:
            results[run] = {**interpret(case, PARSERS[case.agent](record["text"])), "error": None,
                            "latency_s": record["latency_s"], "tokens": record["in_tok"] + record["out_tok"]}
        except VerdictParseError as exc:
            results[run] = {"label": "error", "correct": False, "error": str(exc)[:120],
                            "latency_s": record["latency_s"], "tokens": record["in_tok"] + record["out_tok"]}
    return results


# ── aggregation ──────────────────────────────────────────────────────────────
def auc(grades: list[int], truth: list[int]) -> float | None:
    from sklearn.metrics import roc_auc_score
    if len(set(truth)) < 2:
        return None
    return float(roc_auc_score(truth, grades))


def summarise_agent(agent: str, cases: list[AblationCase], runs: dict[str, dict[str, dict]], extra: dict) -> dict:
    n = len(cases)
    det_correct = [float(c.det_correct) for c in cases]
    sampled = [[runs[c.case_id][r] for r in SAMPLED_RUNS] for c in cases]
    labels = [[x["label"] for x in row] for row in sampled]
    t0 = [[runs[c.case_id][r] for r in TEMP0_RUNS] for c in cases]
    pooled = [x["correct"] for row in sampled for x in row]
    llm_case_mean = [float(np.mean([x["correct"] for x in row])) for row in sampled]
    t0_acc = [float(np.mean([row[0]["correct"]])) for row in t0]
    all_calls = [x for c in cases for r in ALL_RUNS for x in [runs[c.case_id][r]]]
    errors = sum(1 for x in all_calls if x["error"])
    lat = [x["latency_s"] for x in all_calls]
    toks = [x["tokens"] for x in all_calls]
    out: dict = {
        "agent": agent, "n_cases": n, **extra,
        "strata": dict(Counter(c.stratum for c in cases)),
        "deterministic": {"accuracy": wilson(int(sum(det_correct)), n).as_dict(),
                          "unanimity_across_5_runs": {"rate": 1.0, "note": "pure function; verified by double run in tests"}},
        "llm_sampled_T0.7": {"pooled_accuracy_5_runs": wilson(int(sum(pooled)), len(pooled)).as_dict(),
                             "mean_per_run_accuracy": round(float(np.mean(llm_case_mean)), 4),
                             "unanimity": unanimity(labels), "fleiss_kappa": fleiss_kappa(labels)},
        "llm_T0": {"accuracy_run_a": wilson(int(sum(t0_acc)), n).as_dict(),
                   "determinism_same_verdict_across_two_runs": wilson(
                       sum(1 for row in t0 if row[0]["label"] == row[1]["label"]), n).as_dict()},
        "parse_or_schema_errors": {"count": errors, "of_calls": len(all_calls)},
        "latency_s": {"mean": round(float(np.mean(lat)), 2), "p95": round(float(np.percentile(lat, 95)), 2)},
        "tokens_per_call_mean": round(float(np.mean(toks)), 1),
    }
    if agent != "exception":
        out["difference_llm_minus_deterministic"] = bootstrap_diff(llm_case_mean, det_correct)
    if agent == "order":
        filed = [x for row in sampled for x in row if x.get("filed")]
        out["llm_invented_value_rate"] = wilson(sum(1 for x in filed if x["invented"]), len(filed)).as_dict()
        det_inv = sum(1 for c in cases if c.meta["invented"])
        out["deterministic_orders_with_invented_values"] = det_inv
        should_ask = [row for c, row in zip(cases, sampled, strict=True) if c.truth["case"]["expected_action"] == "clarify"]
        asked = sum(1 for row in should_ask for x in row if x["label"] == "ask")
        out["llm_clarification_recall"] = wilson(asked, sum(len(r) for r in should_ask)).as_dict()
    if agent == "invoice":
        disp = [(c, row) for c, row in zip(cases, sampled, strict=True) if c.truth["expected_verdict"] == "dispute"]
        out["llm_dispute_recall"] = wilson(sum(1 for _, row in disp for x in row if x["label"] == "dispute"),
                                           sum(len(r) for _, r in disp)).as_dict()
        out["llm_false_disputes"] = sum(1 for c, row in zip(cases, sampled, strict=True)
                                        if c.truth["expected_verdict"] == "approve" for x in row if x["label"] == "dispute")
        reasons = [x["right_reason"] for row in sampled for x in row if x.get("right_reason") is not None]
        out["llm_right_reason"] = wilson(sum(reasons), len(reasons)).as_dict()
    if agent == "exception":
        within = [x["within_one"] for row in sampled for x in row if "within_one" in x]
        out["llm_exact_agreement_with_code_grade"] = out["llm_sampled_T0.7"]["pooled_accuracy_5_runs"]
        out["llm_within_one_grade"] = wilson(sum(within), len(within)).as_dict() if within else None
        truth = [c.truth["truly_delayed"] for c in cases]
        det_auc = auc([SEVERITIES.index(c.det_verdict) for c in cases], truth)
        llm_aucs = []
        for r in SAMPLED_RUNS:
            vals = [SEVERITIES.index(runs[c.case_id][r]["label"]) if runs[c.case_id][r]["label"] in SEVERITIES else -1 for c in cases]
            a = auc(vals, truth)
            if a is not None:
                llm_aucs.append(a)
        out["auc_grade_vs_truly_delayed"] = {"deterministic": det_auc, "llm_mean_over_5_runs": float(np.mean(llm_aucs)) if llm_aucs else None,
                                             "note": f"n={len(cases)}, stratified by code grade: compare arms, do not read as absolute"}
    return out


def cost_estimate(ledger: Ledger) -> dict:
    calls = max(1, ledger.calls)
    per_call = (ledger.input_tokens / calls * PRICE_PER_M_TOKENS[0] + ledger.output_tokens / calls * PRICE_PER_M_TOKENS[1]) / 1e6
    return {"free_tier_cost_usd": 0.0, "paid_equivalent_usd_per_1000_verdicts_ESTIMATE": round(per_call * 1000, 4),
            "assumed_price_usd_per_million_tokens_input_output": list(PRICE_PER_M_TOKENS),
            "basis": "mean measured tokens per call x provider public list price (assumed, check before quoting)"}


def ledger_from_cache(cache_dir: Path | None = None) -> dict:
    """The true live-call ledger, from the cache itself: one file is one billed provider call.

    A per-process counter would lose calls made before a restart, so the ledger is rebuilt
    from what is on disk. Provider failures are never cached and so are not counted here.
    """
    cache_dir = cache_dir or CACHE_DIR
    totals = {"live_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "by_agent": {}}
    for path in sorted(cache_dir.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        slot = totals["by_agent"].setdefault(record["agent"], {"live_calls": 0, "input_tokens": 0,
                                                              "output_tokens": 0, "latency_s": 0.0})
        for target in (totals, slot):
            target["live_calls"] += 1
            target["input_tokens"] += record["in_tok"]
            target["output_tokens"] += record["out_tok"]
            target["latency_s"] = round(target["latency_s"] + record["latency_s"], 3)
    return totals


def write_cases_csv(path: Path, all_cases: dict[str, tuple[list[AblationCase], dict]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["agent", "case_id", "stratum", "det_verdict", "det_correct", *ALL_RUNS, "llm_correct_of_5", "unanimous_5"])
        for agent, (cases, runs) in all_cases.items():
            for c in cases:
                got = runs.get(c.case_id)
                if got is None:
                    continue
                labels = [got[r]["label"] for r in ALL_RUNS]
                writer.writerow([agent, c.case_id, c.stratum, c.det_verdict, int(c.det_correct), *labels,
                                 sum(got[r]["correct"] for r in SAMPLED_RUNS), int(len(set(labels[:5])) == 1)])


# ── the held-out hard sets: deterministic arm on all, LLM once at temperature 0 ─────────
HARD_RUN = "t0h"
OUT_HARD = RAW / "b7_hard_sets_llm.json"
OUT_LEDGER_HARD = RAW / "b7_llm_ledger_hard_sets.json"


def order_hard_cases() -> list[AblationCase]:
    from src.ml.b7_hard_sets import build_order_hard

    prompt = load_variant("order_entry", "llm_verdict_v1")
    hard = build_order_hard()
    items = [Case(**asdict(o)) for o in hard]
    ordered = pick_subset(items, [c.template for c in items], 10)
    out = []
    for c in ordered:
        det = extract_order_rules(c.subject, c.body)
        sc = score_case(c, det)
        out.append(AblationCase("order", f"orderhard-{c.seq}", c.template,
                                prompt.render(email_subject=c.subject, email_body=c.body), det["action"],
                                bool(sc["correct"]), {"case": asdict(c)}, {"invented": bool(sc["invented_fields"])}))
    return out


def invoice_hard_cases() -> list[AblationCase]:
    from src.agents.exception_agent import load_audit
    from src.agents.invoice_auditor import InvoiceCase
    from src.ml.b7_hard_sets import build_invoice_boundary

    prompt = load_variant("invoice_audit", "llm_verdict_v1")
    hard = build_invoice_boundary()
    km = corridor_km_lookup(load_audit())
    rng = random.Random(SUBSET_SEED)
    ordered = pick_subset(list(range(len(hard))), [h.kind for h in hard], 10)
    out = []
    for i in ordered:
        h = hard[i]
        case = InvoiceCase(seq=h.seq, kind=h.kind, corridor_id=h.corridor_id, route_type=h.route_type,
                           weight_kg=h.weight_kg, pieces=h.pieces, external_invoice_number=h.external_invoice_number,
                           freight_charge=h.freight_charge, other_charges=h.other_charges,
                           total_amount=h.total_amount, currency=h.currency)
        ledger_numbers = rng.sample([x.external_invoice_number for j, x in enumerate(hard) if j != i], LEDGER_SIZE)
        findings = audit_invoice(case, km.get(h.corridor_id), set(ledger_numbers))
        det = verdict_for(findings)
        codes = [f.code for f in findings]
        out.append(AblationCase("invoice", f"invoicehard-{h.seq}", h.kind,
                                _invoice_prompt(prompt, case, km.get(h.corridor_id), ledger_numbers), det,
                                det == h.expected_verdict,
                                {"expected_verdict": h.expected_verdict, "expected_finding": h.expected_finding},
                                {"det_codes": codes}))
    return out


def run_hard(caller: CALLER, ledger: Ledger, limit: int | None = None) -> dict:
    from src.agents.llm import ProviderRateLimited

    result: dict = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "pre_registered_in": "D-086", "model": MODEL, "temperature": 0.0, "runs_per_case": 1,
                    "held_out": True, "synthetic": True, "agents": {}}
    for agent, builder in (("order", order_hard_cases), ("invoice", invoice_hard_cases)):
        cases = builder()[:limit]
        rows, halted = [], None
        for c in cases:
            try:
                record = cached_call(agent, c.case_id, HARD_RUN, 0.0, c.prompt_text, caller, ledger)
            except ProviderRateLimited as exc:
                halted = str(exc)
                break
            try:
                got = {**interpret(c, PARSERS[agent](record["text"])), "error": None}
            except VerdictParseError as exc:
                got = {"label": "error", "correct": False, "error": str(exc)[:120]}
            rows.append((c, got))
        by_stratum: dict[str, list[tuple[bool, bool]]] = {}
        for c, got in rows:
            by_stratum.setdefault(c.stratum, []).append((c.det_correct, got["correct"]))
        result["agents"][agent] = {
            "cases_completed": len(rows), "of": len(cases), "halted_by_provider_limit": halted,
            "deterministic_on_same_cases": wilson(sum(c.det_correct for c, _ in rows), len(rows)).as_dict() if rows else None,
            "llm_T0": wilson(sum(g["correct"] for _, g in rows), len(rows)).as_dict() if rows else None,
            "parse_or_schema_errors": sum(1 for _, g in rows if g["error"]),
            "llm_invented_value_orders": sum(1 for _, g in rows if g.get("invented")) if agent == "order" else None,
            "by_stratum": {k: {"deterministic": wilson(sum(a for a, _ in v), len(v)).as_dict(),
                               "llm_T0": wilson(sum(b for _, b in v), len(v)).as_dict()}
                           for k, v in sorted(by_stratum.items())},
        }
    OUT_HARD.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


BUILDERS = {"order": order_cases, "invoice": invoice_cases, "exception": exception_cases}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--llm-verdict", action="store_true", help="also run the LLM-decides arm (cached)")
    ap.add_argument("--agents", default="order,invoice,exception")
    ap.add_argument("--n", type=int, default=40, help="cases per agent in the LLM subset")
    ap.add_argument("--hard-sets", action="store_true", help="run the held-out hard sets once at T=0 (needs --llm-verdict)")
    ap.add_argument("--limit", type=int, default=None, help="cap on hard-set cases per agent (balanced prefix)")
    ap.add_argument("--stop-after-min", type=float, default=None,
                    help="stop starting new cases after this many minutes (time budget, D-086 subset policy)")
    args = ap.parse_args()

    from src.agents.llm import ProviderRateLimited

    caller = default_caller() if args.llm_verdict else None
    ledger = Ledger()
    if args.hard_sets:
        if caller is None:
            ap.error("--hard-sets needs --llm-verdict")
        print(json.dumps(run_hard(caller, ledger, args.limit), indent=1))
        OUT_LEDGER_HARD.write_text(json.dumps({**asdict(ledger), "model": MODEL, **cost_estimate(ledger)}, indent=2), encoding="utf-8")
        return 0
    summary: dict = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                     "pre_registered_in": "D-086", "provider": PROVIDER, "model": MODEL,
                     "model_note": "open model on a free tier; NOT the Gemini model that writes the prose",
                     "sampled_temperature": SAMPLED_TEMPERATURE, "agents": {}}
    csv_data = {}
    agents = [a for a in args.agents.split(",") if a]
    built = {agent: BUILDERS[agent](args.n) for agent in agents}
    all_runs: dict[str, dict[str, dict]] = {agent: {} for agent in agents}
    halted_by: dict[str, str | None] = dict.fromkeys(agents)
    stop_at = time.monotonic() + args.stop_after_min * 60 if args.stop_after_min else None
    if caller is not None:
        # Interleaved by case index, so whatever the quota or the time budget allows, every
        # agent has completed the same number of (balanced-prefix) cases.
        for i in range(max(len(built[a][0]) for a in agents)):
            if stop_at is not None and time.monotonic() > stop_at:
                break
            for agent in agents:
                cases = built[agent][0]
                if i >= len(cases) or halted_by[agent]:
                    continue
                try:
                    all_runs[agent][cases[i].case_id] = run_case(cases[i], caller, ledger)
                except ProviderRateLimited as exc:
                    halted_by[agent] = str(exc)
    for agent in agents:
        cases, extra = built[agent]
        entry: dict = {"agent": agent, "subset_n": len(cases), **extra,
                       "deterministic_on_subset": wilson(sum(c.det_correct for c in cases), len(cases)).as_dict()}
        if caller is not None:
            runs = all_runs[agent]
            halted = halted_by[agent]
            done = [c for c in cases if c.case_id in runs]
            if done:
                entry = {**entry, **summarise_agent(agent, done, runs, extra)}
                csv_data[agent] = (done, runs)
            entry["cases_completed"] = len(done)
            entry["halted_by_provider_limit"] = halted
        summary["agents"][agent] = entry
        print(agent, {k: v for k, v in entry.items() if k in ("subset_n", "cases_completed", "halted_by_provider_limit")}, flush=True)
    if caller is not None:
        summary["cost"] = cost_estimate(ledger)
        live = ledger_from_cache()
        OUT_LEDGER.write_text(json.dumps({
            **live, "model": MODEL, "provider": PROVIDER,
            "note": "rebuilt from the on-disk cache: one file is one provider call; includes the hard-set runs and 3 smoke calls",
            **cost_estimate(Ledger(calls=live["live_calls"], input_tokens=live["input_tokens"],
                                   output_tokens=live["output_tokens"]))}, indent=2), encoding="utf-8")
        write_cases_csv(OUT_CSV, csv_data)
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT_JSON.name}; live key present: {bool(os.environ.get('GROQ_API_KEY'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
