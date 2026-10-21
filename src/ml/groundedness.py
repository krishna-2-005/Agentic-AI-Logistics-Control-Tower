"""Groundedness judging for the Analytics assistant (execution plan v3.1 W7 D5, Lahari).

    python -m src.ml.groundedness --precheck     # rebuild contexts, check every number
    python -m src.ml.groundedness --report       # merge in the hand verdicts, write the summary
    python -m src.ml.groundedness --agreement docs/human_tasks/second_labeller_groundedness_sheet.csv

Two stages, and the split is the point.

1. **The pre-check is mechanical.** For every model-phrased answer, rebuild the context the
   assistant was given — retrieval is deterministic over the same index, so the no-model
   path returns the same passages — and check whether every number in the answer appears
   in that context. A number that is not there is either arithmetic the model did, or a
   number it brought from somewhere else. The pre-check cannot tell those apart, and it
   cannot see a claim that uses no number at all.
2. **The verdict is a judgement.** Each answer is read against its context and marked
   `grounded`, `partly grounded` or `not grounded`, with a one-line reason, in
   `benchmarks/raw/w7_groundedness_verdicts.csv`. The pre-check column sits beside it so a
   reader can see where the judgement agreed with the arithmetic and where it did not.

The builder does not grade his own agent (D-028): `assistant_eval.py` scores routes and
sources and deliberately stops there.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("ml.groundedness")

RAW = config.BENCHMARKS_RAW_DIR
ANSWERS = RAW / "w7_assistant_answers_llm.jsonl"
PRECHECK = RAW / "w7_groundedness_precheck.csv"
VERDICTS = RAW / "w7_groundedness_verdicts.csv"
SUMMARY = RAW / "w7_groundedness_summary.json"
REFUSAL = "I don't have that in the project data."

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> list[str]:
    """Numbers as written, normalised: commas dropped, trailing zeros kept apart from ints."""
    out = []
    for raw in _NUMBER.findall(text or ""):
        value = raw.replace(",", "")
        value = value.removesuffix(".")
        out.append(value)
    return out


def _variants(value: str) -> set[str]:
    """The forms a number can take in a context: 13.88 may appear as 13.88, 13.9 or 14."""
    forms = {value}
    try:
        number = float(value)
    except ValueError:
        return forms
    for places in (0, 1, 2):
        forms.add(f"{number:.{places}f}")
    if number.is_integer():
        forms.add(str(int(number)))
    return forms


def unsupported(answer: str, context: str) -> list[str]:
    """Numbers in the answer that appear in no form in the context."""
    context_numbers = {v for n in numbers(context) for v in _variants(n)}
    missing = []
    for value in numbers(answer):
        if not (_variants(value) & context_numbers):
            missing.append(value)
    return missing


def cohen_kappa(first: list[str], second: list[str]) -> dict:
    """Cohen's kappa for two labellers rating the same items with nominal labels.

    kappa = (p_o - p_e) / (1 - p_e); p_e is the agreement two labellers with these label
    frequencies would reach by chance. kappa is None when p_e is 1 (both always give one
    label), where it is undefined. Labels are compared case-insensitively.
    """
    if len(first) != len(second) or not first:
        raise ValueError("need two equal-length, non-empty label lists")
    a = [str(x).strip().lower() for x in first]
    b = [str(y).strip().lower() for y in second]
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    labels = sorted(set(a) | set(b))
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in labels)
    kappa = None if expected >= 1.0 else (observed - expected) / (1 - expected)
    return {"n": n, "observed_agreement": round(observed, 4),
            "chance_agreement": round(expected, 4),
            "kappa": None if kappa is None else round(kappa, 4)}


AGREEMENT = RAW / "b7_groundedness_agreement.json"


def agreement(second_sheet: str) -> dict:
    """Cohen's kappa between the first labeller's verdicts and a filled second-labeller sheet.

    The sheet is `docs/human_tasks/second_labeller_groundedness_sheet.csv` with the `verdict`
    column filled with grounded / partly grounded / not grounded. Blank rows are rejected:
    a half-filled sheet would quietly shrink n.
    """
    first = pd.read_csv(VERDICTS, keep_default_na=False)
    second = pd.read_csv(second_sheet, keep_default_na=False)
    merged = first.merge(second[["id", "verdict"]], on="id", suffixes=("_first", "_second"))
    if (merged["verdict_second"].str.strip() == "").any():
        raise ValueError("the second-labeller sheet has blank verdicts; fill every row first")
    result = cohen_kappa(merged["verdict_first"].tolist(), merged["verdict_second"].tolist())
    result["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    AGREEMENT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def precheck() -> pd.DataFrame:
    from src.agents.analytics_assistant import answer as ask

    rows = [json.loads(line) for line in ANSWERS.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    for row in rows:
        rebuilt = ask(row["question"], use_llm=False)
        refused = row["route"] == "refused" or row["answer"].strip().startswith(REFUSAL)
        missing = [] if refused else unsupported(row["answer"], rebuilt.context)
        records.append({
            "id": row["id"],
            "category": row["category"],
            "expected_route": row["expected_route"],
            "route": row["route"],
            "draft_source": row["draft_source"],
            "context_rebuilt_same_route": rebuilt.route == row["route"],
            "answer_numbers": len(numbers(row["answer"])),
            "numbers_not_in_context": ";".join(missing),
            "refused": refused,
            "question": row["question"],
            "answer": row["answer"],
        })
    frame = pd.DataFrame(records)
    frame.to_csv(PRECHECK, index=False)
    log.info("%d answers pre-checked; %d carry a number not found in their context",
             len(frame), int((frame["numbers_not_in_context"] != "").sum()))
    return frame


def report() -> dict:
    pre = pd.read_csv(PRECHECK, keep_default_na=False)
    verdicts = pd.read_csv(VERDICTS, keep_default_na=False)
    merged = pre.merge(verdicts[["id", "verdict", "reason"]], on="id", how="left")
    judged = merged[merged["verdict"] != ""]
    in_scope = judged[judged["expected_route"] != "refused"]
    out_scope = judged[judged["expected_route"] == "refused"]
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "judged": len(judged),
        "answers": len(merged),
        "grounded": int((judged["verdict"] == "grounded").sum()),
        "partly_grounded": int((judged["verdict"] == "partly grounded").sum()),
        "not_grounded": int((judged["verdict"] == "not grounded").sum()),
        "groundedness_rate_in_scope": round(float((in_scope["verdict"] == "grounded").mean()), 4)
        if len(in_scope) else None,
        # The headline. Extractive fallbacks are verbatim context by construction, so
        # counting them as grounded model answers would credit the model for answers it
        # did not write.
        "model_written_in_scope": int((in_scope["draft_source"] == "llm").sum()),
        "groundedness_rate_model_written": round(float(
            (in_scope[in_scope["draft_source"] == "llm"]["verdict"] == "grounded").mean()), 4)
        if (in_scope["draft_source"] == "llm").any() else None,
        "out_of_scope_refused": int(out_scope["refused"].sum()) if len(out_scope) else None,
        "out_of_scope_total": len(out_scope),
        "extractive_fallbacks": int((judged["draft_source"] == "extractive").sum()),
        "method": ("mechanical pre-check of every number against a rebuilt context, then a "
                   "hand verdict per answer; the builder's own scorer does not grade this (D-028)"),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("groundedness: %s", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Judge the assistant's answers for groundedness")
    parser.add_argument("--precheck", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--agreement", metavar="SHEET_CSV",
                        help="Cohen's kappa against a filled second-labeller sheet")
    args = parser.parse_args()
    if args.agreement:
        print(json.dumps(agreement(args.agreement), indent=2))
    if args.precheck:
        precheck()
    if args.report:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
