"""B7: the ablation harness, with the model mocked. Nothing here touches the network."""

import json
import math

import pytest

from src.agents.prompts.registry import load_variant
from src.ml import agent_ablation as ab


def test_fleiss_kappa_perfect_and_hand_computed():
    assert ab.fleiss_kappa([["a", "a", "a"], ["b", "b", "b"]]) == pytest.approx(1.0)
    k = ab.fleiss_kappa([["a", "a"], ["a", "b"], ["b", "b"], ["b", "a"]])
    # Pbar = (1+0+1+0)/4 = 0.5 ; shares 0.5/0.5 ; Pe = 0.5 ; kappa = 0
    assert k == pytest.approx(0.0, abs=1e-9)


def test_fleiss_kappa_known_value():
    # 3 subjects, 3 raters. counts: [3,0], [2,1], [0,3] -> P_i = [1, 1/3, 1]; Pbar = 7/9
    # shares: a = 5/9, b = 4/9 ; Pe = 25/81 + 16/81 = 41/81 ; kappa = (7/9 - 41/81)/(40/81)
    ratings = [["a", "a", "a"], ["a", "a", "b"], ["b", "b", "b"]]
    expected = (7 / 9 - 41 / 81) / (40 / 81)
    assert ab.fleiss_kappa(ratings) == pytest.approx(expected)


def test_fleiss_kappa_undefined_when_everything_identical_and_validates():
    assert ab.fleiss_kappa([["a"] * 5, ["a"] * 5]) is None
    with pytest.raises(ValueError):
        ab.fleiss_kappa([["a", "b"], ["a"]])


def test_unanimity():
    out = ab.unanimity([["a"] * 5, ["a", "a", "b", "a", "a"], ["b"] * 5, ["b"] * 5])
    assert out["successes"] == 3 and out["total"] == 4


def test_bootstrap_diff_is_deterministic_and_signed():
    a = ab.bootstrap_diff([1.0] * 10, [0.0] * 10, resamples=200)
    assert a["difference"] == 1.0 and a == ab.bootstrap_diff([1.0] * 10, [0.0] * 10, resamples=200)
    with pytest.raises(ValueError):
        ab.bootstrap_diff([1.0], [1.0, 0.0])


def test_parsers_accept_valid_and_reject_everything_else():
    assert ab.parse_order_verdict('{"verdict":"file","order":{"pieces":3},"missing_field":null}')["verdict"] == "file"
    for bad in ("```json\n{}\n```", "not json", "[1]", '{"verdict":"maybe"}',
                '{"verdict":"ask","order":{}}', '{"verdict":"ask","missing_field":"colour"}'):
        with pytest.raises(ab.VerdictParseError):
            ab.parse_order_verdict(bad)
    assert ab.parse_invoice_verdict('{"verdict":"approve","reason_code":null}')["verdict"] == "approve"
    for bad in ('{"verdict":"approve","reason_code":"total_mismatch"}', '{"verdict":"dispute","reason_code":null}',
                '{"verdict":"dispute","reason_code":"vibes"}'):
        with pytest.raises(ab.VerdictParseError):
            ab.parse_invoice_verdict(bad)
    assert ab.parse_exception_verdict('{"severity":"high"}')["verdict"] == "high"
    with pytest.raises(ab.VerdictParseError):
        ab.parse_exception_verdict('{"severity":"urgent"}')


def test_cache_key_depends_on_every_part():
    base = ("order", "c1", "s0", 0.7, "prompt", "m")
    keys = {ab.cache_key(*base)}
    for i, alt in enumerate(["x", "c2", "s1", 0.0, "prompt2", "m2"]):
        changed = list(base)
        changed[i] = alt
        keys.add(ab.cache_key(*changed))
    assert len(keys) == 7


def test_cached_call_hits_the_provider_once(tmp_path):
    calls = []

    def fake(prompt, temperature):
        calls.append((prompt, temperature))
        return '{"severity":"low"}', 10, 5

    ledger = ab.Ledger()
    first = ab.cached_call("exception", "c1", "s0", 0.7, "p", fake, ledger, cache_dir=tmp_path)
    again = ab.cached_call("exception", "c1", "s0", 0.7, "p", fake, ledger, cache_dir=tmp_path)
    assert len(calls) == 1 and first["text"] == again["text"]
    assert ledger.calls == 2 and ledger.cache_hits == 1 and ledger.input_tokens == 20


def test_provider_failure_is_not_cached(tmp_path):
    def boom(prompt, temperature):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        ab.cached_call("order", "c1", "s0", 0.7, "p", boom, ab.Ledger(), cache_dir=tmp_path)
    assert not list(tmp_path.rglob("*.json"))


def test_subset_is_balanced_seeded_and_prefix_balanced():
    items = list(range(60))
    strata = [f"s{i % 3}" for i in items]
    a = ab.pick_subset(items, strata, 4)
    assert a == ab.pick_subset(items, strata, 4)
    assert len(a) == 12
    first_six = [strata[i] for i in a[:6]]
    assert sorted(first_six) == ["s0", "s0", "s1", "s1", "s2", "s2"]


