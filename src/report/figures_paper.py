"""Figures that only the upgraded manuscripts use: forest plot, rolling-origin folds, architecture.

    python -m src.report.figures_paper

The forest plot reads `b2_significance.json` (day-block 95% intervals of the MAE difference to the bar, by
slice), the fold plot reads `b2_rolling_origin.csv`, and the architecture drawing is boxes and arrows with no
data behind it. Style comes from `src.report.style`; each figure is written as vector PDF and PNG.
"""

from __future__ import annotations

import json

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from src.common import config
from src.report import style

RAW = config.BENCHMARKS_RAW_DIR
FOREST_MODELS = (("lightgbm_l1_oldbase", "Reported (LightGBM, L1)", style.BLUE),
                 ("v2_gbt", "Served (Spark MLlib)", style.ORANGE))
HEADLINE = ("overall", "cold_asof", "warm_asof", "unseen_in_train")
NICE = {"overall": "all test legs", "cold_asof": "cold at query time", "warm_asof": "warm at query time",
        "unseen_in_train": "corridor unseen in training"}


def _label(key: str) -> str:
    if key in NICE:
        return NICE[key]
    group, _, value = key.partition(": ")
    return f"{group.replace('_', ' ')}: {value}"


def forest() -> plt.Figure:
    sig = json.loads((RAW / "b2_significance.json").read_text(encoding="utf-8"))["models"]
    keys = [k for k in sig["v2_gbt"]["vs_bar"] if k not in HEADLINE[1:] and not k.endswith("unseen")]
    fig, ax = plt.subplots(figsize=(style.COL_WIDTH_IN * 1.15, 0.2 * len(keys) + 0.8))
    for offset, (model, name, colour) in zip((-0.16, 0.16), FOREST_MODELS, strict=True):
        for row, key in enumerate(keys):
            cell = sig[model]["vs_bar"][key]
            lo, hi = cell["ci_block_day"]
            ax.plot([lo, hi], [row + offset] * 2, color=colour, lw=1.4)
            ax.plot(cell["delta_mae"], row + offset, "o", color=colour, ms=3.5, label=name if row == 0 else None)
    ax.axvline(0, color=style.INK, lw=0.8)
    ax.set_yticks(range(len(keys)), [_label(k) for k in keys])
    ax.invert_yaxis()
    ax.set_xlabel("MAE minus back-off bar (min); left of 0 = model better")
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=2, fontsize=7)
    fig.tight_layout()
    return fig


def folds() -> plt.Figure:
    """MAE by fold: the bar, the reported single-node model and, if its folds have run, the two Spark models."""
    zoo = pd.read_csv(RAW / "b2_rolling_origin_zoo.csv")
    fig, ax = plt.subplots(figsize=(style.COL_WIDTH_IN, 2.3))
    x = zoo["fold"]
    ax.plot(x, zoo["mae_backoff"], marker="s", color=style.GREY, label="back-off bar", lw=1.3, ms=4)
    ax.plot(x, zoo["mae_model"], marker="o", color=style.BLUE, label="reported (LightGBM)", lw=1.3, ms=4)
    spark = RAW / "b2_rolling_origin.csv"
    if spark.exists():
        s = pd.read_csv(spark)
        ax.plot(s["fold"], s["mae_v2_gbt"], marker="^", color=style.ORANGE, label="served (Spark)", lw=1.3, ms=4)
    ax.set_xticks(x, [str(a) for a in zoo["test_days"]])
    ax.set_xlabel("test days (train on all earlier days)")
    ax.set_ylabel("MAE (min)")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return fig


def architecture() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(style.FULL_WIDTH_IN, 2.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 36)
    ax.axis("off")

    def box(x, y, w, h, text, colour):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=colour, ec=style.INK, lw=0.8, alpha=0.9))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=6.2, color="black")

    def arrow(x0, y0, x1, y1):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=8, lw=0.9, color=style.INK))

    box(1, 24, 17, 9, "Public trip records\n144,867 scan rows", "#dfe8f5")
    box(24, 24, 17, 9, "Spark: clean, legs,\nas-of features", "#dfe8f5")
    box(47, 24, 19, 9, "Corridor audit\nWelch + BH/BY, permutation,\nempirical Bayes", "#fbe3c8")
    box(72, 24, 26, 9, "Batch models: median, back-off,\nSpark GBT, LightGBM zoo\n(intervals, rolling origin)", "#fbe3c8")
    box(24, 6, 17, 9, "Kafka replay of\nqueries and facts", "#dcefe9")
    box(47, 6, 19, 9, "Structured Streaming:\nevent-time state, same\nfeatures as batch", "#dcefe9")
    box(72, 6, 26, 9, "Agents: code decides, model\nwords it; alert, order, invoice,\nassistant; public API + site", "#efe6c8")
    arrow(18.5, 28.5, 23.5, 28.5)
    arrow(41.5, 28.5, 46.5, 28.5)
    arrow(66.5, 28.5, 71.5, 28.5)
    arrow(32.5, 23.5, 32.5, 15.5)
    arrow(41.5, 10.5, 46.5, 10.5)
    arrow(66.5, 10.5, 71.5, 10.5)
    arrow(85, 23.5, 85, 15.5)
    fig.tight_layout()
    return fig


