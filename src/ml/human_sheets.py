"""Blank sheets for the human-only labelling tasks (B7). Nothing here invents a label.

    python -m src.ml.human_sheets --build
    python -m src.ml.human_sheets --agreement a.csv b.csv     # after two people filled them

Writes, under `docs/human_tasks/`:

* `second_labeller_groundedness_sheet.csv`: the 30 saved assistant answers with the context
  each was given, `verdict` and `reason` blank. The first labeller's verdicts are not on it,
  so the second judgement is independent. Cohen's kappa is computed by
  `python -m src.ml.groundedness --agreement <sheet>`.
* `order_email_labelling_sheet.csv`: 150 emails sampled with a fixed seed from the two order
  corpora (100 from the 200-email set, 50 from the hard set), `label` blank. Two people each
  fill their own copy; `--agreement` computes Cohen's kappa between them and each person's
  agreement with the generator's intended label. The intended label is not on the sheet.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from src.common import config
from src.ml.groundedness import ANSWERS, cohen_kappa

HUMAN_DIR = config.DOCS_DIR / "human_tasks"
GROUND_SHEET = HUMAN_DIR / "second_labeller_groundedness_sheet.csv"
ORDER_SHEET = HUMAN_DIR / "order_email_labelling_sheet.csv"
SHEET_SEED = 8604
N_FROM_SCALE, N_FROM_HARD = 100, 50
LABELS = ("ask", "infer", "refuse")
#: the generator's intended action mapped onto the sheet's labels
INTENDED = {"file": "infer", "clarify": "ask"}


def order_email_pool() -> list[dict]:
    """The 150 sampled emails with their intended label (kept off the blank sheet)."""
    from src.ml.b7_hard_sets import build_order_hard
    from src.ml.order_eval_scale import build_cases

    rng = random.Random(SHEET_SEED)
    scale = rng.sample(build_cases(), N_FROM_SCALE)
    hard = rng.sample(build_order_hard(), N_FROM_HARD)
    pool = [{"source": "w9_order_eval_set", "subject": c.subject, "body": c.body,
             "intended": INTENDED[c.expected_action], "seq": c.seq} for c in scale]
    pool += [{"source": "b7_order_hard_set", "subject": c.subject, "body": c.body,
              "intended": INTENDED[c.expected_action], "seq": c.seq} for c in hard]
    rng.shuffle(pool)
    for i, item in enumerate(pool, 1):
        item["email_id"] = f"E{i:03d}"
    return pool


def build_order_sheet(path: Path = ORDER_SHEET) -> int:
    pool = order_email_pool()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["email_id", "subject", "body", "label", "field_if_ask", "note"])
        for item in pool:
            writer.writerow([item["email_id"], item["subject"], item["body"], "", "", ""])
    return len(pool)


def build_groundedness_sheet(path: Path = GROUND_SHEET) -> int:
    from src.agents.analytics_assistant import answer as ask

    rows = [json.loads(line) for line in ANSWERS.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "question", "context_given_to_the_assistant", "assistant_answer", "verdict", "reason"])
        for row in rows:
            context = ask(row["question"], use_llm=False).context
            writer.writerow([row["id"], row["question"], context, row["answer"], "", ""])
    return len(rows)


def order_agreement(sheet_a: str, sheet_b: str) -> dict:
    """Kappa between two labellers, and each against the generator's intended label."""

    def read(path: str) -> dict[str, str]:
        with open(path, newline="", encoding="utf-8") as fh:
            return {r["email_id"]: r["label"].strip().lower() for r in csv.DictReader(fh)}

    a, b = read(sheet_a), read(sheet_b)
    ids = sorted(a)
    if set(ids) != set(b) or any(not a[i] or not b[i] for i in ids):
        raise ValueError("both sheets must cover the same emails with every label filled")
    bad = {x for x in list(a.values()) + list(b.values()) if x not in LABELS}
    if bad:
        raise ValueError(f"labels must be one of {LABELS}; found {sorted(bad)}")
    intended = {p["email_id"]: p["intended"] for p in order_email_pool()}
    return {
        "labeller_a_vs_b": cohen_kappa([a[i] for i in ids], [b[i] for i in ids]),
        "labeller_a_vs_intended": cohen_kappa([a[i] for i in ids], [intended[i] for i in ids]),
        "labeller_b_vs_intended": cohen_kappa([b[i] for i in ids], [intended[i] for i in ids]),
        "note": "the intended label comes from the generators, not from a person",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--agreement", nargs=2, metavar=("SHEET_A", "SHEET_B"))
    args = ap.parse_args()
    if args.build:
        print("order emails:", build_order_sheet(), "| groundedness answers:", build_groundedness_sheet())
    if args.agreement:
        result = order_agreement(*args.agreement)
        out = config.BENCHMARKS_RAW_DIR / "b7_order_label_agreement.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
