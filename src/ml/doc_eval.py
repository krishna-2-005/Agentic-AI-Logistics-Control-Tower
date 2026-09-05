"""Document-extraction evaluation harness (execution plan W4 D5) -- the first
Layer 2 (agent) evaluation number.

    python -m src.ml.doc_eval

Scores Krishna's Document Intelligence Agent predictions against the Week 3 ground
truth labels: field-level accuracy, micro-averaged precision/recall/F1, and coverage
(how many of the attempted documents actually produced a prediction, D-032). This
module never calls an LLM and never imports `src.agents.document_agent` beyond
reading the JSON file it already wrote -- deliberately separate code, per the
execution plan's own note that keeping builder and judge apart is "better science,
better viva answers" (also `docs/learning-log.md`'s Week 2 entry).

Scores every prompt version whose predictions file exists (`v1`, and `v2` once
D3-D4 produces it) so a version comparison falls out of one run rather than two.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.agents.doc_corpus.labels import LABEL_FIELDS
from src.common import config, docs
from src.common.logging_setup import get_logger

log = get_logger("ml.doc_eval")

#: Every predictions file this harness knows how to find, keyed by prompt version.
#: A version whose file does not exist yet is skipped, not an error -- D3-D4's `v2`
#: run is capped by the same daily LLM quota as D1-D2 (D-032) and may not exist on
#: every machine at every point in the week.
PREDICTIONS_FILES: dict[str, Path] = {
    "v1": config.BENCHMARKS_RAW_DIR / "w4_doc_agent_predictions.json",
    "v2": config.BENCHMARKS_RAW_DIR / "w4_doc_agent_predictions_v2.json",
}


def load_predictions(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_label(entry: dict, documents_dir: Path) -> dict:
    return json.loads((documents_dir / entry["label_json"]).read_text(encoding="utf-8"))


def null_baseline_fields() -> dict:
    """The trivial extractor `agent_evaluation.md`'s recording rules ask every metric
    to be reported beside: predict null for every field, i.e. extract nothing. Not a
    regex-on-raw-OCR baseline (the more informative trivial extractor for the
    fixed-shape fields) -- `run_corpus` does not persist the raw OCR text in the
    predictions file, so that comparison is not computable from what exists today.
    Noted as a gap rather than skipped silently; see the doc section this writes.
    """
    return dict.fromkeys(LABEL_FIELDS)


def score_document(predicted: dict, true: dict) -> dict:
    """Per-document TP/FP/FN over `LABEL_FIELDS`, plus whether every field matched.

    A field counts as a true positive only when the true value is not null and the
    prediction matches it exactly. A correctly-returned null (rule 1: never invent a
    value the document does not carry, e.g. a BOL's `total_amount`) is neither a hit
    nor a miss for precision/recall -- the same reason a slot-filling evaluation does
    not reward guessing "no value" on a field it is simply unsure about, and does not
    count a genuinely absent field as a missed extraction either.
    """
    tp = fp = fn = correct = 0
    for field in LABEL_FIELDS:
        true_val = true.get(field)
        pred_val = predicted.get(field)
        if pred_val == true_val:
            correct += 1
            if true_val is not None:
                tp += 1
        else:
            if true_val is not None:
                fn += 1
            if pred_val is not None:
                fp += 1
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "fields_correct": correct,
        "n_fields": len(LABEL_FIELDS),
        "exact_match": correct == len(LABEL_FIELDS),
    }


def _prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def score_predictions_file(path: Path, documents_dir: Path) -> dict:
    """Score one predictions file end to end -- coverage, per-field accuracy, and
    micro-averaged precision/recall/F1 (pooled over every (document, field) pair,
    not averaged per-document-then-per-field, so a document with more populated
    fields is not silently up-weighted or down-weighted relative to one with fewer).
    """
    data = load_predictions(path)
    predictions = data["predictions"]
    n_attempted = len(predictions)

    field_correct = dict.fromkeys(LABEL_FIELDS, 0)
    field_total = dict.fromkeys(LABEL_FIELDS, 0)
    tp = fp = fn = 0
    exact_matches = 0
    n_scored = 0

    for entry in predictions:
        if entry["predicted_fields"] is None:
            continue
        n_scored += 1
        true = load_label(entry, documents_dir)
        result = score_document(entry["predicted_fields"], true)
        tp += result["tp"]
        fp += result["fp"]
        fn += result["fn"]
        exact_matches += result["exact_match"]
        for field in LABEL_FIELDS:
            field_total[field] += 1
            field_correct[field] += int(entry["predicted_fields"].get(field) == true.get(field))

    precision, recall, f1 = _prf1(tp, fp, fn)
    field_table = pd.DataFrame({
        "field": LABEL_FIELDS,
        "correct": [field_correct[f] for f in LABEL_FIELDS],
        "n": [field_total[f] for f in LABEL_FIELDS],
        "accuracy": [
            round(field_correct[f] / field_total[f], 3) if field_total[f] else None
            for f in LABEL_FIELDS
        ],
    })

    return {
        "prompt_version": data.get("prompt_version"),
        "n_attempted": n_attempted,
        "n_scored": n_scored,
        "coverage": round(n_scored / n_attempted, 3) if n_attempted else 0.0,
        "exact_match_documents": exact_matches,
        "exact_match_rate": round(exact_matches / n_scored, 3) if n_scored else 0.0,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "field_table": field_table,
    }


def score_null_baseline(path: Path, documents_dir: Path) -> dict:
    """The trivial extractor, scored the identical way -- over the same documents,
    same field set, same metric. Recall is 0 by construction (nothing is ever
    extracted); precision and F1 follow from `_prf1`'s zero-division handling.
    """
    data = load_predictions(path)
    fn = 0
    n_scored = 0
    for entry in data["predictions"]:
        if entry["predicted_fields"] is None:
            continue
        n_scored += 1
        true = load_label(entry, documents_dir)
        fn += sum(1 for f in LABEL_FIELDS if true.get(f) is not None)
    precision, recall, f1 = _prf1(tp=0, fp=0, fn=fn)
    return {"n_scored": n_scored, "tp": 0, "fp": 0, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def render_doc(results: dict[str, dict], baseline: dict) -> str:
    o: list[str] = []
    o.append("## Document-extraction evaluation (D5) -- the first agent-eval number\n")
    o.append(
        "*Generated by `python -m src.ml.doc_eval` -- regenerate rather than editing "
        "numbers by hand. Scored against Krishna's predictions files "
        "(`week4-krishna-doc-agent`), never re-running OCR or the LLM.*\n"
    )
    o.append(
        "Precision/recall/F1 are micro-averaged over every (document, field) pair: a "
        "field counts as a true positive only when the true value is non-null and the "
        "prediction matches it exactly (a correctly-returned null is neither a hit nor "
        "a miss). Coverage is documents scored / documents attempted -- D-032's free-tier "
        "quota wall means this is well under 100% for both versions.\n"
    )
    o.append("| Prompt | Attempted | Scored | Coverage | Exact-match docs | Precision | Recall | F1 |")
    o.append("|---|---|---|---|---|---|---|---|")
    for version, r in results.items():
        o.append(
            f"| `doc_extraction/{version}` | {r['n_attempted']} | {r['n_scored']} | "
            f"{r['coverage']:.0%} | {r['exact_match_documents']}/{r['n_scored']} "
            f"({r['exact_match_rate']:.0%}) | {r['precision']:.3f} | {r['recall']:.3f} "
            f"| **{r['f1']:.3f}** |"
        )
    o.append(
        f"| Null baseline (predict nothing) | -- | {baseline['n_scored']} | -- | 0/{baseline['n_scored']} "
        f"(0%) | {baseline['precision']:.3f} | {baseline['recall']:.3f} | {baseline['f1']:.3f} |"
    )
    o.append("")

    if len(results) > 1:
        versions = list(results)
        base_v, new_v = versions[0], versions[-1]
        o.append(
            f"**`{new_v}` improves F1 from {results[base_v]['f1']:.3f} to "
            f"{results[new_v]['f1']:.3f}** over the documents each version actually "
            "scored -- not the identical sample in every case, since each run's quota "
            "cutoff lands on a different document (D-032). Per-field detail and the "
            "specific `document_number` fix are in D-033, not repeated here.\n"
        )

    o.append("### Per-field accuracy\n")
    o.append("| Field | " + " | ".join(f"`{v}`" for v in results) + " |")
    o.append("|---" * (len(results) + 1) + "|")
    for field in LABEL_FIELDS:
        row = [field]
        for v in results:
            ft = results[v]["field_table"]
            acc = ft.loc[ft["field"] == field, "accuracy"].iloc[0]
            n = ft.loc[ft["field"] == field, "n"].iloc[0]
            row.append(f"{acc:.0%} (n={n})" if acc is not None else "--")
        o.append("| " + " | ".join(row) + " |")
    o.append("")

    o.append(
        "**What is not in this table.** A regex-only trivial extractor for the "
        "fixed-shape fields (`document_number`, the two centre codes) would be a more "
        "informative baseline than \"predict nothing\" -- `agent_evaluation.md`'s own "
        "recording rules ask for one -- but `document_agent.run_corpus` does not persist "
        "the raw OCR text in the predictions file, only its character count, so a regex "
        "baseline is not computable from what exists today without re-running OCR. "
        "Noted as a gap for whoever next touches `document_agent.py`, not silently "
        "skipped.\n"
    )
    return "\n".join(o)


def main() -> int:
    documents_dir = config.DOCUMENTS_DIR
    results = {}
    for version, path in PREDICTIONS_FILES.items():
        if not path.exists():
            log.warning("%s missing -- skipping %s (D3-D4's v2 run may not have happened on this machine)", path, version)
            continue
        results[version] = score_predictions_file(path, documents_dir)
        log.info(
            "%s: %d/%d scored, F1=%.3f, exact-match %d/%d",
            version, results[version]["n_scored"], results[version]["n_attempted"],
            results[version]["f1"], results[version]["exact_match_documents"], results[version]["n_scored"],
        )

    if not results:
        log.error("No predictions files found -- run the document agent first (week4-krishna-doc-agent).")
        return 1

    baseline_path = next(p for v, p in PREDICTIONS_FILES.items() if v in results)
    baseline = score_null_baseline(baseline_path, documents_dir)

    raw = config.BENCHMARKS_RAW_DIR
    field_rows = []
    for version, r in results.items():
        t = r["field_table"].copy()
        t.insert(0, "prompt_version", version)
        field_rows.append(t)
    pd.concat(field_rows, ignore_index=True).to_csv(raw / "w4_doc_eval_field_accuracy.csv", index=False)

    summary = {
        version: {k: v for k, v in r.items() if k != "field_table"}
        for version, r in results.items()
    }
    summary["null_baseline"] = baseline
    (raw / "w4_doc_eval_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    docs.write_section(
        config.DOCS_DIR / "W4_lahari_beat_osrm.md",
        "doc-eval",
        render_doc(results, baseline),
    )
    log.info("Doc-eval tables -> %s, doc section doc-eval", raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
