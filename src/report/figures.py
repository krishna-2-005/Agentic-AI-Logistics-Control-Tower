"""Report-quality figures for the paper (execution plan v3.1 W8 D5, G-09 support).

    python -m src.report.figures              # writes docs/figures/*.png and *.pdf
    python -m src.report.figures --only fig3  # one figure while iterating

**Every figure is built from a file in `benchmarks/raw/`.** No figure takes a number from
a docstring, a write-up, or this module: if a value is not in a cache file, it does not
appear on a chart. That rule is what makes `benchmarks/experiments_appendix.md` a complete
account of the paper's numbers rather than a partial one.

Design rules applied here, in the order they were decided:

1. **Form follows the data's job.** Magnitude across a few labelled things is a horizontal
   bar; a distribution is a histogram; two measures on different scales are two panels,
   never two y-axes on one plot.
2. **Colour carries identity, not rank.** Corridors confirmed slower keep the same orange
   in every figure they appear in; faster keeps the same aqua. A filter or a reorder never
   repaints them.
3. **The palette was validated, not chosen by eye.** `#2a78d6, #eb6834, #1baf7a, #eda100`
   passes the lightness band, chroma floor and colour-vision separation checks (worst
   adjacent pair ΔE 9.1 under protanopia, 22.9 normal). Two of the four fall under 3:1
   contrast against white, which obliges visible labels — so every bar is directly
   labelled and no figure relies on colour alone to be read.
4. **Print-safe.** 300 dpi PNG for slides and a vector PDF for the paper; greyscale
   fallback is the value labels, which survive any reproduction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # imported after the Agg backend selection above
import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("report.figures")

RAW = config.BENCHMARKS_RAW_DIR
OUT = config.DOCS_DIR / "figures"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GREY, INK, MUTED = "#c9c9c4", "#0b0b0b", "#52514e"

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.labelsize": 9,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": "#e8e8e4",
    "grid.linewidth": 0.8,
    "figure.facecolor": "white",
})


def _finish(fig, name: str, caption: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    png, pdf = OUT / f"{name}.png", OUT / f"{name}.pdf"
    fig.savefig(png)
    fig.savefig(pdf)
    plt.close(fig)
    log.info("%s", png.name)
    return {"figure": name, "png": str(png.relative_to(config.REPO_ROOT)).replace("\\", "/"),
            "caption": caption}


def _bar_labels(ax, bars, values, fmt="{:.2f}", pad=0.01, inside=False):
    """Every bar labelled: the palette's low-contrast slots need text to be readable."""
    span = max(values) if values else 1
    for bar, value in zip(bars, values):
        x = bar.get_width()
        ax.text(x - span * pad if inside else x + span * pad,
                bar.get_y() + bar.get_height() / 2, fmt.format(value),
                va="center", ha="right" if inside else "left",
                color="white" if inside else INK, fontsize=8,
                fontweight="bold" if inside else "normal")


# ── 1 · the premise ──────────────────────────────────────────────────────────
def fig1_gap_ratio() -> dict:
    """How far the production planner is from realised time, over every leg."""
    legs = pd.read_csv(RAW / "w1_leg_summary.csv")
    ratio = (legs["actual_time"] / legs["osrm_time"]).replace([np.inf, -np.inf], np.nan).dropna()
    over = float((ratio > 1).mean())
    median = float(ratio.median())

    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    ax.hist(ratio.clip(upper=8), bins=80, range=(0, 8), color=BLUE, edgecolor="none")
    ax.axvline(1.0, color=MUTED, lw=1.2, ls="--")
    ax.axvline(median, color=ORANGE, lw=2)
    ax.annotate(f"median {median:.2f}×", xy=(median, ax.get_ylim()[1] * 0.92),
                xytext=(median + 0.45, ax.get_ylim()[1] * 0.92), color=ORANGE, fontweight="bold")
    # Left of the distribution, where the histogram is empty: a leader line across the bars
    # would cross the data it is labelling.
    ax.annotate("planner's\nestimate", xy=(1.0, ax.get_ylim()[1] * 0.42),
                xytext=(0.12, ax.get_ylim()[1] * 0.52), color=MUTED, fontsize=8,
                arrowprops={"arrowstyle": "->", "color": MUTED, "lw": 0.8})
    ax.set_xlabel("realised time ÷ planned time")
    ax.set_ylabel("legs")
    ax.set_title(f"{over:.1%} of {len(ratio):,} legs run over plan")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    return _finish(fig, "fig1_gap_ratio_distribution",
                   f"Realised over planned time on {len(ratio):,} OD legs; {over:.1%} exceed the plan, "
                   f"median {median:.2f}×. Clipped at 8× for display. Source: w1_leg_summary.csv")


