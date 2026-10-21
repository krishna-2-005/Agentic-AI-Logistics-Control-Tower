"""Agent-layer figures (B7/B8), drawn from files under benchmarks/raw/ only.

    python -m src.report.figures_agents
"""

from __future__ import annotations

import json

import matplotlib.pyplot as plt

from src.common import config
from src.report.style import (
    BLUE,
    FULL_WIDTH_IN,
    INK,
    MUTED,
    ORANGE,
    apply_style,
    save,
)

SEVERITIES = ("low", "medium", "high", "critical")


def fig_b8_severity_ci() -> list:
    """Fig. 9 redone: precision by severity with Wilson 95% whiskers, as-of vs superseded replay."""
    apply_style()
    stats = json.loads((config.BENCHMARKS_RAW_DIR / "b8_exception_stats.json").read_text(encoding="utf-8"))
    as_of = {r["severity"]: r for r in stats["as_of"]["by_severity"]["rows"]}
    old = {r["severity"]: r for r in stats["superseded_replay_snapshot"]["by_severity"]["rows"]}
    trivial = stats["as_of"]["overall"]["trivial_policy_precision"]["rate"] * 100

    fig, ax = plt.subplots(figsize=(FULL_WIDTH_IN * 0.62, 3.0))
    ax.axhline(trivial, color=MUTED, linestyle="--", linewidth=1)
    ax.text(3.45, trivial - 3.2, f"alert every leg: {trivial:.1f}%", ha="right", fontsize=8, color=MUTED)
    for offset, data, colour, marker, label in (
        (-0.1, as_of, BLUE, "o", "as-of history (reported)"),
        (0.1, old, ORANGE, "D", "end-of-data history (superseded)"),
    ):
        xs = [i + offset for i in range(4)]
        ys = [data[s]["rate"] * 100 for s in SEVERITIES]
        lo = [y - data[s]["ci_low"] * 100 for y, s in zip(ys, SEVERITIES, strict=True)]
        hi = [data[s]["ci_high"] * 100 - y for y, s in zip(ys, SEVERITIES, strict=True)]
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt=marker, color=colour, capsize=3, markersize=5, label=label)
    for i, s in enumerate(SEVERITIES):
        ax.text(i - 0.1, as_of[s]["ci_low"] * 100 - 4.5, f"n={as_of[s]['total']}", ha="center",
                fontsize=7, color=INK)
    ax.set_xticks(range(4), SEVERITIES)
    ax.set_ylim(20, 100)
    ax.set_ylabel("notification precision (%)")
    ax.set_xlabel("computed severity")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.grid(axis="y")
    return save(fig, "fig_b8_severity_ci")


def main() -> int:
    for path in fig_b8_severity_ci():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
