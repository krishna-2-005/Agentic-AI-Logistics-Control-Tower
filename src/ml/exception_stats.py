"""Uncertainty for the Exception agent's precision claim (B8, D-085).

    python -m src.ml.exception_stats

Reads only counts already published in ``w8_replay_leakage.json`` (the same 2,000 replayed
legs scored two ways: as-of history, and the superseded end-of-data snapshot) and writes
``b8_exception_stats.json``. No Spark, no model, no network.

Why the test is not a plain two-proportion test
-----------------------------------------------
The agent's precision is the delayed share *among the legs it alerted on*. The trivial
policy ("alert every leg") has precision equal to the delayed share among *all* legs. The
alerted legs are a subset of all legs, so the two samples overlap and an independent
two-proportion test is invalid. With w the alerted share::

    trivial = w * p_alerted + (1 - w) * p_not_alerted
    gain    = p_alerted - trivial = (1 - w) * (p_alerted - p_not_alerted)

so "the gain is zero" is exactly "alerted and not-alerted legs are delayed at the same
rate", a comparison of two disjoint groups. That is the primary test. A bootstrap over the
legs gives an interval for the gain itself. The naive independent test is reported, flagged
invalid, only so its number is not a mystery.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

import numpy as np
from scipy import stats as sps

from src.common import config
from src.ml.stats import wilson

SRC = config.BENCHMARKS_RAW_DIR / "w8_replay_leakage.json"
OUT = config.BENCHMARKS_RAW_DIR / "b8_exception_stats.json"

BOOT_RESAMPLES = 10_000
BOOT_SEED = 20260
SEVERITIES = ("low", "medium", "high", "critical")


def cochran_armitage(successes: list[int], totals: list[int], scores: list[float] | None = None) -> dict:
    """Cochran-Armitage test for a linear trend in a proportion across ordered groups.

    z = T / sqrt(Var), T = sum s_i (x_i - n_i * pbar),
    Var = pbar (1 - pbar) [sum n_i s_i^2 - (sum n_i s_i)^2 / N]. Two-sided p from the normal.
    """
    if len(successes) != len(totals) or len(totals) < 2:
        raise ValueError("need matching successes/totals for at least two groups")
    s = np.asarray(scores if scores is not None else range(1, len(totals) + 1), dtype=float)
    x = np.asarray(successes, dtype=float)
    n = np.asarray(totals, dtype=float)
    big_n = n.sum()
    pbar = x.sum() / big_n
    t_stat = float((s * (x - n * pbar)).sum())
    var = pbar * (1 - pbar) * float((n * s**2).sum() - (n * s).sum() ** 2 / big_n)
    z = t_stat / math.sqrt(var) if var > 0 else 0.0
    return {"z": round(z, 4), "p_two_sided": float(2 * sps.norm.sf(abs(z))),
            "direction": "increasing" if z > 0 else "decreasing" if z < 0 else "flat"}


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> dict:
    """Pooled two-proportion z-test (two-sided) for p1 = p2 between independent groups."""
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else 0.0
    return {"z": round(z, 4), "p_two_sided": float(2 * sps.norm.sf(abs(z)))}


def bootstrap_gain(tp: int, alerted: int, delayed_total: int, legs: int,
                   resamples: int = BOOT_RESAMPLES, seed: int = BOOT_SEED) -> dict:
    """Bootstrap the gain (alerted precision minus all-legs delayed rate) over legs.

    A leg is one of four cells (alerted/not x delayed/not); the statistic depends only on
    the cell counts, so resampling legs is a multinomial draw on the cells. Alerted and
    not-alerted legs are resampled together, which keeps the two policies paired.
    """
    cells = np.array([tp, alerted - tp, delayed_total - tp, legs - alerted - (delayed_total - tp)])
    if (cells < 0).any():
        raise ValueError("inconsistent counts")
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(legs, cells / legs, size=resamples)
    a_tp, a_fp, n_tp, _ = draws.T
    alerted_n = a_tp + a_fp
    ok = alerted_n > 0
    gain = a_tp[ok] / alerted_n[ok] - (a_tp[ok] + n_tp[ok]) / legs
    low, high = np.percentile(gain, [2.5, 97.5])
    return {"resamples": resamples, "seed": seed, "ci_low": round(float(low), 4),
            "ci_high": round(float(high), 4), "p_one_sided_gain_le_0": float((gain <= 0).mean())}


def policy_vs_trivial(label: str, tp: int, alerted: int, delayed_total: int, legs: int) -> dict:
    not_alerted = legs - alerted
    tp_not = delayed_total - tp
    gain = tp / alerted - delayed_total / legs
    z_test = two_prop_z(tp, alerted, tp_not, not_alerted)
    fisher = sps.fisher_exact([[tp, alerted - tp], [tp_not, not_alerted - tp_not]])
    boot = bootstrap_gain(tp, alerted, delayed_total, legs)
    significant = bool(gain > 0 and z_test["p_two_sided"] < 0.05 and boot["ci_low"] > 0)
    if significant:
        text = (f"better than alerting every leg by {100 * gain:.2f} points; significant at 5% "
                f"(n = {legs:,} legs, {alerted:,} alerts)")
    elif gain > 0:
        text = f"directionally better; not significant at n = {legs:,} legs ({alerted:,} alerts)"
    else:
        text = f"not better than alerting every leg (n = {legs:,} legs)"
    return {
        "label": label,
        "legs": legs,
        "agent_precision": wilson(tp, alerted).as_dict(),
        "trivial_policy_precision": wilson(delayed_total, legs).as_dict(),
        "not_alerted_delayed_rate": wilson(tp_not, not_alerted).as_dict(),
        "gain_points": round(100 * gain, 2),
        "primary_test": {
            "name": "pooled two-proportion z, alerted vs not alerted (disjoint groups)",
            **z_test,
            "fisher_exact_p": float(fisher.pvalue),
        },
        "bootstrap_gain": boot,
        "naive_independent_test_INVALID_overlapping_samples": two_prop_z(tp, alerted, delayed_total, legs),
        "significant_at_5pct": significant,
        "write_up": text,
    }


def severity_table(by_severity: list[dict], trivial: float) -> dict:
    by_name = {b["severity"]: b for b in by_severity}
    rows, xs, ns = [], [], []
    for sev in SEVERITIES:
        b = by_name[sev]
        w = wilson(b["truly_delayed"], b["notified"])
        xs.append(b["truly_delayed"])
        ns.append(b["notified"])
        rows.append({"severity": sev, **w.as_dict(),
                     "ci_excludes_trivial_policy": bool(w.lower > trivial or w.upper < trivial)})
    return {"rows": rows, "cochran_armitage": cochran_armitage(xs, ns)}


def run() -> dict:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    legs = src["legs"]
    out: dict = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": SRC.name,
        "pre_registered_in": "D-085",
    }
    for key, label in (("exception_agent_as_of", "as_of"),
                       ("exception_agent_snapshot", "superseded_replay_snapshot")):
        block = src[key]
        alerted = block["alerts_scored"]
        tp = sum(b["truly_delayed"] for b in block["by_severity"])
        delayed_total = round(tp / block["recall_of_all_delayed"])  # the total the module scored against
        out[label] = {
            "overall": policy_vs_trivial(label, tp, alerted, delayed_total, legs),
            "by_severity": severity_table(block["by_severity"], delayed_total / legs),
        }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main() -> int:
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