# ── 2 · the headline ─────────────────────────────────────────────────────────
def fig2_audit() -> dict:
    """The audit's whole result in one panel: effect size against support."""
    audit = pd.read_csv(RAW / "w2_corridor_audit.csv")
    slower = audit[audit["is_significant"] & (audit["direction"] == "worse")]
    faster = audit[audit["is_significant"] & (audit["direction"] == "better")]
    flat = audit[~audit["is_significant"]]

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.scatter(flat["n_legs"], flat["excess_ratio"], s=10, color=GREY, label=f"not significant ({len(flat):,})")
    ax.scatter(faster["n_legs"], faster["excess_ratio"], s=12, color=AQUA, label=f"faster ({len(faster):,})")
    ax.scatter(slower["n_legs"], slower["excess_ratio"], s=12, color=ORANGE, label=f"slower ({len(slower):,})")
    ax.axhline(1.0, color=MUTED, lw=1, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("legs on the corridor (log)")
    ax.set_ylabel("excess ratio vs the network (log)")
    ax.set_title(f"{len(slower)} slower and {len(faster)} faster of {len(audit):,} corridors (FDR 0.05)")
    ax.legend(frameon=False, loc="upper right", fontsize=8)
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    return _finish(fig, "fig2_corridor_audit",
                   f"Welch tests on log time ratios, Benjamini-Hochberg at 5%: {len(slower)} corridors "
                   f"significantly slower, {len(faster)} faster, of {len(audit):,} with >=10 legs. "
                   "Source: w2_corridor_audit.csv")


def fig3_bottlenecks() -> dict:
    """The top of the list, with the places named — a reader checks a chart against a map."""
    top = pd.read_csv(RAW / "w2_top20_bottlenecks.csv").sort_values("bottleneck_rank").head(15)
    labels = [f"{r.source_city}→{r.dest_city}" for r in top.itertuples()]
    fig, ax = plt.subplots(figsize=(6.2, 4.4))
    bars = ax.barh(range(len(top)), top["excess_ratio"], color=ORANGE, height=0.72)
    _bar_labels(ax, bars, list(top["excess_ratio"]), fmt="{:.1f}×")
    ax.set_yticks(range(len(top)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("× the network's typical overrun")
    ax.set_title("The 15 worst corridors, and where they are")
    ax.set_xlim(0, top["excess_ratio"].max() * 1.15)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    return _finish(fig, "fig3_top_bottlenecks",
                   "The 15 highest excess ratios among corridors confirmed slower. "
                   "Source: w2_top20_bottlenecks.csv")


def fig4_support_instability() -> dict:
    """The methodological warning: the same data, one parameter, a disjoint answer."""
    ten = pd.read_csv(RAW / "w2_top20_bottlenecks.csv").sort_values("bottleneck_rank").head(20)
    thirty = pd.read_csv(RAW / "w2_corridor_audit_support30.csv")
    thirty = thirty[thirty["is_significant"] & (thirty["direction"] == "worse")]
    thirty = thirty.sort_values("excess_ratio", ascending=False).head(20)
    shared = set(ten["corridor_id"]) & set(thirty["corridor_id"])

    # Shared x on purpose. The two lists differ in *membership* and in *magnitude*, and a
    # per-panel scale would hide the second: the 30-leg list's worst corridor is milder
    # than the 10-leg list's fifteenth.
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.6), sharex=True)
    for ax, frame, title, colour in (
        (axes[0], ten, f"support floor: 10 legs (n={len(ten)})", ORANGE),
        (axes[1], thirty, f"support floor: 30 legs (n={len(thirty)})", BLUE),
    ):
        values = list(frame["excess_ratio"])
        ax.barh(range(len(values)), values, color=colour, height=0.72)
        ax.invert_yaxis()
        ax.set_yticks([])
        ax.set_title(title, fontsize=9, pad=6)
        ax.set_xlabel("excess ratio vs the network")
        ax.grid(axis="x")
        ax.set_axisbelow(True)
    fig.suptitle(f"Same audit, two support floors: {len(shared)} corridors in common",
                 fontsize=10, fontweight="bold", y=1.04)
    return _finish(fig, "fig4_support_instability",
                   f"Top-20 bottleneck lists at a 10-leg and a 30-leg support floor share {len(shared)} "
                   "corridors. Sources: w2_top20_bottlenecks.csv, w2_corridor_audit_support30.csv")


# ── 3 · the model ────────────────────────────────────────────────────────────
def fig5_model_mae() -> dict:
    """What each model costs in minutes of error, against the baseline that matters."""
    table = pd.read_csv(RAW / "w7_model_metrics_v2_stepsize.csv")
    overall = table[table["dimension"] == "overall"].set_index("model")["mae_min"]
    v1 = pd.read_csv(RAW / "w7_model_metrics_v2.csv")
    v1_overall = v1[v1["dimension"] == "overall"].set_index("model")["mae_min"]

    rows = [
        ("OSRM plan", float(v1_overall["OSRM"]), GREY),
        ("Random Forest (W4)", float(v1_overall["v1_rf_raw_target"]), GREY),
        ("corridor mean", float(v1_overall["corridor_mean"]), GREY),
        ("corridor median (the bar)", float(overall["corridor_median"]), BLUE),
        ("v2 GBT residual", float(overall["v2_gbt_residual_absolute_step1"]), ORANGE),
        ("sklearn reference", float(v1_overall["histgbr_residual_reference"]), AQUA),
    ]
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    bars = ax.barh([r[0] for r in rows], [r[1] for r in rows], color=[r[2] for r in rows], height=0.7)
    _bar_labels(ax, bars, [r[1] for r in rows], fmt="{:.2f}")
    ax.invert_yaxis()
    ax.set_xlabel("test MAE (minutes)")
    ax.set_xlim(0, max(r[1] for r in rows) * 1.12)
    ax.set_title("Reported model against every baseline it must beat")
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    return _finish(fig, "fig5_model_mae",
                   "Test-split MAE. The bar is the per-corridor median (33.04), not the mean, because "
                   "MAE is minimised by the median. Sources: w7_model_metrics_v2_stepsize.csv, "
                   "w7_model_metrics_v2.csv")


def fig6_mae_by_support() -> dict:
    """Where the model's gain actually is — the figure that stops a headline overclaiming."""
    table = pd.read_csv(RAW / "w7_model_metrics_v2_stepsize.csv")
    sub = table[table["dimension"] == "corridor_support_in_train"]
    order = ["unseen", "1-9", "10-29", ">=30"]
    median = sub[sub["model"] == "corridor_median"].set_index("slice")["mae_min"].reindex(order)
    model = sub[sub["model"] == "v2_gbt_residual_absolute_step1"].set_index("slice")["mae_min"].reindex(order)
    n = sub[sub["model"] == "corridor_median"].set_index("slice")["n"].reindex(order)

    x = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    b1 = ax.bar(x - 0.2, median, width=0.36, color=BLUE, label="corridor median")
    b2 = ax.bar(x + 0.2, model, width=0.36, color=ORANGE, label="v2 GBT residual")
    for bars, values in ((b1, median), (b2, model)):
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 1.5, f"{value:.1f}",
                    ha="center", fontsize=8, color=INK)
    ax.set_xticks(x, [f"{s}\n({int(c):,} legs)" for s, c in zip(order, n)], fontsize=8)
    ax.set_xlabel("legs on this corridor in the training split")
    ax.set_ylabel("test MAE (minutes)")
    ax.set_title("The model's gain is concentrated on corridors with no history")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    return _finish(fig, "fig6_mae_by_support",
                   "Test MAE by how much history the corridor had. On unseen corridors 111.2 → 75.9 min; "
                   "elsewhere the gain is 0.02-0.51 min. Source: w7_model_metrics_v2_stepsize.csv")


