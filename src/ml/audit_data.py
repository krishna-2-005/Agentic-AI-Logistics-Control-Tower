"""Spark-free access to the OD legs behind the corridor audit.

The audit in `src.ml.audit` runs on Spark and publishes `w2_corridor_audit.csv`. The
dependence-aware, shrinkage and stability studies (B3, B4, B5) need the same statistic
leg by leg, so this module loads the legs with pandas and rebuilds the audit's exact
corridor-versus-rest Welch test on them.

The per-leg statistic is `r_i = log(actual_time / osrm_time)`, which Stage 2 stores as
`log_gap_ratio`; `load_legs` checks the stored column against that formula. The Welch
maths is not re-implemented: `src.ml.audit.welch_against_network` is pure pandas and is
called as is, on a corridor table whose sums come from the legs here instead of from a
Spark aggregation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.common import config
from src.ml.audit import ALPHA, STAT, correct_and_rank, welch_against_network

LEGS_PATH = config.PROCESSED_DIR / "trips_v1"
PUBLISHED_AUDIT = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"
MIN_SUPPORT = 10


def load_legs(path=LEGS_PATH) -> pd.DataFrame:
    """One row per OD leg: `leg_id`, `trip_uuid`, `schedule`, `corridor_id`, `r`, `created`, `day`.

    `schedule` is `route_schedule_uuid`, the recurring service a trip ran under.

    Applies the audit's own filter (statistic defined, `osrm_time > 0`) and checks that
    `log_gap_ratio` equals `log(actual_time / osrm_time)` on every row.
    """
    raw = pd.read_parquet(path)
    keep = raw[STAT].notna() & np.isfinite(raw[STAT]) & (raw["osrm_time"] > 0)
    raw = raw.loc[keep].reset_index(drop=True)
    recomputed = np.log(raw["actual_time"] / raw["osrm_time"])
    if not np.allclose(recomputed, raw[STAT], atol=1e-9, equal_nan=False):
        raise AssertionError("log_gap_ratio is not log(actual_time / osrm_time)")
    created = pd.to_datetime(raw["trip_creation_time"])
    legs = pd.DataFrame(
        {
            "leg_id": np.arange(len(raw)),
            "trip_uuid": raw["trip_uuid"].to_numpy(),
            "schedule": raw["route_schedule_uuid"].astype(str).to_numpy(),
            "corridor_id": raw["corridor_id"].to_numpy(),
            "r": raw[STAT].to_numpy(dtype=float),
            "created": created.to_numpy(),
            "day": created.dt.normalize().to_numpy(),
        }
    )
    return legs


def network_totals(r: np.ndarray) -> dict:
    """The sums `welch_against_network` subtracts a corridor from."""
    r = np.asarray(r, dtype=float)
    return {"n": int(r.size), "sum": float(r.sum()), "sumsq": float((r * r).sum())}


def corridor_table(legs: pd.DataFrame, min_support: int = MIN_SUPPORT) -> pd.DataFrame:
    """Corridors with at least `min_support` legs and the sums the Welch test needs."""
    g = legs.assign(rr=legs["r"] ** 2).groupby("corridor_id", sort=True)
    tab = g.agg(
        n_legs=("r", "size"),
        n_trips=("trip_uuid", "nunique"),
        sum_log=("r", "sum"),
        sumsq_log=("rr", "sum"),
    ).reset_index()
    return tab[tab["n_legs"] >= min_support].reset_index(drop=True)


def welch_audit(
    legs: pd.DataFrame, min_support: int = MIN_SUPPORT, alpha: float = ALPHA
) -> pd.DataFrame:
    """The published audit on `legs`: corridor vs the rest, Welch, BH at `alpha`.

    The network totals are those of `legs` itself, so applied to a subset of days this
    is the audit run independently on that subset.
    """
    tab = corridor_table(legs, min_support)
    if tab.empty:
        return tab
    out = welch_against_network(tab, network_totals(legs["r"].to_numpy()))
    return correct_and_rank(out, alpha)


def significant_sets(audited: pd.DataFrame) -> tuple[set, set]:
    """(slower, faster) corridor ids that are significant."""
    sig = audited[audited["is_significant"]]
    slower = set(sig.loc[sig["direction"] == "worse", "corridor_id"])
    faster = set(sig.loc[sig["direction"] == "better", "corridor_id"])
    return slower, faster


# ── Dependence diagnostics (B3, run before the permutation scheme is chosen) ───────────

DIAGNOSTICS_PATH = config.BENCHMARKS_RAW_DIR / "b3_dependence_diagnostics.json"


def anova_icc(values: np.ndarray, groups: np.ndarray) -> dict:
    """One-way ANOVA intraclass correlation with unbalanced groups.

    Returns the ICC (`rho`), the effective group size `n0` and the group count. A value
    near zero means observations in one group are no more alike than strangers.
    """
    codes, k = pd.factorize(groups)[0], None
    k = int(codes.max()) + 1
    n_g = np.bincount(codes, minlength=k).astype(float)
    s_g = np.bincount(codes, weights=values, minlength=k)
    n_tot = float(values.size)
    grand = values.mean()
    ssb = float((s_g**2 / n_g).sum() - n_tot * grand**2)
    ssw = float((values**2).sum() - (s_g**2 / n_g).sum())
    msb, msw = ssb / (k - 1), ssw / (n_tot - k)
    n0 = (n_tot - float((n_g**2).sum()) / n_tot) / (k - 1)
    rho = (msb - msw) / (msb + (n0 - 1) * msw)
    return {"rho": float(rho), "n0": float(n0), "groups": k}


def dependence_diagnostics(legs: pd.DataFrame, min_support: int = MIN_SUPPORT) -> dict:
    """The data facts that decide how the corridor test's dependence is handled."""
    tab = corridor_table(legs, min_support)
    tested = legs[legs["corridor_id"].isin(tab["corridor_id"])].copy()
    tested["res"] = tested["r"] - tested.groupby("corridor_id")["r"].transform("mean")
    days_per_c = tested.groupby("corridor_id")["day"].nunique()
    repeat = (tab["n_legs"] - tab["n_trips"]).to_numpy()
    legs_per_trip = legs.groupby("trip_uuid").size()
    cells = tested.groupby(["corridor_id", "day"]).size()

    icc_corridor = anova_icc(tested["r"].to_numpy(), tested["corridor_id"].to_numpy())
    icc_day = anova_icc(tested["res"].to_numpy(), tested["day"].to_numpy())
    multi = tested[tested.groupby("trip_uuid")["r"].transform("size") > 1]
    icc_trip = anova_icc(multi["res"].to_numpy(), multi["trip_uuid"].to_numpy())
    tested["cell"] = tested["corridor_id"] + "|" + tested["schedule"]
    cell_n = tested.groupby("cell")["r"].transform("size")
    in_multi = tested[cell_n > 1]
    icc_cell = anova_icc(in_multi["res"].to_numpy(), in_multi["cell"].to_numpy())
    cells_per_c = tested.groupby("corridor_id")["cell"].nunique()
    m_cell = (tab.set_index("corridor_id")["n_legs"] / cells_per_c).clip(lower=1.0)
    de_cell = 1.0 + (m_cell - 1.0) * max(icc_cell["rho"], 0.0)

    # Design effects, 1 + (m - 1) * rho, for the two clusterings that can touch a
    # corridor's mean: legs on the same creation day, and legs of the same trip.
    m_day = (tab.set_index("corridor_id")["n_legs"] / days_per_c).clip(lower=1.0)
    de_day = 1.0 + (m_day - 1.0) * max(icc_day["rho"], 0.0)
    trip_size_w = float((legs_per_trip**2).sum() / legs_per_trip.sum())
    de_trip_rest = 1.0 + (trip_size_w - 1.0) * max(icc_trip["rho"], 0.0)

    def q(x) -> dict:
        x = np.asarray(x, dtype=float)
        return {
            "min": float(x.min()),
            "p25": float(np.percentile(x, 25)),
            "median": float(np.median(x)),
            "mean": float(x.mean()),
            "p75": float(np.percentile(x, 75)),
            "max": float(x.max()),
        }

    return {
        "n_legs": int(len(legs)),
        "n_trips": int(legs["trip_uuid"].nunique()),
        "n_creation_dates": int(legs["day"].nunique()),
        "first_date": str(legs["day"].min().date()),
        "last_date": str(legs["day"].max().date()),
        "min_support": min_support,
        "corridors_tested": int(len(tab)),
        "legs_in_tested_corridors": int(len(tested)),
        "legs_per_corridor": q(tab["n_legs"]),
        "trips_per_corridor": q(tab["n_trips"]),
        "days_per_corridor": q(days_per_c),
        "legs_per_trip": q(legs_per_trip),
        "corridors_where_a_trip_repeats_the_corridor": int((repeat > 0).sum()),
        "max_repeats_of_a_corridor_within_one_trip": int(repeat.max()),
        "corridor_day_cells": int(len(cells)),
        "legs_per_corridor_day_cell": q(cells),
        "icc_corridor_of_r": icc_corridor,
        "icc_day_of_corridor_demeaned_r": icc_day,
        "icc_trip_of_corridor_demeaned_r": icc_trip,
        "schedule_cells_per_corridor": q(cells_per_c),
        "corridors_with_one_schedule_cell": int((cells_per_c == 1).sum()),
        "legs_per_corridor_schedule_cell": q(tested.groupby("cell").size()),
        "icc_corridor_schedule_cell_of_corridor_demeaned_r": icc_cell,
        "design_effect_schedule_cell_within_corridor": q(de_cell),
        "effective_n_per_corridor_schedule_cell_design": q(
            tab.set_index("corridor_id")["n_legs"] / de_cell
        ),
        "design_effect_day_within_corridor": q(de_day),
        "design_effect_trip_on_rest_group": de_trip_rest,
        "effective_n_per_corridor_day_design": q(tab.set_index("corridor_id")["n_legs"] / de_day),
        "reading": (
            "A trip never visits the same corridor twice among the tested corridors, so a "
            "trip cannot cluster a corridor's own legs, and the creation day is nearly "
            "independent of the statistic. The cluster that does bind a corridor's legs is the "
            "recurring service (route_schedule_uuid): legs of one corridor and one schedule are "
            "alike (see the schedule-cell ICC and design effect). Caveat: a majority of the "
            "corridors run under a single schedule, where the corridor effect and the service "
            "effect cannot be told apart, and the within-corridor ICC estimate is biased "
            "downward by demeaning on the corridor; the design effect is a lower-bound guide."
        ),
    }


def main() -> None:
    import json

    legs = load_legs()
    out = dependence_diagnostics(legs)
    DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTICS_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
