"""Freight Invoice Auditor v1 (execution plan W6 D5).

    python -m src.agents.invoice_auditor --count 20            # audit a generated batch
    python -m src.agents.invoice_auditor --count 20 --no-draft # no model call
    python -m src.agents.invoice_auditor --count 5 --post      # submit + settle in the TMS

Cross-checks a freight invoice against the shipment's own order and the corridor's
audited rate band, then approves it or disputes it with reasons.

Every check is arithmetic
-------------------------
The auditor's four checks are all comparisons against numbers the project already
knows exactly:

* **the invoice's own arithmetic** -- freight + other against the printed total, which
  is D-021's `total_mismatch` seeded error;
* **the corridor's audited rate band** -- Week 2's `mean_osrm_km` times the rate model
  the corpus itself uses (FTL is a per-km rate; Carting is per-km-per-tonne plus a
  handling charge), so "too expensive" is a band, not an opinion;
* **the share taken by other charges**, against the same 5-18% band the corpus draws
  from;
* **duplicate invoice numbers**, which D-021 seeds deliberately because the same
  external number legitimately arriving twice is exactly what an auditor must catch.

A model is asked for one thing only: the sentence that goes back to the supplier. It
never decides whether to dispute, and it never produces a number -- `--no-draft` swaps
in a template and changes no verdict. Lahari's D5 evaluation scores precision and
recall on a seeded-error set, which is only meaningful because the verdict does not
move between runs.

What "v1" means here
--------------------
The rate band is the corpus's own generator model, which makes it exact for these
invoices and **circular as a claim about real freight pricing**. It measures whether
the auditor catches an invoice that departs from the network's own observed rates; it
is not evidence that those rates are correct. A v2 would fit the band from billed
history rather than borrowing the generator's parameters.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.agents.doc_corpus.records import ConsignmentRecord, generate_records
from src.agents.exception_agent import load_audit
from src.agents.llm import get_llm
from src.agents.prompts.registry import Prompt, load_prompt
from src.agents.tms_client import TMSClient
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.invoice_auditor")

RUNS_JSON = config.BENCHMARKS_RAW_DIR / "w6_invoice_audit_runs.json"
CASES_JSON = config.BENCHMARKS_RAW_DIR / "w6_invoice_cases.json"

#: The corpus's own rate model (`src/agents/doc_corpus/records.py`). Imported as numbers
#: rather than re-derived: if the generator's bands ever move, this file must move with
#: it, and a constant named here is the place that shows up in a diff.
FTL_RATE_PER_KM = (28.0, 45.0)
CARTING_RATE_PER_KM_PER_TONNE = (6.0, 10.0)
CARTING_HANDLING_PER_KG = (2.0, 4.0)
OTHER_CHARGES_SHARE = (0.05, 0.18)

#: Slack on every band. The corridor's `mean_osrm_km` is a mean over legs, so an invoice
#: for one leg can sit slightly outside a band computed from it without being wrong.
#: Wide enough that an honest invoice is never disputed, narrow enough that the seeded
#: overcharges (50%+) are all caught -- a false dispute costs a supplier relationship,
#: which is more expensive than a missed few hundred rupees.
BAND_TOLERANCE = 0.15

#: The error kinds this auditor is built to catch, and the ground truth Lahari's D5
#: evaluation scores against. `clean` is weighted heavily for the same reason the order
#: corpus weights it: a set that is mostly broken teaches the wrong reflex.
CASE_WEIGHTS = {"clean": 5, "total_mismatch": 2, "overcharge": 2, "excessive_other": 2, "duplicate_number": 2}
FINDING_FOR_KIND = {
    "total_mismatch": "total_mismatch",
    "overcharge": "rate_above_band",
    "excessive_other": "other_charges_out_of_band",
    "duplicate_number": "duplicate_invoice_number",
}


@dataclass
class Finding:
    code: str
    detail: str


@dataclass
class InvoiceCase:
    """One synthetic invoice plus the ground truth of what is wrong with it."""

    seq: int
    kind: str
    corridor_id: str
    route_type: str
    weight_kg: float
    pieces: int
    external_invoice_number: str
    freight_charge: float
    other_charges: float
    total_amount: float
    currency: str = "INR"
    expected_finding: str | None = None

    @property
    def expected_verdict(self) -> str:
        return "approve" if self.expected_finding is None else "dispute"


@dataclass
class AuditOutcome:
    seq: int
    kind: str
    corridor_id: str
    verdict: str
    findings: list[dict] = field(default_factory=list)
    expected_verdict: str | None = None
    expected_finding: str | None = None
    note: str | None = None
    draft_source: str | None = None
    prompt_version: str | None = None
    invoice_ref: str | None = None
    posted: bool = False
    error: str | None = None


# ── the bands ────────────────────────────────────────────────────────────────
def freight_band(route_type: str, weight_kg: float, corridor_km: float) -> tuple[float, float]:
    """The rate band for one leg, from the corridor's audited distance.

    FTL is priced per kilometre; Carting adds a per-kilogram handling charge to a
    per-km-per-tonne rate. Both come straight from the corpus's generator.
    """
    if route_type == "FTL":
        low, high = (corridor_km * rate for rate in FTL_RATE_PER_KM)
    else:
        tonnes = weight_kg / 1000
        low = corridor_km * tonnes * CARTING_RATE_PER_KM_PER_TONNE[0] + weight_kg * CARTING_HANDLING_PER_KG[0]
        high = corridor_km * tonnes * CARTING_RATE_PER_KM_PER_TONNE[1] + weight_kg * CARTING_HANDLING_PER_KG[1]
    return round(low * (1 - BAND_TOLERANCE), 2), round(high * (1 + BAND_TOLERANCE), 2)


def audit_invoice(case: InvoiceCase, corridor_km: float | None, seen_numbers: set[str]) -> list[Finding]:
    """Every check, in one place. Returns the findings; empty means approve."""
    findings: list[Finding] = []

    expected_total = round(case.freight_charge + case.other_charges, 2)
    if abs(expected_total - case.total_amount) > 0.01:
        findings.append(Finding(
            "total_mismatch",
            f"freight {case.freight_charge:,.2f} + other {case.other_charges:,.2f} = "
            f"{expected_total:,.2f}, but the invoice totals {case.total_amount:,.2f} "
            f"(a difference of {case.total_amount - expected_total:,.2f})",
        ))

    # A corridor below D-018's leg floor has no audited distance, so there is no band to
    # check against. That is deliberately **not** a finding: "we cannot check this" is a
    # different statement from "this is wrong", and the TMS has only approve/dispute to
    # say it in. Disputing an invoice for the network's own lack of history would be a
    # supplier paying for our data gap.
    if corridor_km is not None:
        low, high = freight_band(case.route_type, case.weight_kg, corridor_km)
        if case.freight_charge > high:
            findings.append(Finding(
                "rate_above_band",
                f"freight {case.freight_charge:,.2f} is above the audited band for this "
                f"corridor ({low:,.2f}-{high:,.2f} for {case.route_type} over {corridor_km:,.1f} km)",
            ))
        elif case.freight_charge < low:
            findings.append(Finding(
                "rate_below_band",
                f"freight {case.freight_charge:,.2f} is below the audited band "
                f"({low:,.2f}-{high:,.2f}) -- worth confirming the shipment was carried in full",
            ))

    if case.freight_charge > 0:
        share = case.other_charges / case.freight_charge
        if not OTHER_CHARGES_SHARE[0] - 0.01 <= share <= OTHER_CHARGES_SHARE[1] + 0.01:
            findings.append(Finding(
                "other_charges_out_of_band",
                f"other charges are {share:.1%} of freight, outside the "
                f"{OTHER_CHARGES_SHARE[0]:.0%}-{OTHER_CHARGES_SHARE[1]:.0%} this network bills",
            ))

    if case.external_invoice_number in seen_numbers:
        findings.append(Finding(
            "duplicate_invoice_number",
            f"invoice number {case.external_invoice_number} has already been submitted",
        ))

    if case.currency != "INR":
        findings.append(Finding("unexpected_currency", f"invoice is in {case.currency}, not INR"))

    return findings


def verdict_for(findings: list[Finding]) -> str:
    """Dispute on any finding. There is no "approve with a note" state in the TMS, and
    inventing one here would put a judgement call where the schema has a boolean."""
    return "dispute" if findings else "approve"


# ── the one language step ────────────────────────────────────────────────────
def template_note(case: InvoiceCase, findings: list[Finding]) -> str:
    reasons = "; ".join(f.detail for f in findings)
    return (
        f"Invoice {case.external_invoice_number} on {case.corridor_id} is disputed: {reasons}. "
        "Please issue a corrected invoice."
    )


def draft_note(case: InvoiceCase, findings: list[Finding], prompt: Prompt | None,
               invoice_ref: str = "(unsubmitted)", shipment_ref: str = "(none)") -> tuple[str, str]:
    if prompt is None or not findings:
        return template_note(case, findings), "template"
    rendered = prompt.render(
        invoice_ref=invoice_ref, shipment_ref=shipment_ref, corridor_id=case.corridor_id,
        freight_charge=f"{case.freight_charge:,.2f}", other_charges=f"{case.other_charges:,.2f}",
        total_amount=f"{case.total_amount:,.2f}", currency=case.currency,
        findings="\n".join(f"- {f.detail}" for f in findings),
    )
    try:
        response = get_llm().invoke(rendered)
        content = getattr(response, "content", response)
        text = (content if isinstance(content, str) else "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )).strip()
        if not text:
            raise ValueError("empty draft")
    except Exception as exc:  # noqa: BLE001 -- wording must never cost the verdict
        log.warning("draft failed (%s) -- using the template", str(exc)[:120])
        return template_note(case, findings), "template"
    return text, "llm"


# ── the development corpus ───────────────────────────────────────────────────
def build_cases(count: int, seed: int = 7) -> list[InvoiceCase]:
    """`count` invoices over a deterministic mix, from real audited corridors (D-021).

    Every kind appears at least once before the weighted draw fills the rest -- the
    order corpus learned that lesson the expensive way (a weighted sample of twelve
    produced none of two kinds, leaving both paths untested).
    """
    records = generate_records(count, seed=seed)
    rng = random.Random(seed)
    kinds = list(CASE_WEIGHTS)[:count]
    population = [k for k, weight in CASE_WEIGHTS.items() for _ in range(weight)]
    kinds += [rng.choice(population) for _ in range(max(0, count - len(kinds)))]
    rng.shuffle(kinds)
    # `duplicate_number` cannot be the first case -- there is no earlier invoice number
    # to repeat, so `_case_from` downgrades it to clean, and the guarantee one line above
    # ("every kind appears at least once") quietly stops holding. Moving it one place
    # keeps the mix and the guarantee.
    if len(kinds) > 1 and kinds[0] == "duplicate_number":
        kinds[0], kinds[1] = kinds[1], kinds[0]

    cases: list[InvoiceCase] = []
    for record, kind in zip(records, kinds, strict=True):
        cases.append(_case_from(record, kind, rng, cases))
    return cases


def _case_from(record: ConsignmentRecord, kind: str, rng: random.Random,
               earlier: list[InvoiceCase]) -> InvoiceCase:
    freight, other = record.freight_charge, record.other_charges
    total = round(freight + other, 2)
    number = f"INV-{record.seq:06d}"

    if kind == "total_mismatch":
        total = round(total * (1 + rng.choice([-1, 1]) * rng.uniform(0.05, 0.30)), 2)
    elif kind == "overcharge":
        freight = round(freight * rng.uniform(1.6, 2.4), 2)
        other = round(freight * rng.uniform(*OTHER_CHARGES_SHARE), 2)
        total = round(freight + other, 2)
    elif kind == "excessive_other":
        other = round(freight * rng.uniform(0.30, 0.60), 2)
        total = round(freight + other, 2)
    elif kind == "duplicate_number":
        if earlier:
            number = rng.choice(earlier).external_invoice_number
        else:
            kind = "clean"

    return InvoiceCase(
        seq=record.seq, kind=kind, corridor_id=record.corridor_id, route_type=record.route_type,
        weight_kg=record.weight_kg, pieces=record.pieces, external_invoice_number=number,
        freight_charge=freight, other_charges=other, total_amount=total,
        expected_finding=FINDING_FOR_KIND.get(kind),
    )


# ── running a batch ──────────────────────────────────────────────────────────
def corridor_km_lookup(audit: pd.DataFrame) -> dict[str, float]:
    if audit.empty:
        return {}
    return audit["mean_osrm_km"].to_dict()


def run(count: int = 20, seed: int = 7, draft: bool = True, post: bool = False,
        out_path: Path = RUNS_JSON) -> dict:
    cases = build_cases(count, seed)
    CASES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CASES_JSON.write_text(json.dumps([asdict(c) for c in cases], indent=2), encoding="utf-8")

    km = corridor_km_lookup(load_audit())
    prompt = load_prompt("invoice_audit") if draft else None
    client = TMSClient() if post else None
    if client is not None and not client.is_up():
        log.warning("TMS is not answering -- auditing without submitting")
        client = None

    seen: set[str] = set()
    outcomes: list[AuditOutcome] = []
    for case in cases:
        findings = audit_invoice(case, km.get(case.corridor_id), seen)
        seen.add(case.external_invoice_number)
        decision = verdict_for(findings)
        outcome = AuditOutcome(
            seq=case.seq, kind=case.kind, corridor_id=case.corridor_id, verdict=decision,
            findings=[asdict(f) for f in findings],
            expected_verdict=case.expected_verdict, expected_finding=case.expected_finding,
            prompt_version=prompt.label if prompt else None,
        )
        if decision == "dispute":
            outcome.note, outcome.draft_source = draft_note(case, findings, prompt)
        outcomes.append(outcome)

    summary = {
        "cases": len(outcomes),
        "disputed": sum(1 for o in outcomes if o.verdict == "dispute"),
        "approved": sum(1 for o in outcomes if o.verdict == "approve"),
        "correct_verdicts": sum(1 for o in outcomes if o.verdict == o.expected_verdict),
        "drafted_by_llm": sum(1 for o in outcomes if o.draft_source == "llm"),
        "seed": seed,
        "generated_at": datetime.now().astimezone().isoformat(),
        "outcomes": [asdict(o) for o in outcomes],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(
        "%d invoice(s): %d disputed, %d approved, %d verdicts matching the seeded truth -> %s",
        summary["cases"], summary["disputed"], summary["approved"], summary["correct_verdicts"], out_path,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit freight invoices against orders and corridor stats")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-draft", action="store_true", help="template wording, no LLM call")
    parser.add_argument("--post", action="store_true", help="submit and settle the invoices in the TMS")
    parser.add_argument("--out", type=Path, default=RUNS_JSON)
    args = parser.parse_args()

    summary = run(count=args.count, seed=args.seed, draft=not args.no_draft,
                  post=args.post, out_path=args.out)
    for outcome in summary["outcomes"][:5]:
        mark = "ok " if outcome["verdict"] == outcome["expected_verdict"] else "MISS"
        print(f"\n[{mark}] #{outcome['seq']} {outcome['kind']:18} -> {outcome['verdict']}")
        for finding in outcome["findings"]:
            print(f"       {finding['code']}: {finding['detail'][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