def test_variant_prompts_load_and_render():
    for agent in ("order_entry", "invoice_audit", "exception_triage"):
        prompt = load_variant(agent, "llm_verdict_v1")
        assert prompt.version == "llm_verdict_v1" and "JSON" in prompt.text
    with pytest.raises(ValueError):
        load_variant("order_entry", "../v1")
    with pytest.raises(FileNotFoundError):
        load_variant("order_entry", "llm_verdict_v9")


def _fake_caller_for(case_lookup):
    def fake(prompt, temperature):
        return case_lookup(prompt, temperature), 100, 20
    return fake


def test_run_case_scores_runs_and_counts_errors(tmp_path):
    cases, _ = ab.exception_cases(8)
    case = cases[0]

    def answer(prompt, temperature):
        # sampled runs disagree on purpose; temperature 0 is junk once
        if temperature == 0.0:
            return "garbage"
        return json.dumps({"severity": case.det_verdict})

    ledger = ab.Ledger()
    runs = ab.run_case(case, _fake_caller_for(answer), ledger, cache_dir=tmp_path)
    assert all(runs[r]["correct"] for r in ab.SAMPLED_RUNS)
    assert runs["t0a"]["label"] == "error" and runs["t0a"]["error"]
    assert ledger.calls == 7


def test_summarise_order_with_mock_model(tmp_path):
    cases, _ = ab.order_cases(20)
    by_prompt = {c.prompt_text: c for c in cases}

    def answer(prompt, temperature):
        c = by_prompt[prompt]
        truth = c.truth["case"]
        if truth["expected_action"] == "clarify":
            return json.dumps({"verdict": "ask", "order": {}, "missing_field": truth["expected_missing"]})
        return json.dumps({"verdict": "file", "order": truth["expected_fields"], "missing_field": None})

    ledger = ab.Ledger()
    runs = {c.case_id: ab.run_case(c, _fake_caller_for(answer), ledger, cache_dir=tmp_path) for c in cases}
    summary = ab.summarise_agent("order", cases, runs, {})
    assert summary["llm_sampled_T0.7"]["pooled_accuracy_5_runs"]["rate"] == 1.0
    assert summary["llm_sampled_T0.7"]["unanimity"]["rate"] == 1.0
    assert summary["llm_T0"]["determinism_same_verdict_across_two_runs"]["rate"] == 1.0
    assert summary["llm_invented_value_rate"]["successes"] == 0
    assert summary["parse_or_schema_errors"]["count"] == 0


def test_invented_centre_code_is_flagged(tmp_path):
    cases, _ = ab.order_cases(20)
    case = next(c for c in cases if c.truth["case"]["expected_action"] == "file")

    def answer(prompt, temperature):
        fields = dict(case.truth["case"]["expected_fields"])
        fields["origin_centre"] = "IND999999ZZZ"
        return json.dumps({"verdict": "file", "order": fields, "missing_field": None})

    runs = ab.run_case(case, _fake_caller_for(answer), ab.Ledger(), cache_dir=tmp_path)
    assert runs["s0"]["invented"] is True and runs["s0"]["correct"] is False


def test_invoice_ledger_contains_duplicate_source_and_is_fixed_size():
    cases, _ = ab.invoice_cases(40)
    dup = next(c for c in cases if c.stratum == "duplicate_number")
    assert dup.truth["expected_finding"] == "duplicate_invoice_number"
    assert dup.prompt_text.count("LEV-") >= ab.LEDGER_SIZE
    assert dup.det_verdict == "dispute"
    clean = next(c for c in cases if c.stratum == "clean")
    assert clean.det_verdict == "approve"


def test_cost_estimate_is_labelled_and_free_tier_is_zero():
    ledger = ab.Ledger(calls=10, input_tokens=8000, output_tokens=2000)
    est = ab.cost_estimate(ledger)
    assert est["free_tier_cost_usd"] == 0.0
    assert est["paid_equivalent_usd_per_1000_verdicts_ESTIMATE"] == pytest.approx(
        (800 * 0.15 + 200 * 0.60) / 1e6 * 1000, rel=1e-3)


def test_throttle_records_and_adapts():
    t = ab.Throttle(tokens_per_minute=10_000, estimate=900)
    t.wait()
    t.record(1500)
    assert t.estimate > 900 and not math.isnan(t.estimate)


def test_run_hard_with_mock_model(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ab, "OUT_HARD", tmp_path / "hard.json")
    by_prompt = {c.prompt_text: c for c in ab.order_hard_cases() + ab.invoice_hard_cases()}

    def answer(prompt, temperature):
        c = by_prompt[prompt]
        if c.agent == "invoice":
            code = c.truth["expected_finding"]
            return json.dumps({"verdict": c.truth["expected_verdict"], "reason_code": code}), 50, 10
        truth = c.truth["case"]
        if truth["expected_action"] == "clarify":
            return json.dumps({"verdict": "ask", "order": {}, "missing_field": truth["expected_missing"]}), 50, 10
        return json.dumps({"verdict": "file", "order": truth["expected_fields"], "missing_field": None}), 50, 10

    result = ab.run_hard(answer, ab.Ledger(), limit=10)
    assert result["agents"]["order"]["cases_completed"] == 10
    assert result["agents"]["order"]["llm_T0"]["rate"] == 1.0
    assert result["agents"]["invoice"]["llm_T0"]["rate"] == 1.0
    assert result["agents"]["order"]["deterministic_on_same_cases"]["total"] == 10
