"""
Invoice Auditor evaluation at scale (WP-02): 150 invoices, 15 per error kind.

    python -m src.ml.invoice_eval_scale            # 150 cases, zero API calls

The Week 6 number is "20 of 20 verdicts matched". Ten error kinds were sampled
by a weighted draw into those twenty cases, so some kinds appeared twice and one
appeared once -- and a per-kind claim resting on one case is not a claim. The
addendum asks for at least twenty per category and an interval on every rate.

This set is **stratified**: exactly `--per-kind` invoices of each of the ten
kinds, so every per-kind number rests on the same evidence as every other. The
overall rate is then a weighted average of a design, not of an accident, which is
worth saying out loud -- it is *not* an estimate of how often a real invoice run
would be disputed, because a real run is overwhelmingly clean. It answers the
question the auditor is actually built for: given a problem of this kind, does it
catch it, and does it name the right reason.

Two of the ten kinds expect `approve`
-------------------------------------
`rounding_total` and `other_at_edge` are invoices that look wrong and are not:
a total off by four-tenths of a paisa, and other-charges sitting exactly on the
allowed share. An auditor that disputes everything scores 100% on the eight
dispute kinds and fails these two, which is why they are in the set and why the
trivial policies are reported beside the result.

`overcharge_hidden` is priced, not fixed
----------------------------------------
It is 10% over the corpus's own band top, inside the auditor's 15% tolerance, so
the auditor is *expected to miss it*. D-047 chose that tolerance deliberately;
this set puts a number on what the choice costs rather than leaving it as a
sentence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.invoice_eval import EXPECTED, build_eval_set, score
from src.ml.stats import wilson

log = get_logger("ml.invoice_eval_scale")

RESULT_JSON = config.BENCHMARKS_RAW_DIR / "w9_invoice_eval.json"
EVAL_SET_JSON = config.BENCHMARKS_RAW_DIR / "w9_invoice_eval_set.json"

#: Different from the Week 6 seed (2026), so the consignments underneath are
#: different invoices on different corridors.
SEED = 9022

#: Kinds the auditor is *expected* to miss, and why.
#
# Without this a reader sees `overcharge_hidden 0/15` and concludes the auditor
# is broken. It is doing exactly what D-047 decided: the band carries a 15%
# tolerance so that ordinary price variation is not disputed, and this kind sits
# at 10% over the band top, inside it. The 0 of 15 is the price of that decision,
# which is worth a number rather than a sentence.
EXPECTED_MISSES = {
    "overcharge_hidden": (
        "10% over the band top, inside the auditor's 15% tolerance (D-047). "
        "Missed by design; this is what the tolerance costs."
    ),
}


def stratified_kinds(per_kind: int) -> list[str]:
    """Exactly `per_kind` of each kind, interleaved rather than blocked.

    Interleaved because `duplicate_number` copies an invoice number from a case
    already built: in a blocked layout all fifteen duplicates would land in a row
    and copy each other, which tests one thing fifteen times.
    """
    kinds = list(EXPECTED)
    return [kind for _ in range(per_kind) for kind in kinds]


def summarise(frame, base: dict, per_kind: int) -> dict:
    """The Week 6 summary, plus an interval on everything that is a proportion."""
    n = len(frame)
    correct = int(frame["verdict_correct"].sum())

    positives = frame[frame["expected_verdict"] == "dispute"]
    negatives = frame[frame["expected_verdict"] == "approve"]
    disputed = frame[frame["verdict"] == "dispute"]
    true_positives = int((disputed["expected_verdict"] == "dispute").sum())

    by_kind = {}
    for kind, group in frame.groupby("kind"):
        found = group["found_expected"].dropna()
        by_kind[str(kind)] = {
            "expected_verdict": group["expected_verdict"].iloc[0],
            "verdict": wilson(int(group["verdict_correct"].sum()), len(group)).as_dict(),
            "right_reason": wilson(int(found.sum()), len(found)).as_dict()
            if len(found)
            else None,
        }

    return {
        "n_cases": n,
        "per_kind": per_kind,
        "seed": SEED,
        "stratified": True,
        "accuracy": wilson(correct, n).as_dict(),
        "dispute_precision": wilson(true_positives, len(disputed)).as_dict()
        if len(disputed)
        else None,
        "dispute_recall": wilson(true_positives, len(positives)).as_dict(),
        "right_reason": wilson(
            int(frame["found_expected"].dropna().sum()),
            int(frame["found_expected"].notna().sum()),
        ).as_dict(),
        "false_disputes": int(
            ((frame["verdict"] == "dispute") & (frame["expected_verdict"] == "approve")).sum()
        ),
        "missed_problems": int(
            ((frame["verdict"] == "approve") & (frame["expected_verdict"] == "dispute")).sum()
        ),
        "unbenchmarked_corridors": int((~frame["benchmarked"]).sum()),
        "by_kind": by_kind,
        "expected_misses": EXPECTED_MISSES,
        "missed_by_design": int(
            sum(
                1
                for _, row in frame.iterrows()
                if row["kind"] in EXPECTED_MISSES and not row["verdict_correct"]
            )
        ),
        # Both trivial policies, because each looks good on half the set.
        "trivial_policy_dispute_everything": wilson(len(positives), n).as_dict(),
        "trivial_policy_approve_everything": wilson(len(negatives), n).as_dict(),
        "note": (
            "Stratified: equal cases per kind, so the overall rate reflects the "
            "design of this set and not the mix of a real invoice run, which is "
            "overwhelmingly clean. Per-kind rates are the comparable numbers."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week6_for_comparison": {
            "cases": base.get("cases"),
            "accuracy": base.get("accuracy"),
            "note": "20 cases, kinds drawn at random; some kinds appeared once.",
        },
    }


def render_markdown(s: dict) -> str:
    a = s["accuracy"]
    lines = [
        f"### Invoice Auditor — {s['n_cases']} invoices, {s['per_kind']} per kind",
        "",
        f"- Verdict correct **{a['rate']:.1%}** [{a['ci_low']:.1%}–{a['ci_high']:.1%}] "
        f"({a['successes']}/{a['total']})",
        f"- Dispute recall **{s['dispute_recall']['rate']:.1%}**, "
        f"precision **{s['dispute_precision']['rate']:.1%}**"
        if s["dispute_precision"]
        else "",
        f"- Right reason on a dispute **{s['right_reason']['rate']:.1%}**",
        f"- Correct invoices wrongly disputed: **{s['false_disputes']}**",
        f"- Problems missed: **{s['missed_problems']}**, of which "
        f"**{s['missed_by_design']}** are the tolerance working as decided "
        f"(see below) rather than a failure",
        "",
        f"Trivial policies on the same set: dispute everything "
        f"{s['trivial_policy_dispute_everything']['rate']:.1%}, approve everything "
        f"{s['trivial_policy_approve_everything']['rate']:.1%}.",
        "",
        "| kind | expects | verdict correct | 95% interval | right reason |",
        "|---|---|---|---|---|",
    ]
    expected_misses = s.get("expected_misses", {})
    for kind, row in sorted(s["by_kind"].items()):
        v = row["verdict"]
        rr = row["right_reason"]
        rr_txt = f"{rr['rate']:.0%}" if rr else "—"
        flag = " *(missed by design)*" if kind in expected_misses else ""
        lines.append(
            f"| `{kind}`{flag} | {row['expected_verdict']} | "
            f"{v['successes']}/{v['total']} | "
            f"{v['ci_low']:.0%}–{v['ci_high']:.0%} | {rr_txt} |"
        )
    for kind, why in expected_misses.items():
        lines += ["", f"**`{kind}`** — {why}"]
    return "\n".join(ln for ln in lines if ln != "")


def run(per_kind: int = 15) -> dict:
    kinds = stratified_kinds(per_kind)
    cases = build_eval_set(count=len(kinds), seed=SEED, kinds=kinds)
    frame, base = score(cases)
    summary = summarise(frame, base, per_kind)
    summary["cases"] = frame.to_dict(orient="records")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-kind", type=int, default=15, help="invoices of each kind")
    ap.add_argument("--out", type=Path, default=RESULT_JSON)
    args = ap.parse_args()

    config.ensure_dirs()
    summary = run(args.per_kind)

    EVAL_SET_JSON.write_text(
        json.dumps(summary["cases"], indent=2, default=str), encoding="utf-8"
    )
    args.out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log.info("%d invoices scored -> %s", summary["n_cases"], args.out)
    print()
    print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
