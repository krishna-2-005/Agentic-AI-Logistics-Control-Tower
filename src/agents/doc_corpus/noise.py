"""Scan-artefact noise augmentation (execution plan W3 D3-D4).

**Why this does not use `pdf2image`.** `pdf2image` rasterises via `poppler`'s
`pdftoppm`, a system binary `pip install` does not provide — D-012 already spent an
afternoon on exactly this class of problem for Spark on Windows, and none of the three
machines this project runs on has poppler installed. Requiring it would make the
corpus's noisy half unreproducible on whichever machine did not happen to have it, so
this module draws the same fields (`templates.field_rows`) straight onto a raster
canvas with Pillow — already a `reportlab` dependency, already installed everywhere —
and degrades that. The clean PDF and the noisy scan are two independent renderers over
one shared field list, not a render-then-rasterise pipeline, which is also the reason
they cannot visually drift: there is no round trip to lose fidelity in. `pdf2image` /
`pytesseract` stay in `requirements.txt` for Week 4, when they will run against real
rasterised PDFs of an unknown source rather than one this project generated.

Degradations applied, each with a random draw so the corpus is not one noise level
repeated 100 times: small rotation (skew), Gaussian pixel noise, a light blur, a
brightness/contrast jitter, and a JPEG re-encode at a randomly low quality — the same
five artefacts a real phone-camera-scanned freight document actually accumulates.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from src.agents.doc_corpus.records import ConsignmentRecord
from src.agents.doc_corpus.templates import TITLES, field_rows

_PAGE_SIZE = (1240, 1754)  # ~A4 at 150 DPI
_MARGIN = 70


def _font(size: int) -> ImageFont.ImageFont:
    # Pillow's built-in bitmap font, sized — no .ttf shipped or assumed installed, so
    # this renders identically on all three teammates' machines regardless of what
    # system fonts they have (the same reproducibility instinct as D-012).
    return ImageFont.load_default(size=size)


def _draw_clean_page(rec: ConsignmentRecord, label: dict, doc_type: str) -> Image.Image:
    img = Image.new("L", _PAGE_SIZE, color=255)
    draw = ImageDraw.Draw(img)
    y = _MARGIN
    draw.text((_MARGIN, y), TITLES[doc_type], font=_font(30), fill=0)
    y += 46
    draw.line((_MARGIN, y, _PAGE_SIZE[0] - _MARGIN, y), fill=0, width=2)
    y += 30

    for row_label, value in field_rows(rec, label, doc_type):
        draw.text((_MARGIN, y), f"{row_label}:", font=_font(18), fill=0)
        draw.text((_MARGIN + 260, y), str(value), font=_font(18), fill=0)
        y += 34

    draw.text(
        (_MARGIN, _PAGE_SIZE[1] - 40),
        # Pillow's built-in bitmap font has no em-dash glyph (renders as a box) -
        # a plain hyphen instead, unlike the reportlab PDF footer which can use one.
        "Synthetic document - Agentic AI Logistics Control Tower, Week 3 corpus.",
        font=_font(13), fill=90,
    )
    return img


def _degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    angle = rng.uniform(-2.5, 2.5)
    img = img.rotate(angle, expand=False, fillcolor=255)

    arr = np.asarray(img).astype(np.float32)
    noise_sigma = rng.uniform(4, 14)
    arr += np.random.default_rng(rng.randint(0, 2**31 - 1)).normal(0, noise_sigma, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if rng.random() < 0.7:
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 1.1)))

    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 1.15))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.85, 1.1))
    return img


def render_scan_image(
    rec: ConsignmentRecord, label: dict, doc_type: str, path: Path, seed: int
) -> None:
    """Write a degraded, scan-like JPEG for `path`. Deterministic in `seed`."""
    rng = random.Random(seed)
    img = _draw_clean_page(rec, label, doc_type)
    img = _degrade(img, rng)

    # JPEG re-encode at a random low-ish quality — the fifth artefact, applied last so
    # it compresses the noise/blur too, the way a real re-saved scan would.
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=rng.randint(35, 70))
    path.write_bytes(buf.getvalue())