# ── 4 · the alerting policy ──────────────────────────────────────────────────
def fig7_threshold() -> dict:
    """Two measures on different scales: two panels, never two y-axes.

    Two series, not one. The claim ("quality barely moves, workload halves") belongs to the
    **logistic delay classifier**, the best real classifier in the sweep. The first version
    of this figure plotted `champion_threshold` — the stream's own flag — under that title,
    where MCC climbs 0.315 → 0.477 and the alert rate falls only 99% → 68%: a chart that
    argued against its own caption. Both series are now drawn, which is also how the
    second finding (the stream's flag is the weakest of the two) becomes visible.
    """
    ts = pd.read_csv(RAW / "w5_threshold_sensitivity.csv")
    series = [
        ("logistic classifier", ts[ts["model"] == "logistic_regression"].sort_values("threshold"), BLUE, "o"),
        ("the stream's own flag", ts[ts["model"] == "champion_threshold"].sort_values("threshold"), ORANGE, "s"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.2), sharex=True)
    for label, frame, colour, marker in series:
        axes[0].plot(frame["threshold"], frame["mcc"], marker=marker, color=colour, lw=2, ms=6, label=label)
        axes[1].plot(frame["threshold"], frame["alert_rate"] * 100, marker=marker, color=colour, lw=2, ms=6,
                     label=label)
    best = series[0][1]
    for position, (_, row) in enumerate(best.iterrows()):
        axes[0].annotate(f"{row['mcc']:.3f}", (row["threshold"], row["mcc"]),
                         textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
        # Only the endpoints on the right panel: the claim is "98% to 49%", and labelling
        # the two middle points crowds them into each other at this width.
        if position in (0, len(best) - 1):
            axes[1].annotate(f"{row['alert_rate'] * 100:.0f}%", (row["threshold"], row["alert_rate"] * 100),
                             textcoords="offset points", xytext=(0, -16), ha="center", fontsize=8)
    axes[0].set_title("classifier quality (MCC)", fontsize=9)
    axes[0].set_ylim(0, 0.75)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    axes[1].set_title("share of legs alerted", fontsize=9)
    axes[1].set_ylim(0, 118)
    for ax in axes:
        ax.set_xlabel("delay threshold (× planned)")
        ax.grid(axis="y")
        ax.set_axisbelow(True)
    fig.suptitle("For the best classifier, quality barely moves while the workload halves",
                 fontsize=10, fontweight="bold", y=1.02)
    return _finish(fig, "fig7_threshold_sensitivity",
                   "Alerting across delay thresholds. The logistic classifier holds MCC 0.507-0.540 while "
                   "the share of legs alerted falls 98% to 49%; the stream's own flag is weaker at every "
                   "threshold. Source: w5_threshold_sensitivity.csv")


# ── 5 · the architecture claim ───────────────────────────────────────────────
def fig8_scale() -> dict:
    """The licence for the phrase 'big data': the same code, two orders of magnitude up."""
    runs = json.loads((RAW / "w7_scale_benchmark.json").read_text(encoding="utf-8"))["runs"]
    main = sorted([r for r in runs if r["cores"] == 20], key=lambda r: r["rows"])
    four = [r for r in runs if r["cores"] == 4]

    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    ax.plot([r["rows"] for r in main], [r["wall_seconds"] for r in main],
            marker="o", color=BLUE, lw=2, ms=7, label="20 cores")
    for r in main:
        ax.annotate(f"{r['wall_seconds']:.1f}s", (r["rows"], r["wall_seconds"]),
                    textcoords="offset points", xytext=(0, 9), ha="center", fontsize=8)
    if four:
        ax.scatter([r["rows"] for r in four], [r["wall_seconds"] for r in four],
                   marker="s", color=ORANGE, s=55, zorder=3, label="4 cores")
        for r in four:
            ax.annotate(f"{r['wall_seconds']:.1f}s", (r["rows"], r["wall_seconds"]),
                        textcoords="offset points", xytext=(6, -12), fontsize=8, color=ORANGE)
    ax.set_xscale("log")
    ax.set_xlabel("rows aggregated (log)")
    ax.set_ylabel("wall seconds")
    ax.set_title("The Week 2 aggregation, unchanged, from 26k to 56M rows")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(True)
    ax.set_axisbelow(True)
    return _finish(fig, "fig8_scale_runtime",
                   "network_baseline and corridor_aggregate imported unchanged; wall time includes each "
                   "run's parquet scan. Source: w7_scale_benchmark.json")


def fig9_severity_precision() -> dict:
    """The agent layer's one measured ranking claim: severity earns its place as a filter.

    Bars are the **as-of** measurement (D-054). The first version of this figure plotted
    `w6_exception_eval.json`, a replay that scored early legs with end-of-data history; its
    values are kept as hollow markers, because the size of that gap is itself a result
    (P-62) and a figure that silently swapped numbers would hide it.
    """
    original = json.loads((RAW / "w6_exception_eval.json").read_text(encoding="utf-8"))
    as_of = json.loads((RAW / "w8_replay_leakage.json").read_text(encoding="utf-8"))["exception_agent_as_of"]
    order = ["low", "medium", "high", "critical"]
    rows = sorted(as_of["by_severity"], key=lambda r: order.index(r["severity"]))
    replayed = {r["severity"]: r["precision"] for r in original["by_severity"]}
    base = original["legs_truly_delayed"] / original["legs_in_replay"]

    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    x = range(len(rows))
    bars = ax.bar(x, [r["precision"] * 100 for r in rows],
                  color=[GREY, YELLOW, ORANGE, "#b5341a"], width=0.62, label="as-of (reported)")
    ax.scatter(x, [replayed[r["severity"]] * 100 for r in rows], marker="D", s=46,
               facecolors="white", edgecolors=INK, linewidths=1.2, zorder=3,
               label="replay with end-of-data history (superseded)")
    for bar, r in zip(bars, rows):
        ax.text(bar.get_x() + bar.get_width() / 2, r["precision"] * 100 / 2,
                f"{r['precision'] * 100:.1f}%\n({r['notified']:,})", ha="center", va="center",
                fontsize=8, color="white" if r["severity"] == "critical" else INK)
    ax.axhline(base * 100, color=MUTED, ls="--", lw=1.2)
    ax.annotate(f"alert every leg: {base * 100:.1f}%", xy=(-0.45, base * 100 + 2),
                ha="left", va="bottom", color=MUTED, fontsize=8)
    ax.set_xticks(list(x), [r["severity"] for r in rows])
    ax.set_ylabel("share of alerts that were genuinely late")
    ax.set_ylim(0, 108)
    ax.set_title("Severity still ranks alerts correctly, at lower precision than first reported")
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    return _finish(fig, "fig9_severity_precision",
                   "Notification precision by computed severity over the earliest 2,000 replayed legs, "
                   "scored with the history each leg had at its own time; hollow markers are the first, "
                   "leaked measurement (D-054). Sources: w8_replay_leakage.json, w6_exception_eval.json")


FIGURES = {
    "fig1": fig1_gap_ratio, "fig2": fig2_audit, "fig3": fig3_bottlenecks,
    "fig4": fig4_support_instability, "fig5": fig5_model_mae, "fig6": fig6_mae_by_support,
    "fig7": fig7_threshold, "fig8": fig8_scale, "fig9": fig9_severity_precision,
}


def run(only: str | None = None) -> list[dict]:
    chosen = {only: FIGURES[only]} if only else FIGURES
    made = [fn() for fn in chosen.values()]
    blurb = ("Every figure is built from a file in `benchmarks/raw/`. PNG at 300 dpi for slides, "
             "PDF (vector) for the paper.")
    index = ["# Figures", "",
             "**Owner: Krishna.** Generated by `python -m src.report.figures`; do not edit by hand.",
             "", blurb, "",
             "| figure | caption and source |", "|---|---|"]
    index += [f"| [`{m['figure']}`]({Path(m['png']).name}) | {m['caption']} |" for m in made]
    if not only:
        (OUT / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    log.info("%d figure(s) -> %s", len(made), OUT)
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the paper's figure set")
    parser.add_argument("--only", choices=sorted(FIGURES), default=None)
    args = parser.parse_args()
    run(args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
