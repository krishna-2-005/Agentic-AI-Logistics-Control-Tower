"""One figure style for the whole paper, the site's evidence figures and the appendix.

Every module that draws a figure imports this one rather than setting its own fonts and
colours, so the figures read as one set (UPGRADE_PLAN C5). The palette is the one
`src.report.figures` validated before it was adopted: the lightness band, chroma floor and
colour-vision separation checks pass, two of the four fall under 3:1 against white, and so
every mark is directly labelled and no figure depends on colour alone to be read.

    from src.report.style import BLUE, ORANGE, AQUA, YELLOW, apply_style, save

    apply_style()
    fig, ax = plt.subplots(figsize=(COL_WIDTH_IN, 2.4))
    ...
    save(fig, "b2_forest_plot")         # writes <out_dir>/<name>.pdf and .png

Sizes are given in inches for the two page layouts the manuscripts use: a single column
(IEEE and LNCS both ~3.5 in) and a full text width (~7 in).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # imported after the Agg backend selection above

from src.common import config

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GREY, INK, MUTED = "#c9c9c4", "#0b0b0b", "#52514e"

#: Identity colours: a corridor confirmed slower is orange and faster is aqua in every
#: figure, whatever the filter or order (the rule `src.report.figures` set).
SLOWER, FASTER, NEUTRAL = ORANGE, AQUA, GREY

COL_WIDTH_IN = 3.5
FULL_WIDTH_IN = 7.0

#: Where figure files go. The paper's `paper/figures/` is a copy of this directory made
#: by `scripts/build_paper.sh`, so figures are only ever written here, by code.
FIGURES_DIR = config.DOCS_DIR / "figures"


def apply_style() -> None:
    """Set the shared rcParams. Idempotent; call it at the top of every figure function."""
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
        # TrueType, not Type 3: journal and conference checkers reject Type 3 fonts.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def save(fig, name: str, out_dir: Path | None = None) -> list[Path]:
    """Write `name`.pdf (vector, for the paper) and `name`.png (300 dpi, for slides)."""
    out_dir = out_dir or FIGURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("pdf", "png"):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path)
        paths.append(path)
    plt.close(fig)
    return paths


apply_style()
