"""The model card and the data card print only numbers their source files hold (WP-10).

    pytest tests/test_cards.py -q

Each expected string is built *from the file*, not typed here, so a card that drifts from
its evidence fails, and so does a card whose evidence file changes underneath it.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "benchmarks" / "raw"
MODEL_CARD = (ROOT / "docs" / "model_card.md").read_text(encoding="utf-8")
DATA_CARD = (ROOT / "docs" / "data_card.md").read_text(encoding="utf-8")


def load(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def n(value: float) -> str:
    """Thousands separators, as the cards print counts."""
    return f"{int(value):,}"


# ── data card ────────────────────────────────────────────────────────────────
def data_card_expectations() -> list[str]:
    q = load("w1_clean_quality_report.json")
    r = load("w2_reconstruction_report.json")
    h = load("w2_hub_report.json")
    a = load("w2_audit_report.json")
    b = load("w3_baseline_report.json")
    with (RAW / "w1_delay_threshold_sensitivity.csv").open(encoding="utf-8") as f:
        rows = {row["threshold"]: row for row in csv.DictReader(f)}
    return [
        n(q["rows_in"]), n(q["distinct"]["trip_uuid"]), n(q["rows_out"]),
        f"| rows dropped (any reason) | **{q['rows_dropped_total']}** |",
        n(q["null_sentinels_converted"]["source_name"]), n(q["null_sentinels_converted"]["destination_name"]),
        n(q["states_inferred_from_pin"]),
        n(q["quality_flags"]["is_negative_segment"]), n(q["quality_flags"]["is_zero_osrm_segment"]),
        n(q["quality_flags"]["is_suspect"]),
        n(q["distinct"]["source_center"]), n(q["distinct"]["destination_center"]),
        n(q["route_type_counts"]["FTL"]), n(q["route_type_counts"]["Carting"]),
        f"**{n(r['legs_out'])} origin–destination legs**", f"**{n(r['corridors'])} corridors**",
        f"**{n(h['hubs_out'])} distinct facilities**", f"**{h['supported_hubs']}**",
        f"**{n(a['corridors_supported'])} have at least ten legs**",
        f"**{n(rows['2.0']['delayed_legs'])} legs ({rows['2.0']['delayed_pct']}%)**",
        f"{n(rows['1.25']['delayed_legs'])} ({rows['1.25']['delayed_pct']}%)",
        f"**{r['metrics']['frac_over_plan'] * 100:.1f}%**",
        f"**{r['metrics']['median_gap_ratio']:.1f}**",
        f"| median gap | {r['metrics']['median_gap_min']:.0f} min |",
        f"| mean gap | {r['metrics']['mean_gap_min']:.1f} min |",
        f"| median dwell | {r['metrics']['median_dwell_min']:.0f} min |",
        f"**{b['pct_corr_cold']:.2f}%**", f"{b['pct_src_cold']:.2f}% / {b['pct_dst_cold']:.2f}%",
    ]


@pytest.mark.parametrize("expected", data_card_expectations())
def test_the_data_card_prints_what_its_files_hold(expected):
    assert expected in DATA_CARD, f"data card does not say {expected!r}"


def test_the_committed_reports_carry_no_local_paths():
    for name in ("w1_clean_quality_report.json", "w2_reconstruction_report.json", "w2_hub_report.json"):
        text = (RAW / name).read_text(encoding="utf-8")
        assert '"input"' not in text and ":\\\\" not in text, name


# ── model card ───────────────────────────────────────────────────────────────
def model_card_expectations() -> list[str]:
    report = load("w7_model_v2_stepsize_report.json")
    baseline = load("w3_baseline_report.json")
    stream = load("w10_stream_validation_v2.json")
    equivalence = load("w10_gbt_local_equivalence.json")
    latency = load("f1_api_latency.json")
    out = [
        f"**{n(baseline['n_train'])}** / **{n(baseline['n_test'])}** legs",
        f"{n(report['validation']['n_fit'])} legs fit, {n(report['validation']['n_scored'])} scored",
        f"| trees, depth | {report['grid']['maxIter']}, depth {report['grid']['maxDepth']} |",
        f"| **this model** | **{report['test']['overall_mae_min']['v2_gbt_residual_absolute_step1']:.2f}** |",
        f"| corridor median (the fair baseline) | {report['test']['overall_mae_min']['corridor_median']:.2f} |",
        f"(best {report['validation']['mae_min_by_step_size']['1']:.2f} against "
        f"{report['validation']['corridor_median_mae_min']:.2f})",
        f"**{n(stream['all_legs']['identical_predictions'])} of {n(stream['all_legs']['legs'])} identical**, "
        f"{stream['identical_predictions']} of {stream['legs']} in the acceptance sample",
        f"MAE **{stream['test_split']['stream_mae_min']:.2f}**",
        f"| the public API's numpy reader against Spark, on every leg | "
        f"**{n(equivalence['identical_predictions'])} of {n(equivalence['legs'])} identical**",
        f"p50 {latency['p50_ms']:.0f} ms, p95 {latency['p95_ms']:.0f} ms",
    ]
    with (RAW / "w7_model_metrics_v2_stepsize.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    model = {(r["dimension"], r["slice"]): r for r in rows if r["model"] == "v2_gbt_residual_absolute_step1"}
    for (dimension, slice_), r in model.items():
        if dimension == "overall":
            continue
        # The unseen-corridor row is the one the card prints in bold.
        mae = f"{float(r['mae_min']):.2f}"
        mae = f"**{mae}**" if slice_ == "unseen" else mae
        out.append(f"| {n(r['n'])} | {float(r['median_baseline_mae_min']):.2f} | {mae} |")
    return out


@pytest.mark.parametrize("expected", model_card_expectations())
def test_the_model_card_prints_what_its_files_hold(expected):
    assert expected in MODEL_CARD, f"model card does not say {expected!r}"


def test_the_feature_count_is_the_models_own():
    from src.ml.models_v2 import FEATURES_V2

    assert f"**{len(FEATURES_V2)}**" in MODEL_CARD


def test_the_osrm_figure_is_the_frozen_one():
    freeze = json.loads((ROOT / "benchmarks" / "results_freeze_v4.json").read_text(encoding="utf-8"))
    osrm = {v["id"]: v["value"] for v in freeze["values"]}["mae_osrm"]
    assert f"| {osrm:.2f} |" in MODEL_CARD
