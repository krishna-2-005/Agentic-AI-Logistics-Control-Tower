"""Planning-time and buffer indices against the corridor audit (D-100, upgrade B11).

    python -m src.ml.audit_indices

The freight-reliability literature describes a corridor by its planning time index (95th percentile of travel time over
free-flow time) and its buffer index ((95th percentile minus mean) over mean). Here both are computed on the ratio scale
`q = exp(r)` (realised over the recorded OSRM time, the recorded OSRM time standing in for free-flow time) for the 1,130
corridors the audit tests, and compared with the audit's ranking and with each other for stability across the two halves of
the creation dates of D-082. Writes `b11_reliability_indices.json` and `b11_reliability_indices_corridors.csv`.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import audit_data
from src.ml.stability import assign_parts

log = get_logger("ml.audit_indices")

RAW = config.BENCHMARKS_RAW_DIR
OUT_JSON = RAW / "b11_reliability_indices.json"
OUT_CSV = RAW / "b11_reliability_indices_corridors.csv"
SEED = 20261001
MIN_LEGS = 10
HALF_FLOOR = 5
TOP_N = 20
BOOTSTRAP = 2000


def indices(legs: pd.DataFrame, floor: int) -> pd.DataFrame:
    """One row per corridor with at least `floor` legs: n, mean log ratio, planning time index, buffer index."""
    rows = []
    for corridor, group in legs.groupby("corridor_id", sort=True):
        if len(group) < floor:
            continue
        q = np.exp(group["r"].to_numpy(dtype=float))
        p95 = float(np.percentile(q, 95))
        mean = float(q.mean())
        rows.append((corridor, len(q), float(group["r"].mean()), p95, (p95 - mean) / mean))
    return pd.DataFrame(rows, columns=["corridor_id", "n_legs", "mean_log", "pti", "bi"]).set_index("corridor_id")


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def top(frame: pd.DataFrame, column: str, n: int = TOP_N) -> set:
    return set(frame[column].sort_values(ascending=False).head(n).index)


def bootstrap_spearman(x: np.ndarray, y: np.ndarray, reps: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(reps):
        idx = rng.integers(0, len(x), len(x))
        values.append(float(spearmanr(x[idx], y[idx])[0]))
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def run() -> dict:
    legs = audit_data.load_legs()
    full = indices(legs, MIN_LEGS)
    published = pd.read_csv(audit_data.PUBLISHED_AUDIT).set_index("corridor_id")
    slower = published[published["is_significant"].astype(bool) & (published["direction"] == "worse")]
    audit_top = set(slower.sort_values("excess_ratio", ascending=False).head(TOP_N).index)
    result: dict = {
        "generated_at": datetime.now(UTC).isoformat(), "decision": "D-100", "seed": SEED, "corridors": int(len(full)),
        "definitions": "ratio scale q = exp(r); PTI = P95(q); BI = (P95(q) - mean(q)) / mean(q)",
        "against_audit": {
            "spearman_pti_vs_mean_log": float(spearmanr(full["pti"], full["mean_log"])[0]),
            "spearman_bi_vs_mean_log": float(spearmanr(full["bi"], full["mean_log"])[0]),
            "top20_jaccard_pti_vs_audit": jaccard(top(full, "pti"), audit_top),
            "top20_jaccard_bi_vs_audit": jaccard(top(full, "bi"), audit_top),
            "top20_jaccard_mean_log_vs_audit": jaccard(top(full, "mean_log"), audit_top),
        },
    }
    parts = assign_parts(legs, 2)
    first = indices(legs[parts == 0], HALF_FLOOR)
    second = indices(legs[parts == 1], HALF_FLOOR)
    both = first.join(second, lsuffix="_h1", rsuffix="_h2", how="inner")
    stability: dict = {"universe": int(len(both))}
    for name, column in (("mean_log", "mean_log"), ("pti", "pti"), ("bi", "bi")):
        x, y = both[f"{column}_h1"].to_numpy(), both[f"{column}_h2"].to_numpy()
        stability[name] = {
            "spearman": float(spearmanr(x, y)[0]),
            "ci95": bootstrap_spearman(x, y, BOOTSTRAP, SEED),
            "top20_jaccard": jaccard(set(both[f"{column}_h1"].sort_values(ascending=False).head(TOP_N).index),
                                     set(both[f"{column}_h2"].sort_values(ascending=False).head(TOP_N).index)),
        }
    result["stability_halves"] = stability
    result["note"] = ("legs of one recurring service are correlated, so a 95th percentile of 10 to 15 legs is a noisy "
                      "statistic and is not corrected for it (D-083)")
    full.to_csv(OUT_CSV)
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
