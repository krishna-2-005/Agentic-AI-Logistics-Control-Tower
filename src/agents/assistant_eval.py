"""Run the Analytics Assistant over its fixed 30-question set (execution plan v3.1 W7 D5).

    python -m src.agents.assistant_eval --no-llm          # routes and sources, zero quota
    python -m src.agents.assistant_eval --budget 15       # model-phrased answers, resumable

Two things are scored automatically, and one is left to a person on purpose:

* **route** -- did the question go to the ranked table, to retrieval, or to refusal, as the
  set expects? Wrong routing is the assistant answering a different question.
* **source** -- for table and retrieval answers, does at least one returned source carry
  the expected table, corridor or decision id?
* **groundedness** is *not* scored here. Whether every number in an answer appears in its
  context, and nothing is claimed the context does not support, is Lahari's judgement on
  the saved answers (W7 D5). A script that grades its own agent's groundedness is the
  builder marking its own work, which D-028 exists to prevent.

Model-phrased runs cost one call per answered question, so they are cached per question
and stop cleanly on a quota refusal, like the Order Entry evaluation. Refused questions
cost nothing -- refusal is decided before any call.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from src.agents.analytics_assistant import answer
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.assistant_eval")

QUESTIONS = config.BENCHMARKS_RAW_DIR / "w7_assistant_questions_v1.json"


def out_paths(use_llm: bool) -> tuple[Path, Path]:
    mode = "llm" if use_llm else "no_llm"
    raw = config.BENCHMARKS_RAW_DIR
    return raw / f"w7_assistant_run_{mode}.json", raw / f"w7_assistant_answers_{mode}.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def load_answers(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {row["id"]: row for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def score(question: dict, result: dict) -> dict:
    route_ok = result["route"] == question["expected_route"]
    expected_source = question.get("expected_source") or ""
    if question["expected_route"] == "refused":
        source_ok = result["route"] == "refused"
    elif not expected_source:
        source_ok = bool(result["sources"])
    else:
        source_ok = any(expected_source in source for source in result["sources"])
    return {"route_correct": route_ok, "source_correct": source_ok}


def _is_quota_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("429", "resource_exhausted", "quota"))


def run(use_llm: bool = False, budget: int | None = None, questions_path: Path = QUESTIONS) -> dict:
    questions = load_questions(questions_path)
    summary_path, answers_path = out_paths(use_llm)
    done = load_answers(answers_path)
    calls = 0

    for question in questions:
        if question["id"] in done:
            continue
        if use_llm and budget is not None and calls >= budget and question["expected_route"] != "refused":
            log.info("budget of %d model call(s) reached; the rest resume on the next run", budget)
            break
        result = asdict(answer(question["question"], use_llm=use_llm))
        if use_llm and result["draft_source"] == "extractive" and result["route"] != "refused":
            # The model call failed and the assistant fell back. On a quota refusal that is
            # not an answer to score -- stop, and let the next run pick this question up.
            from src.agents.tracing import read_traces

            last = read_traces(agent="analytics_assistant", limit=1)
            if last and _is_quota_error(json.dumps(last[0])):
                log.warning("quota reached at %s -- stopping without recording it", question["id"])
                break
        if use_llm and result["route"] != "refused":
            calls += 1
        record = {**question, **{k: result[k] for k in ("route", "answer", "sources", "nearest_distance", "draft_source")},
                  **score(question, result), "answered_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        with answers_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        done[question["id"]] = record
        log.info("%s %-9s route=%-9s source=%s", question["id"], "ok" if record["route_correct"] else "WRONG-ROUTE",
                 record["route"], "ok" if record["source_correct"] else "MISS")

    rows = list(done.values())
    categories: dict[str, dict] = {}
    for row in rows:
        bucket = categories.setdefault(row["category"], {"n": 0, "route_correct": 0, "source_correct": 0})
        bucket["n"] += 1
        bucket["route_correct"] += int(row["route_correct"])
        bucket["source_correct"] += int(row["source_correct"])
    refused_expected = [r for r in rows if r["expected_route"] == "refused"]
    refused_actual = [r for r in rows if r["route"] == "refused"]
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "llm" if use_llm else "no_llm",
        "answered": len(rows),
        "questions": len(questions),
        "route_accuracy": round(sum(r["route_correct"] for r in rows) / len(rows), 4) if rows else None,
        "source_accuracy": round(sum(r["source_correct"] for r in rows) / len(rows), 4) if rows else None,
        "refusal_recall": round(sum(r["route"] == "refused" for r in refused_expected) / len(refused_expected), 4)
        if refused_expected else None,
        "refusal_precision": round(sum(r["expected_route"] == "refused" for r in refused_actual) / len(refused_actual), 4)
        if refused_actual else None,
        "by_category": categories,
        "groundedness": "not scored by this script -- judged by hand on the saved answers (Lahari, W7 D5)",
        "misses": [{"id": r["id"], "expected": r["expected_route"], "got": r["route"], "sources": r["sources"][:3]}
                   for r in rows if not (r["route_correct"] and r["source_correct"])],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("%d of %d answered: route %.1f%%, source %.1f%%", len(rows), len(questions),
             100 * (summary["route_accuracy"] or 0), 100 * (summary["source_accuracy"] or 0))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the assistant over its fixed question set")
    parser.add_argument("--no-llm", action="store_true", help="extractive answers, zero quota")
    parser.add_argument("--budget", type=int, default=None, help="max model calls this run")
    parser.add_argument("--fresh", action="store_true", help="discard saved answers for this mode first")
    args = parser.parse_args()
    if args.fresh:
        for path in out_paths(not args.no_llm):
            path.unlink(missing_ok=True)
    summary = run(use_llm=not args.no_llm, budget=args.budget)
    print(json.dumps({k: summary[k] for k in ("answered", "route_accuracy", "source_accuracy",
                                               "refusal_recall", "refusal_precision", "misses")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
