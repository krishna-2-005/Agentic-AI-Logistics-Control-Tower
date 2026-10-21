"""Figures for the dependence-aware audit, the empirical-Bayes ranking and the stability study.

    python -m src.report.figures_audit            # all four
    python -m src.report.figures_audit --only b4_eb_shrinkage

Each figure reads only files in `benchmarks/raw/` (B3, B4, B5) and writes a vector PDF and a
300 dpi PNG to `docs/figures/` through `src.report.style`. Orange is slower and aqua is
faster, as in the audit figure; every mark is also told apart by shape or fill, so the figures
read in greyscale.
"""

from __future__ import annotations

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.common import config
from src.report import style
from src.report.style import AQUA, BLUE, FULL_WIDTH_IN, GREY, INK, MUTED, ORANGE

RAW = config.BENCHMARKS_RAW_DIR
FLOORS = (5, 10, 20, 30)


def _json(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def b4_eb_shrinkage() -> list:
    """Raw against shrunk corridor effects, and how little each corridor moved."""
    style.apply_style()
    res = _json("b4_eb_ranking.json")
    tab = pd.read_csv(RAW / "b4_eb_corridors.csv")
    thr = res["threshold_log"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.0), gridspec_kw={"width_ratios": [1.5, 1]})

    a.vlines(tab["n_legs"], tab["raw_mean_log"], tab["eb_post_mean"], color=GREY, lw=0.6, zorder=1)
    a.scatter(tab["n_legs"], tab["raw_mean_log"], s=11, facecolors="none", edgecolors=MUTED, lw=0.6,
              label="raw mean", zorder=2)
    a.scatter(tab["n_legs"], tab["eb_post_mean"], s=5, color=BLUE, label="shrunk (empirical Bayes)", zorder=3)
    a.axhline(thr, color=ORANGE, lw=1.2, ls="--")
    a.text(tab["n_legs"].max(), 3.7, "dashed: material threshold, 1.5 x the network overrun", ha="right",
           va="top", fontsize=7.5, color=INK)
    a.set_ylim(top=3.75)
    a.set_xscale("log")
    a.set_xlabel("legs on the corridor (log scale)")
    a.set_ylabel("mean log(actual / planned time)")
    a.set_title("Raw and shrunk corridor effects", loc="left")
    a.legend(frameon=False, loc="lower right", fontsize=7.5)
    a.grid(True, which="major")
    a.set_axisbelow(True)

    b.scatter(tab["n_legs"], 100 * tab["eb_shrink_factor"], s=6, color=BLUE)
    b.set_xscale("log")
    b.set_yscale("log")
    b.set_xlabel("legs on the corridor (log scale)")
    b.set_ylabel("pull toward the network mean (%)")
    b.set_title("Shrinkage: median about 1%", loc="left")
    b.grid(True, which="major")
    b.set_axisbelow(True)
    fig.tight_layout()
    return style.save(fig, "b4_eb_shrinkage")


def b4_eb_stability_heatmap() -> list:
    """Top-20 overlap between support floors, published ranking beside the shrunk one."""
    style.apply_style()
    res = _json("b4_eb_ranking.json")
    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.3), layout="constrained")
    panels = (("raw_published", "Raw ranking (published rule)"), ("eb_prob", "Shrunk ranking (P above threshold)"))
    im = None
    for ax, (key, title) in zip(axes, panels, strict=True):
        m = np.eye(len(FLOORS))
        for row in res["pair_stability"][key]:
            fa, fb = (int(x) for x in row["floors"].split("|"))
            i, j = FLOORS.index(fa), FLOORS.index(fb)
            m[i, j] = m[j, i] = row["jaccard_top20"]
        im = ax.imshow(m, vmin=0, vmax=1, cmap="Blues")
        for i in range(len(FLOORS)):
            for j in range(len(FLOORS)):
                ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center", fontsize=9,
                        color="white" if m[i, j] > 0.55 else INK)
        ax.set_xticks(range(len(FLOORS)), [str(f) for f in FLOORS])
        ax.set_yticks(range(len(FLOORS)), [str(f) for f in FLOORS])
        ax.set_xlabel("minimum legs per corridor")
        ax.set_ylabel("minimum legs per corridor")
        mean = res["summary"][key]["mean_pairwise_jaccard_top20"]
        ax.set_title(f"{title}\nmean off-diagonal overlap {mean:.2f}", loc="left", fontsize=9)
        for s in ax.spines.values():
            s.set_visible(False)
    fig.colorbar(im, ax=list(axes), shrink=0.8, pad=0.03, label="share of the top 20 in common (Jaccard)")
    return style.save(fig, "b4_eb_stability_heatmap")