def agent_ablation() -> plt.Figure:
    """Pilot ablation: accuracy with Wilson 95% intervals for the rules and a model deciding, order and invoice."""
    big = json.loads((RAW / "b7_agent_ablation.json").read_text(encoding="utf-8"))["agents"]
    small = json.loads((RAW / "b7_agent_ablation_gpt-oss-20b.json").read_text(encoding="utf-8"))["agents"]
    hard = json.loads((RAW / "b7_hard_sets_deterministic.json").read_text(encoding="utf-8"))
    rows = [
        (f"order: rules (n={big['order']['n_cases']})", big["order"]["deterministic"]["accuracy"], style.BLUE),
        ("order: 120b model (5 runs)", big["order"]["llm_sampled_T0.7"]["pooled_accuracy_5_runs"], style.ORANGE),
        ("order: 20b model (5 runs, n=8)", small["order"]["llm_sampled_T0.7"]["pooled_accuracy_5_runs"], style.YELLOW),
        ("order: rules, held-out hard set", hard["order"]["overall"], style.BLUE),
        (f"invoice: rules (n={big['invoice']['n_cases']})", big["invoice"]["deterministic"]["accuracy"], style.BLUE),
        ("invoice: 120b model (5 runs)", big["invoice"]["llm_sampled_T0.7"]["pooled_accuracy_5_runs"], style.ORANGE),
    ]
    fig, ax = plt.subplots(figsize=(style.COL_WIDTH_IN * 1.15, 2.4))
    for y, (_, cell, colour) in enumerate(rows):
        ax.plot([cell["ci_low"], cell["ci_high"]], [y, y], color=colour, lw=1.6)
        ax.plot(cell["rate"], y, "o", color=colour, ms=4)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0.3, 1.02)
    ax.set_xlabel("accuracy (Wilson 95% interval)")
    ax.set_title("Pilot scale: the rules' score on the first set is not held out", fontsize=7)
    fig.tight_layout()
    return fig


def power_curves() -> plt.Figure:
    """Power and false discovery proportion of the four audit variants against the planted shift (D-099)."""
    data = json.loads((RAW / "b9_power.json").read_text(encoding="utf-8"))["results"]
    deltas = [r["delta"] for r in data if r["delta"] > 0]
    styles = {"bh_welch": ("Welch, BH", style.ORANGE, "o"), "by_welch": ("Welch, BY", style.YELLOW, "s"),
              "bh_perm": ("cell permutation, BH", style.BLUE, "^"), "by_perm": ("cell permutation, BY", style.AQUA, "v")}
    fig, axes = plt.subplots(1, 2, figsize=(style.COL_WIDTH_IN * 1.9, 2.4), sharex=True)
    for key, (label, colour, marker) in styles.items():
        axes[0].plot(deltas, [r["power"][key] for r in data if r["delta"] > 0], marker=marker, color=colour, label=label, lw=1.3, ms=4)
        axes[1].plot(deltas, [r["false_discovery_proportion"][key] for r in data if r["delta"] > 0], marker=marker, color=colour, lw=1.3, ms=4)
    axes[0].axhline(0.8, color=style.GREY, lw=0.8, ls="--")
    axes[1].axhline(0.05, color=style.GREY, lw=0.8, ls="--")
    axes[0].set_ylabel("share of planted corridors found")
    axes[1].set_ylabel("false discovery proportion")
    for ax in axes:
        ax.set_xlabel("planted shift in log ratio")
        ax.set_ylim(-0.02, 1.02)
    axes[0].legend(frameon=False, fontsize=6.5, loc="center right")
    fig.tight_layout()
    return fig


def main() -> int:
    style.apply_style()
    style.save(forest(), "fig_forest_delta_mae")
    style.save(architecture(), "fig_architecture")
    style.save(agent_ablation(), "fig_agent_ablation")
    if (RAW / "b9_power.json").exists():
        style.save(power_curves(), "fig_power_curves")
    if (RAW / "b2_rolling_origin_zoo.csv").exists():
        style.save(folds(), "fig_rolling_origin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
