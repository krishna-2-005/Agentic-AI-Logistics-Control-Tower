"""Invoice Auditor evaluation (execution plan W6 D5).

    python -m src.ml.invoice_eval
    python -m src.ml.invoice_eval --count 60 --seed 2026

Scores Krishna's Freight Invoice Auditor on a seeded-error set **I wrote**, not the one
he developed against. Same builder/judge separation as D-028 and the Order Entry
evaluation: an auditor tuned on the very cases it is later scored on is not being
measured.

Where this set differs from his, on purpose
-------------------------------------------
His corpus has five kinds and all of them are comfortably outside the auditor's bands.
Mine has ten, and three of them sit deliberately **near the edges**, because an
evaluation that only asks easy questions returns a number that means nothing:

* ``other_at_edge`` -- other charges at exactly the 18% the network bills. Correct
  answer: approve. A checker that tests `>` where it means `>=` fails here and nowhere
  else.
* ``rounding_total`` -- a total off by four tenths of a paisa. Correct answer: approve.
  Disputing a supplier over a rounding error is how an audit desk loses its credibility.
* ``overcharge_hidden`` -- freight 10% above the corpus's own rate band, which is
  **inside** the auditor's 15% tolerance. Correct answer: dispute. The auditor will
  approve it, and it is in the set precisely so the tolerance's cost is a measured
  number rather than an assumption.

That last one is designed to fail. A seeded set whose every case the auditor passes
tells you the cases were easy, not that the auditor is good.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.agents.doc_corpus.records import generate_records
from src.agents.exception_agent import load_audit
from src.agents.invoice_auditor import (
    BAND_TOLERANCE,
    OTHER_CHARGES_SHARE,
    InvoiceCase,
    audit_invoice,
    corridor_km_lookup,
    freight_band,
    verdict_for,
)
from src.common import config, docs
from src.common.logging_setup import get_logger

log = get_logger("ml.invoice_eval")

OUT_JSON = config.BENCHMARKS_RAW_DIR / "w6_invoice_eval.json"
OUT_CSV = config.BENCHMARKS_RAW_DIR / "w6_invoice_eval_cases.csv"
EVAL_SET_JSON = config.BENCHMARKS_RAW_DIR / "w6_invoice_eval_set.json"
DOC_PATH = config.DOCS_DIR / "W6_lahari_agent_eval.md"

EVAL_SEED = 2026

#: kind -> (expected verdict, the finding a correct auditor should raise)
EXPECTED = {
    "clean": ("approve", None),
    "rounding_total": ("approve", None),
    "other_at_edge": ("approve", None),
    "total_mismatch": ("dispute", "total_mismatch"),
    "overcharge_gross": ("dispute", "rate_above_band"),
    "overcharge_hidden": ("dispute", "rate_above_band"),
    "undercharge": ("dispute", "rate_below_band"),
    "excessive_other": ("dispute", "other_charges_out_of_band"),
    "duplicate_number": ("dispute", "duplicate_invoice_number"),
    "foreign_currency": ("dispute", "unexpected_currency"),
}


@dataclass
class EvalCase:
    case: InvoiceCase
    kind: str
    expected_verdict: str
    expected_finding: str | None


def build_eval_set(count: int = 60, seed: int = EVAL_SEED) -> list[EvalCase]:
    """`count` invoices over my ten kinds, every kind represented."""
    records = generate_records(count, seed=seed)
    rng = random.Random(seed)
    kinds = list(EXPECTED)
    kinds += [rng.choice(list(EXPECTED)) for _ in range(max(0, count - len(kinds)))]
    rng.shuffle(kinds)
    if len(kinds) > 1 and kinds[0] == "duplicate_number":
        kinds[0], kinds[1] = kinds[1], kinds[0]

    cases: list[EvalCase] = []
    for record, kind in zip(records, kinds, strict=True):
        freight, other = record.freight_charge, record.other_charges
        number = f"LEV-{record.seq:06d}"
        currency = "INR"
        low, high = freight_band(record.route_type, record.weight_kg, record.mean_osrm_km)

        if kind == "total_mismatch":
            pass  # handled below, after the total is computed
        elif kind == "overcharge_gross":
            freight = round(high * 1.8, 2)
            other = round(freight * 0.12, 2)
        elif kind == "overcharge_hidden":
            # 10% over the corpus's own band top, which is inside the auditor's 15%
            # tolerance. The auditor should miss this; the point is to price the miss.
            freight = round((high / (1 + BAND_TOLERANCE)) * 1.10, 2)
            other = round(freight * 0.12, 2)
        elif kind == "undercharge":
            freight = round(low * 0.5, 2)
            other = round(freight * 0.12, 2)
        elif kind == "excessive_other":
            other = round(freight * 0.40, 2)
        elif kind == "other_at_edge":
            other = round(freight * OTHER_CHARGES_SHARE[1], 2)
        elif kind == "foreign_currency":
            currency = "USD"
        elif kind == "duplicate_number" and cases:
            number = rng.choice(cases).case.external_invoice_number

        total = round(freight + other, 2)
        if kind == "total_mismatch":
            total = round(total * 1.22, 2)
        elif kind == "rounding_total":
            total = round(total + 0.004, 3)

        expected_verdict, expected_finding = EXPECTED[kind]
        cases.append(EvalCase(
            case=InvoiceCase(
                seq=record.seq, kind=kind, corridor_id=record.corridor_id,
                route_type=record.route_type, weight_kg=record.weight_kg, pieces=record.pieces,
                external_invoice_number=number, freight_charge=freight, other_charges=other,
                total_amount=total, currency=currency,
            ),
            kind=kind, expected_verdict=expected_verdict, expected_finding=expected_finding,
        ))
    return cases


def score(cases: list[EvalCase]) -> tuple[pd.DataFrame, dict]:
    km = corridor_km_lookup(load_audit())
    seen: set[str] = set()
    rows = []
    for entry in cases:
        findings = audit_invoice(entry.case, km.get(entry.case.corridor_id), seen)
        seen.add(entry.case.external_invoice_number)
        verdict = verdict_for(findings)
        codes = [f.code for f in findings]
        rows.append({
            "seq": entry.case.seq,
            "kind": entry.kind,
            "expected_verdict": entry.expected_verdict,
            "verdict": verdict,
            "verdict_correct": verdict == entry.expected_verdict,
            "expected_finding": entry.expected_finding,
            "findings": ",".join(codes),
            "found_expected": entry.expected_finding in codes if entry.expected_finding else None,
            "benchmarked": entry.case.corridor_id in km,
        })
    frame = pd.DataFrame(rows)

    positives = frame[frame["expected_verdict"] == "dispute"]
    disputed = frame[frame["verdict"] == "dispute"]
    true_positives = int((disputed["expected_verdict"] == "dispute").sum())
    summary = {
        "cases": len(frame),
        "accuracy": round(float(frame["verdict_correct"].mean()), 4),
        "precision": round(true_positives / len(disputed), 4) if len(disputed) else None,
        "recall": round(true_positives / len(positives), 4) if len(positives) else None,
        "false_disputes": int(((frame["verdict"] == "dispute") & (frame["expected_verdict"] == "approve")).sum()),
        "missed_problems": int(((frame["verdict"] == "approve") & (frame["expected_verdict"] == "dispute")).sum()),
        "right_reason": round(float(frame["found_expected"].dropna().mean()), 4)
        if frame["found_expected"].notna().any() else None,
        "unbenchmarked_corridors": int((~frame["benchmarked"]).sum()),
        "by_kind": [
            {
                "kind": kind,
                "n": len(group),
                "correct": int(group["verdict_correct"].sum()),
                "expected": group["expected_verdict"].iloc[0],
            }
            for kind, group in frame.groupby("kind")
        ],
        "seed": EVAL_SEED,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return frame, summary


def render_doc(frame: pd.DataFrame, summary: dict) -> str:
    lines = [
        "## Invoice Auditor evaluation (D5)",
        "",
        (
            "*Generated by `python -m src.ml.invoice_eval` -- regenerate rather than editing "
            "numbers by hand.*"
        ),
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        (
            f"{summary['cases']} invoices over ten seeded kinds, on a set the auditor's author "
            "never saw (D-028). Three kinds sit deliberately near the auditor's edges, and one of "
            "them is designed to be missed."
        ),
        "",
        "| | |",
        "|---|---|",
        f"| **Verdict accuracy** | **{summary['accuracy']:.1%}** |",
        f"| Precision (of disputes raised) | {summary['precision']:.1%} |",
        f"| Recall (of problems present) | {summary['recall']:.1%} |",
        f"| **False disputes** (clean invoice disputed) | **{summary['false_disputes']}** |",
        f"| Missed problems | {summary['missed_problems']} |",
        f"| Disputes raised for the right reason | {summary['right_reason']:.1%} |",
        "",
        "### By seeded kind",
        "",
        "| kind | expected | n | correct |",
        "|---|---|---|---|",
    ]
    for entry in summary["by_kind"]:
        lines.append(f"| `{entry['kind']}` | {entry['expected']} | {entry['n']} | "
                     f"{entry['correct']}/{entry['n']} |")
    lines += [
        "",
        (
            "Per-invoice verdicts: `benchmarks/raw/w6_invoice_eval_cases.csv`; the set itself: "
            "`w6_invoice_eval_set.json`."
        ),
    ]
    return "\n".join(lines)


def run(count: int = 60, seed: int = EVAL_SEED, out_md: Path = DOC_PATH) -> dict:
    cases = build_eval_set(count, seed)
    EVAL_SET_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVAL_SET_JSON.write_text(
        json.dumps([{**asdict(c.case), "expected_verdict": c.expected_verdict,
                     "expected_finding": c.expected_finding} for c in cases], indent=2),
        encoding="utf-8",
    )
    frame, summary = score(cases)
    frame.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    docs.write_section(out_md, "invoice-eval", render_doc(frame, summary))
    log.info(
        "%d invoice(s): accuracy %.1f%%, %d false dispute(s), %d missed",
        summary["cases"], 100 * summary["accuracy"], summary["false_disputes"],
        summary["missed_problems"],
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Invoice Auditor on an authored set")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=EVAL_SEED)
    parser.add_argument("--out-md", type=Path, default=DOC_PATH)
    args = parser.parse_args()
    run(count=args.count, seed=args.seed, out_md=args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