def b5_stability_scatter() -> list:
    """Each corridor's effect in the first half of the window against the second half."""
    style.apply_style()
    res = _json("b5_stability.json")
    h = res["settings"]["proportional"]["halves"]["pairs"]["H1->H2"]
    tab = pd.read_csv(RAW / "b5_stability_corridors.csv")
    fig, axes = plt.subplots(1, 2, figsize=(FULL_WIDTH_IN, 3.3), sharex=True, sharey=True)
    specs = (
        ("mean_log", "Raw mean", h["spearman_raw_mean"]["rho"]),
        ("eb_mean", "Shrunk (empirical Bayes)", h["spearman_eb_posterior_mean"]["rho"]),
    )
    flag = tab["sig_bh_welch_slower_h1"]
    for ax, (col, title, rho) in zip(axes, specs, strict=True):
        x, y = tab[f"{col}_h1"], tab[f"{col}_h2"]
        ax.scatter(x[~flag], y[~flag], s=7, color=GREY, label="not flagged slower in the first half")
        ax.scatter(x[flag], y[flag], s=11, color=ORANGE, marker="^", edgecolors=INK, linewidths=0.3,
                   label="flagged slower in the first half")
        lim = [-0.5, 3.7]
        ax.plot(lim, lim, color=MUTED, lw=1, ls="--")
        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_title(f"{title}: Spearman {rho:.2f}", loc="left", fontsize=9)
        ax.set_xlabel("mean log(actual / planned), first half")
        ax.grid(True, which="major")
        ax.set_axisbelow(True)
    axes[0].set_ylabel("same, second half")
    axes[0].legend(frameon=False, loc="upper left", fontsize=7)
    fig.suptitle(f"{h['universe']} corridors with at least 5 legs in both halves", x=0.01, ha="left",
                 fontsize=8, color=MUTED)
    fig.tight_layout()
    return style.save(fig, "b5_stability_scatter")


def b3_audit_robust() -> list:
    """The 1,130-corridor audit, with which discoveries survive the cluster-aware test."""
    style.apply_style()
    res = _json("b3_audit_robust.json")
    tab = pd.read_csv(RAW / "b3_audit_robust_corridors.csv")
    worse, better = tab["direction"] == "worse", tab["direction"] == "better"
    robust = tab["status"] == "robust"
    fragile = tab["status"] == "fragile"
    none = tab["status"] == "not_significant"
    near = tab["p_perm"] < 0.05

    fig, ax = plt.subplots(figsize=(FULL_WIDTH_IN * 0.86, 3.9))
    ax.scatter(tab.loc[none, "n_legs"], tab.loc[none, "excess_ratio"], s=9, color=GREY,
               label=f"not significant ({int(none.sum())})")
    ax.scatter(tab.loc[fragile & better, "n_legs"], tab.loc[fragile & better, "excess_ratio"], s=14,
               marker="v", color=AQUA, alpha=0.75, label=f"faster, fragile ({int((fragile & better).sum())})")
    ax.scatter(tab.loc[fragile & worse, "n_legs"], tab.loc[fragile & worse, "excess_ratio"], s=14,
               marker="^", color=ORANGE, alpha=0.75, label=f"slower, fragile ({int((fragile & worse).sum())})")
    ax.scatter(tab.loc[near, "n_legs"], tab.loc[near, "excess_ratio"], s=42, facecolors="none",
               edgecolors=INK, linewidths=0.8, label=f"permutation p < 0.05, uncorrected ({int(near.sum())})")
    ax.scatter(tab.loc[robust, "n_legs"], tab.loc[robust, "excess_ratio"], s=40, color=INK, marker="D",
               label=f"robust ({int(robust.sum())})")
    ax.axhline(1.0, color=MUTED, lw=1, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("legs on the corridor (log scale)")
    ax.set_ylabel("corridor time over plan, relative to the network (log scale)")
    ax.set_title(
        f"Published audit: {res['published_slower']} slower, {res['published_faster']} faster; "
        f"{res['robust_slower'] + res['robust_faster']} survive the cluster-aware test",
        loc="left", fontsize=9)
    ax.legend(frameon=False, loc="upper right", fontsize=7.5)
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    return style.save(fig, "b3_audit_robust")


FIGURES = {
    "b4_eb_shrinkage": b4_eb_shrinkage,
    "b4_eb_stability_heatmap": b4_eb_stability_heatmap,
    "b5_stability_scatter": b5_stability_scatter,
    "b3_audit_robust": b3_audit_robust,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=sorted(FIGURES))
    args = ap.parse_args()
    for name, fn in FIGURES.items():
        if args.only and name != args.only:
            continue
        for p in fn():
            print(p)


if __name__ == "__main__":
    main()
