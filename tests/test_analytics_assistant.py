"""Tests for the Analytics Assistant, its tracing and its question-set runner (v3.1 W7 D3-D5).

    pytest tests/test_analytics_assistant.py -q

No LLM and no vector index: retrieval is replaced with a stub wherever it is reached, so
what is pinned is the routing, the refusal gate, the trace log and the scoring.
"""

from __future__ import annotations

import json

import pytest

from src.agents import analytics_assistant as aa
from src.agents import assistant_eval as ae
from src.agents import tracing

QUESTION_SET = ae.QUESTIONS


# ── routing ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("question", [
    "Which corridors are the worst bottlenecks?",
    "What are the top 3 slowest corridors in the network?",
    "Show the 10 worst bottleneck routes.",
])
def test_ranking_questions_about_corridors_take_the_table_route(question):
    routed = aa.table_route(question)
    assert routed is not None and routed[1] == ["w2_top20_bottlenecks.csv"]


def test_the_hub_ranking_question_d045_broke_goes_to_the_table():
    # Pure retrieval ranked Aluva (rank 1) below rank 11 for this exact question.
    context, sources = aa.table_route("Which hub has the longest dwell time?")
    assert sources == ["w2_hub_friction_top20.csv"]
    assert context.splitlines()[0].startswith("rank 1: hub IND683511AAA")


def test_a_hub_question_without_a_ranking_word_is_not_routed_to_the_table():
    # "dwell" and "hub" but asking about one hub -- the top-5 table would answer a
    # different question.
    assert aa.table_route("Tell me about dwell at the Hubli hub.") is None


def test_faster_or_slower_is_a_fact_question_not_a_ranking():
    assert aa.table_route("Is the Dhampur to Kanth corridor faster or slower than the network?") is None


def test_top_n_is_honoured_and_capped():
    context, _ = aa.table_route("What are the top 3 slowest corridors in the network?")
    assert len(context.splitlines()) == 3
    assert aa._top_n("top 99 worst corridors") == 20
    assert aa._top_n("which corridors are worst") == aa.TOP_N_DEFAULT


def test_the_fastest_corridors_are_confirmed_faster_ones():
    context, sources = aa.table_route("Which corridors run fastest compared with the network?")
    assert sources == ["w2_corridor_audit.csv"]
    assert all("statistically confirmed faster" in line for line in context.splitlines())


# ── refusal and answering ───────────────────────────────────────────────────
def _stub_search(distance: float):
    def search(question, k=5):
        return [{"text": "Corridor X runs slow. It has 40 legs.", "distance": distance,
                 "metadata": {"kind": "corridor", "corridor_id": "INDA>INDB"}}]
    return search


