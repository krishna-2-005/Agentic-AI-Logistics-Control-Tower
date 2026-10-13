"""
The WP-02 evaluations: that they are the size they claim, and that the number
reported as evidence is the one that is evidence.

The second is the point of this file. The order-entry corpus found three defects
and those defects were fixed, so the current score on it is 100% and means very
little. The held-out first run is 85.0% and means a great deal. Nothing stops
someone quoting the wrong one except a test that says which is which.
"""

from __future__ import annotations

import json

import pytest

from src.common import config
from src.ml.stats import wilson

RAW = config.BENCHMARKS_RAW_DIR

ORDER = RAW / "w9_order_eval.json"
INVOICE = RAW / "w9_invoice_eval.json"
LIFECYCLE = RAW / "w9_lifecycle_eval.json"

pytestmark = pytest.mark.skipif(
    not ORDER.exists(),
    reason="WP-02 evaluations not run yet — python -m src.ml.order_eval_scale --run",
)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── the sets are the size the addendum asked for ─────────────────────────────


def test_every_agent_is_evaluated_on_at_least_150_cases() -> None:
    """The addendum's floor. Below it a per-stratum rate is an anecdote."""
    assert _load(ORDER)["n_cases"] >= 150
    assert _load(INVOICE)["n_cases"] >= 150
    assert _load(LIFECYCLE)["n_cases"] >= 100  # lifecycles, where the ask was 100


def test_the_order_set_is_half_adversarial() -> None:
    order = _load(ORDER)
    assert order["adversarial"]["total"] >= 60, "the ask was at least 60 adversarial cases"
    assert order["straightforward"]["total"] >= 60, (
        "an all-adversarial set cannot show that ordinary email still works"
    )


def test_every_invoice_kind_has_at_least_twenty_cases() -> None:
    """A per-kind claim on fewer than twenty is not a claim. The work order says
    150 invoices AND >= 20 per kind, which cannot both hold across ten kinds;
    the per-kind floor is the one that matters."""
    invoice = _load(INVOICE)
    thin = {k: v["verdict"]["total"] for k, v in invoice["by_kind"].items()
            if v["verdict"]["total"] < 20}
    assert not thin, f"kinds below 20 cases: {thin}"


# ── every rate carries an interval ───────────────────────────────────────────


@pytest.mark.parametrize("path", [ORDER, INVOICE, LIFECYCLE])
def test_rates_carry_intervals(path) -> None:
    """A bare proportion is what this whole package exists to stop reporting."""
    doc = _load(path)

    def walk(node):
        if isinstance(node, dict):
            if "rate" in node and "successes" in node:
                assert "ci_low" in node and "ci_high" in node, f"{node} has no interval"
                assert node["ci_low"] <= node["rate"] <= node["ci_high"]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)


def test_a_perfect_score_still_reports_uncertainty() -> None:
    """Wald would give zero width at p = 1.0, which is the failure being fixed."""
    p = wilson(20, 20)
    assert p.upper == 1.0
    assert p.lower < 0.9, "a perfect score on 20 should not claim a floor above 90%"
    assert wilson(200, 200).lower > p.lower, "more evidence must narrow the interval"


# ── the number reported as evidence ──────────────────────────────────────────


def test_the_held_out_order_result_is_recorded_and_is_not_the_headline_score() -> None:
    """The corpus found three defects; they were fixed; the current score is no
    longer independent of the set. Both numbers stay, and they must differ --
    if they ever match, either nothing was fixed or the record was overwritten.
    """
    order = _load(ORDER)
    held = order["held_out_first_run"]

    assert held["overall"]["rate"] == pytest.approx(0.85, abs=0.005)
    assert held["templates_at_zero"], "the held-out run's failures are not recorded"
    assert held["orders_filed_on_invented_values"] > 0

    assert order["overall"]["rate"] > held["overall"]["rate"], (
        "the post-fix score is not above the held-out one; if the fixes were "
        "reverted this record is now misleading"
    )


def test_the_frozen_order_value_is_the_held_out_one() -> None:
    """What reaches the paper. Freezing the post-fix 100% would put a number in
    front of a reader that looks like evidence and is not."""
    freeze = json.loads(
        (config.BENCHMARKS_DIR / "results_freeze_v4.json").read_text(encoding="utf-8")
    )
    values = {v["id"]: v["value"] for v in freeze["values"]}
    assert values["order_eval_scale_heldout"] == pytest.approx(0.85, abs=0.005)
    assert values["order_eval_scale_adversarial_heldout"] == pytest.approx(0.70, abs=0.005)
    assert 1.0 not in (
        values["order_eval_scale_heldout"],
        values["order_eval_scale_adversarial_heldout"],
    )


def test_the_invoice_miss_is_recorded_as_deliberate() -> None:
    """`overcharge_hidden` is 0 of 20 by design (D-047). Without the annotation a
    reader sees a broken auditor rather than a priced tolerance."""
    invoice = _load(INVOICE)
    assert "overcharge_hidden" in invoice["expected_misses"]
    assert invoice["by_kind"]["overcharge_hidden"]["verdict"]["successes"] == 0
    assert invoice["missed_by_design"] == invoice["missed_problems"], (
        "a problem was missed that is not one of the by-design kinds"
    )


def test_no_correct_invoice_is_disputed() -> None:
    """The expensive direction. Missing an overcharge costs money once; disputing
    a supplier who billed correctly costs a relationship."""
    assert _load(INVOICE)["false_disputes"] == 0


def test_the_lifecycle_run_reads_the_email() -> None:
    """Week 6's lifecycles handed intake the answer, so no case could route
    wrongly. This run must not be recorded the same way."""
    lifecycle = _load(LIFECYCLE)
    assert lifecycle["route"] == "rules"
    assert lifecycle["used_llm"] is False


def test_every_graph_path_is_exercised() -> None:
    cov = _load(LIFECYCLE)["path_coverage"]
    assert cov["exercised"] == cov["possible"], f"never taken: {cov['never_taken']}"
    assert not cov["unexpected_paths"], (
        f"the graph took a path not enumerated in ALL_PATHS: {cov['unexpected_paths']}"
    )


def test_the_evaluations_cost_nothing() -> None:
    """All three run without a model call. If that stops being true the daily
    quota becomes a dependency of the evaluation, which is how the order agent
    ended up scored on 50 cases over five days."""
    assert _load(LIFECYCLE)["used_llm"] is False
    assert _load(ORDER)["route"] == "rules"
    assert _load(ORDER)["llm_route"]["status"] == "not run"
