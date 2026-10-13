"""
The WP-02 section of `benchmarks/agent_evaluation.md`.

    python -m src.ml.agent_eval_report

Writes one delimited section (`src.common.docs`) rather than regenerating the
file. The rest of `agent_evaluation.md` is Lahari's, written by hand, and it is
the better half of the document -- the prose under "What the numbers do and do
not show" is where the reading happens. Overwriting that to insert three tables
would trade the interpretation for the data.

What this section adds is the thing the addendum asked for: every agent at
n >= 150 with an interval on every rate, and a stratum for the cases that are
meant to be hard. The Week 5 and Week 6 numbers above it stay as they are; they
were true of the sets they ran on, and those sets were too small and too easy to
separate a good agent from a lucky one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common import config
from src.common.docs import write_section
from src.common.logging_setup import get_logger

log = get_logger("ml.agent_eval_report")

DOC_PATH = config.BENCHMARKS_DIR / "agent_evaluation.md"
SECTION_ID = "agent-eval-at-scale"

ORDER_JSON = config.BENCHMARKS_RAW_DIR / "w9_order_eval.json"
INVOICE_JSON = config.BENCHMARKS_RAW_DIR / "w9_invoice_eval.json"
LIFECYCLE_JSON = config.BENCHMARKS_RAW_DIR / "w9_lifecycle_eval.json"


def _ci(d: dict) -> str:
    return f"**{d['rate']:.1%}** [{d['ci_low']:.1%}–{d['ci_high']:.1%}] ({d['successes']}/{d['total']})"


def build() -> str:
    order = json.loads(ORDER_JSON.read_text(encoding="utf-8"))
    invoice = json.loads(INVOICE_JSON.read_text(encoding="utf-8"))
    lifecycle = json.loads(LIFECYCLE_JSON.read_text(encoding="utf-8"))

    held = order["held_out_first_run"]
    lines: list[str] = []
    add = lines.append

    add("## At scale, with intervals (WP-02)")
    add("")
    add(
        "Every number above rests on 20 to 50 cases. A perfect score on twenty is "
        "consistent with a true rate of 84%; on two hundred it is not. These runs "
        "are larger, stratified so the hard cases are a named share rather than "
        "whatever the sampler happened to draw, and every rate carries a Wilson "
        "95% interval. All three cost **zero API calls**."
    )
    add("")

    # ── order entry ──────────────────────────────────────────────────────────
    o, a, e = order["overall"], order["adversarial"], order["straightforward"]
    add("### Order Entry — 200 emails, 100 of them adversarial")
    add("")
    add("| | rate | 95% interval |")
    add("|---|---|---|")
    add(f"| **Held out** (first run, before any fix) | {held['overall']['rate']:.1%} | "
        f"{held['overall']['ci_low']:.1%}–{held['overall']['ci_high']:.1%} |")
    add(f"| — adversarial half | {held['adversarial']['rate']:.1%} | "
        f"{held['adversarial']['ci_low']:.1%}–{held['adversarial']['ci_high']:.1%} |")
    add(f"| After fixing what it found | {o['rate']:.1%} | {o['ci_low']:.1%}–{o['ci_high']:.1%} |")
    add(f"| — straightforward half | {e['rate']:.1%} | {e['ci_low']:.1%}–{e['ci_high']:.1%} |")
    add(f"| — adversarial half | {a['rate']:.1%} | {a['ci_low']:.1%}–{a['ci_high']:.1%} |")
    add("")
    add(
        f"**The {held['overall']['rate']:.1%} is the number with evidential weight.** "
        "The rule route was committed before a line of this corpus existed, so its "
        "first score here was a genuine held-out measurement. "
        f"{held['orders_filed_on_invented_values']} orders were filed on values the "
        "email never stated, and three templates scored zero: "
        f"{', '.join('`' + t + '`' for t in held['templates_at_zero'])}. All three "
        "failed the same way — filing confidently on something unestablished."
    )
    add("")
    add(
        f"The {o['rate']:.1%} below it is after those three were fixed, and is **not** "
        "held out: a score on the set that motivated a fix cannot also be independent "
        "confirmation of it. Both are reported because the arc is the finding. For the "
        "next honest measurement this set is spent."
    )
    add("")
    add(
        "The model route is **not scored here**. 200 cases is 200 calls against a free "
        "tier of 20 a day, so the rules-versus-model comparison is WP-07 work. What can "
        "be said already: on the Week 5 set of 50, the rule route and the model route "
        "both score 50 of 50, so that set does not separate them."
    )
    add("")

    # ── invoice ──────────────────────────────────────────────────────────────
    inv_a = invoice["accuracy"]
    add(f"### Invoice Auditor — {invoice['n_cases']} invoices, {invoice['per_kind']} of each kind")
    add("")
    add(f"- Verdict correct {_ci(inv_a)}")
    add(f"- Dispute recall {_ci(invoice['dispute_recall'])}")
    add(f"- Right reason on a dispute {_ci(invoice['right_reason'])}")
    add(f"- Correct invoices wrongly disputed: **{invoice['false_disputes']}**")
    add(
        f"- Problems missed: **{invoice['missed_problems']}**, all "
        f"`overcharge_hidden`, all missed by design"
    )
    add("")
    add("| kind | expects | correct | 95% interval |")
    add("|---|---|---|---|")
    for kind, row in sorted(invoice["by_kind"].items()):
        v = row["verdict"]
        flag = " *(by design)*" if kind in invoice.get("expected_misses", {}) else ""
        add(
            f"| `{kind}`{flag} | {row['expected_verdict']} | {v['successes']}/{v['total']} | "
            f"{v['ci_low']:.0%}–{v['ci_high']:.0%} |"
        )
    add("")
    add(
        "Stratified, so the overall rate describes this design and not a real invoice "
        "run, which is overwhelmingly clean. The per-kind rates are the comparable "
        "numbers. Trivial policies on the same set: dispute everything "
        f"{invoice['trivial_policy_dispute_everything']['rate']:.1%}, approve everything "
        f"{invoice['trivial_policy_approve_everything']['rate']:.1%}."
    )
    add("")
    add(
        "**`overcharge_hidden` is 0 of 20 on purpose.** It sits 10% over the band top, "
        "inside the auditor's 15% tolerance (D-047). The tolerance was a sentence; this "
        "is what it costs — a supplier overcharging by that much passes every time."
    )
    add("")

    # ── lifecycle ────────────────────────────────────────────────────────────
    cov = lifecycle["path_coverage"]
    add(f"### Orchestrator — {lifecycle['n_cases']} lifecycles, with path coverage")
    add("")
    add(f"- Graph paths exercised **{cov['exercised']} of {cov['possible']}**")
    add(f"- Routed as the email deserved {_ci(lifecycle['routing_correct'])}")
    add(f"- Completed without error {_ci(lifecycle['completed_without_error'])}")
    add("")
    add("| path | times taken |")
    add("|---|---|")
    for path, n in sorted(cov["distribution"].items(), key=lambda kv: -kv[1]):
        add(f"| `{path}` | {n} |")
    add("")
    add(
        "**This replaces the wiring caveat above.** Week 6's ten lifecycles ran in a "
        "mode where intake was handed the case's own expected fields, so nothing was "
        "read and no case could route wrongly — it demonstrated that the graph holds "
        "together, which is worth knowing and is not evidence about the agent. These "
        f"{lifecycle['n_cases']} run on `--route rules`: the email is read by the "
        "deterministic extractor and the graph routes on what it found. The old mode "
        "is still reachable as `--route truth` and remains the default, so the Week 6 "
        "number stays reproducible."
    )
    add("")
    add(
        "Path coverage is enumerated from the graph rather than discovered from the "
        "run, so a path nothing reaches appears as a gap instead of simply never "
        "appearing."
    )
    add("")
    add("**Evidence.** `benchmarks/raw/w9_order_eval.json`, `w9_invoice_eval.json`, "
        "`w9_lifecycle_eval.json`. Regenerate with `python -m src.ml.order_eval_scale "
        "--run`, `python -m src.ml.invoice_eval_scale`, `python -m "
        "src.ml.lifecycle_eval_scale --cases 100`.")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DOC_PATH)
    args = ap.parse_args()

    body = build()
    write_section(args.out, SECTION_ID, body)
    log.info("section %r -> %s", SECTION_ID, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