def test_a_far_question_is_refused_without_calling_the_model(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACE_PATH", tmp_path / "t.jsonl")
    import src.common.vectordb as vdb

    monkeypatch.setattr(vdb, "search", _stub_search(0.9))
    from src.agents import llm

    monkeypatch.setattr(llm, "get_llm", lambda: pytest.fail("a refusal must cost zero quota"))
    result = aa.answer("What is the capital of France?", use_llm=True)
    assert result.route == "refused" and result.answer == aa.REFUSAL


def test_a_close_question_is_answered_extractively_with_a_citation(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACE_PATH", tmp_path / "t.jsonl")
    import src.common.vectordb as vdb

    monkeypatch.setattr(vdb, "search", _stub_search(0.3))
    result = aa.answer("Tell me about corridor INDA>INDB", use_llm=False)
    assert result.route == "retrieval" and result.draft_source == "extractive"
    assert "(corridor_audit (INDA>INDB))" in result.answer


def test_a_failed_model_call_falls_back_to_a_grounded_extract(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACE_PATH", tmp_path / "t.jsonl")
    import src.common.vectordb as vdb
    from src.agents import llm

    class Boom:
        def invoke(self, _):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(vdb, "search", _stub_search(0.3))
    monkeypatch.setattr(llm, "get_llm", lambda: Boom())
    result = aa.answer("Tell me about corridor INDA>INDB", use_llm=True)
    assert result.draft_source == "extractive" and "INDA>INDB" in result.answer


def test_the_refusal_threshold_sits_above_every_calibrated_in_scope_probe():
    # Calibration: in-scope 0.349-0.588, easy out-of-scope 0.681-0.941.
    assert 0.588 < aa.REFUSAL_DISTANCE < 0.681


# ── tracing ─────────────────────────────────────────────────────────────────
def test_every_call_is_traced_with_inputs_and_outputs(monkeypatch, tmp_path):
    path = tmp_path / "t.jsonl"
    with tracing.traced("demo", inputs={"q": "hello"}, path=path) as span:
        span.outputs = {"a": "world"}
    record = tracing.read_traces(path)[0]
    assert record["agent"] == "demo" and record["inputs"] == {"q": "hello"}
    assert record["outputs"] == {"a": "world"} and record["error"] is None


def test_a_failing_call_is_still_traced_with_its_error(tmp_path):
    path = tmp_path / "t.jsonl"
    with pytest.raises(ValueError), tracing.traced("demo", inputs={}, path=path):
        raise ValueError("boom")
    assert "ValueError: boom" in tracing.read_traces(path)[0]["error"]


def test_long_fields_are_truncated_not_dropped(tmp_path):
    path = tmp_path / "t.jsonl"
    with tracing.traced("demo", inputs={"q": "x" * 5000}, path=path):
        pass
    stored = tracing.read_traces(path)[0]["inputs"]["q"]
    assert stored.startswith("x" * 100) and "more" not in stored and "+3000 chars" in stored


def test_the_order_entry_agent_traces_a_failed_extraction(monkeypatch):
    from src.agents import order_agent
    from src.agents.order_corpus import OrderEmail
    from src.agents.prompts.registry import load_prompt

    def boom(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(order_agent, "extract_order", boom)
    email = OrderEmail(seq=7, variant="clean", subject="Booking", body="Please collect 3 pieces.",
                       expected_action="file", expected_missing=None, expected_fields={})
    outcome = order_agent.process_email(email, load_prompt("order_entry"), dry_run=True)
    record = tracing.read_traces(agent="order_entry")[0]
    assert record["inputs"]["seq"] == 7 and record["inputs"]["dry_run"] is True
    # The agent swallows the failure into its outcome, so the trace shows it there.
    assert record["outputs"]["error"] == outcome.error == "model unavailable"


def test_the_conftest_keeps_test_traces_out_of_the_real_log():
    assert tracing.TRACE_PATH != tracing.config.DATA_DIR / "traces" / "agent_calls.jsonl"


def test_traces_read_newest_first_and_skip_bad_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    for name in ("first", "second"):
        with tracing.traced(name, inputs={}, path=path):
            pass
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert [r["agent"] for r in tracing.read_traces(path)] == ["second", "first"]


# ── the fixed question set and its scoring ──────────────────────────────────
def test_the_question_set_is_thirty_with_unique_ids_and_valid_routes():
    questions = ae.load_questions(QUESTION_SET)
    assert len(questions) == 30
    assert len({q["id"] for q in questions}) == 30
    assert {q["expected_route"] for q in questions} <= {"table", "retrieval", "refused"}
    assert sum(q["expected_route"] == "refused" for q in questions) == 6


def test_every_table_question_in_the_set_is_routed_to_the_table():
    for question in ae.load_questions(QUESTION_SET):
        routed = aa.table_route(question["question"]) is not None
        assert routed == (question["expected_route"] == "table"), question["id"]


def test_source_scoring_matches_on_the_expected_id():
    question = {"expected_route": "retrieval", "expected_source": "D-003"}
    good = {"route": "retrieval", "sources": ["decisions.md -- D-003 · Delay label threshold"]}
    bad = {"route": "retrieval", "sources": ["decisions.md -- D-024 · Week 4 is judged on MAE"]}
    assert ae.score(question, good) == {"route_correct": True, "source_correct": True}
    assert ae.score(question, bad)["source_correct"] is False


def test_a_refusal_question_scores_only_a_refusal():
    question = {"expected_route": "refused", "expected_source": ""}
    assert ae.score(question, {"route": "refused", "sources": []}) == {"route_correct": True, "source_correct": True}
    assert ae.score(question, {"route": "retrieval", "sources": ["x"]}) == {"route_correct": False, "source_correct": False}


def test_answers_are_resumable(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text(json.dumps({"id": "T01", "route": "table"}) + "\n", encoding="utf-8")
    assert set(ae.load_answers(path)) == {"T01"}
