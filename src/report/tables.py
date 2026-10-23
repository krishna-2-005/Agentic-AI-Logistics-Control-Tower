"""The paper's final metric tables (execution plan v3.1 W8 D1-D2, Lahari).

    python -m src.report.tables          # writes benchmarks/final_tables.md

Two layers, one file, generated from `benchmarks/raw/`:

* **Layer 1** — the prediction problem: baselines, Week 4's models, the Week 7 correction,
  and the slice table the adoption decision rests on.
* **Layer 2** — the agent layer: five agents and the orchestrator, each with the trivial
  policy it has to beat.

Generated rather than written, for the reason `experiments_appendix.py` gives: a table of
numbers maintained by hand drifts from the numbers. Anything this module cannot read from
a cache file is printed as `—` with the file named, so a gap is visible rather than
plausible-looking.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.stats import wilson

log = get_logger("report.tables")

RAW = config.BENCHMARKS_RAW_DIR
OUT = config.BENCHMARKS_DIR / "final_tables.md"

#: Model key -> (display name, what it is). Order is the order of the table.
MODEL_ROWS = [
    ("OSRM", "OSRM plan", "the OSRM estimate recorded in the data, as a prediction"),
    ("v1_rf_raw_target", "Random Forest (W4)", "MLlib, squared loss, raw target — Week 4's reported model"),
    ("corridor_mean", "corridor mean", "past-only mean gap per corridor (D-023)"),
    ("corridor_median", "**corridor median**", "**the bar**: MAE is minimised by the median (D-048)"),
    ("v2_gbt_residual_absolute", "v2 GBT residual, step 0.05", "absolute loss on the median residual"),
    ("v2_gbt_residual_absolute_step1", "**v2 GBT residual, step 1.0**", "**the served model** (the stream and the API run it; D-050)"),
    ("histgbr_residual_reference", "sklearn HistGBR (v1.0 reference)", "single-node; now one of the zoo candidates (D-077)"),
]


def _json(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def layer1_upgrade() -> list[str]:
    """The upgrade pass's headline tables: the bar, the zoo with intervals, rolling origin, the audit variants."""
    b1 = _json("b1_backoff_baseline.json")
    zoo = _json("b6_model_zoo.json")
    sig = _json("b2_significance.json")["models"]
    v3 = _json("b1_model_v3.json")
    bar = b1["test_mae"]["backoff"]
    lines = ["## Layer 1 — the upgrade pass (D-075 to D-098)", "",
             ("The bar is a hierarchical **back-off median** (D-075): "
              f"{bar:.2f} min on the {b1['split']['test']:,} test legs, "
              f"against {b1['test_mae']['old_median']:.2f} for the old median, which predicted 0.0 minutes on a corridor with no history. "
              "Intervals are day-block bootstrap 95% (six India-time calendar days of test legs; D-076). "
              "The **reported model** is the candidate with the lowest validation MAE whatever its library (D-077); the **served** "
              "model is what the stream and the API run."), "",
             "| model | validation MAE | test MAE | test minus bar | 95% interval | comparisons won (of 14, Holm) |",
             "|---|---|---|---|---|---|"]

    def row(name: str, key: str, validation: float | None) -> str:
        m = sig[key]
        val = "—" if validation is None else f"{validation:.2f}"
        if key == "backoff":
            return f"| {name} | {val} | {m['own_mae']['mae']:.2f} | — | — | — |"
        over = m["vs_bar"]["overall"]
        delta = f"{over['delta_mae']:+.2f}"
        ci = f"[{over['ci_block_day'][0]:+.2f}, {over['ci_block_day'][1]:+.2f}]"
        won = str(m["summary"]["wins_after_holm_block"])
        return f"| {name} | {val} | {m['own_mae']['mae']:.2f} | {delta} | {ci} | {won} |"

    lines.append(row("old median (0.0 cold fallback)", "old_median", b1["validation_mae"]["old_median"]))
    lines.append(row("**hard back-off (the bar)**", "backoff", b1["validation_mae"]["backoff"]))
    lines.append(row("Spark GBT over the old median (**served**)", "v2_gbt", v3["validation_mae"]["v2_gbt_step1"]))
    lines.append(row("Spark GBT over back-off", "v3_gbt", v3["validation_mae"]["v3_gbt"]))
    names = {"lightgbm_l1": "LightGBM, L1", "lightgbm_huber": "LightGBM, Huber", "xgboost_l1": "XGBoost, L1",
             "histgbr_l1": "histogram GBT, L1", "quantile_linear": "linear median regression"}
    for key, label in names.items():
        stats = zoo["secondary"][key]
        star = "**" if key == "lightgbm_l1" else ""
        tag = " (**reported**)" if key == "lightgbm_l1" else ""
        lines.append(row(f"{star}{label}{star}{tag}, over the old median", f"{key}_oldbase", stats["validation_mae"]))
    for key, label in names.items():
        stats = zoo["primary"][key]
        lines.append(row(f"{label}, over back-off", key, stats["validation_mae"]))

    ro = _json("b2_rolling_origin.json")["summary"]
    rz = _json("b2_rolling_origin_zoo.json")["summary"]
    lines += ["", "### Rolling origin: four expanding windows (D-076, D-098)", "",
              "| | mean test MAE | mean minus bar | sd over folds | folds beating the bar |", "|---|---|---|---|---|",
              f"| back-off bar | {ro['mae_backoff']['mean']:.2f} | — | — | — |",
              f"| served (Spark over old median) | {ro['mae_v2_gbt']['mean']:.2f} | {ro['delta_v2_vs_backoff']['mean']:+.2f} | "
              f"{ro['delta_v2_vs_backoff']['sd']:.2f} | {ro['v2_gbt_beats_backoff_in_folds']} of 4 |",
              f"| Spark over back-off | {ro['mae_v3_gbt']['mean']:.2f} | {ro['delta_v3_vs_backoff']['mean']:+.2f} | "
              f"{ro['delta_v3_vs_backoff']['sd']:.2f} | {ro['v3_gbt_beats_backoff_in_folds']} of 4 |",
              f"| **reported (LightGBM, L1)** | {rz['mae_model']['mean']:.2f} | {rz['delta_vs_backoff']['mean']:+.2f} | "
              f"{rz['delta_vs_backoff']['sd']:.2f} | {rz['model_beats_backoff_in_folds']} of 4 |", ""]

    audit = _json("b3_audit_robust.json")["variants"]
    fine = _json("b3_audit_robust_1e6.json")["variants"]
    lines += ["### Corridor audit under dependence (D-080, D-084)", "",
              "| variant | slower | faster |", "|---|---|---|"]
    for key, label in (("bh_welch", "Welch, BH (the original audit)"), ("by_welch", "Welch, BY"),
                       ("bh_perm", "cell permutation, BH"), ("by_perm", "**cell permutation, BY (headline)**")):
        lines.append(f"| {label} | {audit[key]['significant_slower']} | {audit[key]['significant_faster']} |")
    lines += [f"| cell permutation, BY, 10^6 permutations | {fine['by_perm']['significant_slower']} | {fine['by_perm']['significant_faster']} |", ""]
    return lines


def layer1() -> list[str]:
    v2 = pd.read_csv(RAW / "w7_model_metrics_v2.csv")
    step = pd.read_csv(RAW / "w7_model_metrics_v2_stepsize.csv")
    overall = pd.concat([v2, step])
    overall = overall[overall["dimension"] == "overall"].drop_duplicates("model").set_index("model")["mae_min"]
    bar = float(overall.get("corridor_median", float("nan")))

    lines = ["## Layer 1 — predicting how late a leg runs", "",
             ("Test split: the last 20% of legs by creation time (D-022), 5,274 legs. "
             "Metric: mean absolute error in minutes (D-024)."), "",
             "| model | test MAE (min) | vs the bar | what it is |", "|---|---|---|---|"]
    for key, name, what in MODEL_ROWS:
        if key not in overall:
            lines.append(f"| {name} | — | — | {what} (not in `w7_model_metrics_v2*.csv`) |")
            continue
        mae = float(overall[key])
        delta = "—" if key == "corridor_median" else f"{mae - bar:+.2f}"
        lines.append(f"| {name} | **{mae:.2f}** | {delta} | {what} |")

    lines += ["", "### Where the served model wins, slice by slice (v1.0 slice table)", "",
              ("Every slice the adoption rule looks at, and the two it does not "
              "(distance, hour) — reported because a model that wins overall by losing "
              "somewhere should have to show it."), "",
              "| dimension | slice | legs | corridor median | served model | delta |",
              "|---|---|---|---|---|---|"]
    table = pd.read_csv(RAW / "w7_model_metrics_v2_stepsize.csv")
    median = table[table["model"] == "corridor_median"].set_index(["dimension", "slice"])
    model = table[table["model"] == "v2_gbt_residual_absolute_step1"].set_index(["dimension", "slice"])
    for idx in model.index:
        if idx[0] == "overall":
            continue
        m, v = float(median.loc[idx, "mae_min"]), float(model.loc[idx, "mae_min"])
        lines.append(f"| {idx[0].replace('_', ' ')} | {idx[1]} | {int(median.loc[idx, 'n']):,} | "
                     f"{m:.2f} | {v:.2f} | **{v - m:+.2f}** |")

    report = _json("w7_model_v2_stepsize_report.json")
    validation = report["validation"]
    lines += ["", "### How the served model's step size was selected", "",
              ("`stepSize` was chosen on a chronological validation cut of the training "
              "split and scored once on test, fixed in D-049 before it ran."), "",
              "| stepSize | max correction (min) | validation MAE | ",
              "|---|---|---|",
              f"| corridor median | — | **{validation['corridor_median_mae_min']:.2f}** |"]
    for step_size, mae in validation["mae_min_by_step_size"].items():
        cap = validation["correction_cap_min_by_step_size"][step_size]
        chosen = " ← chosen" if float(step_size) == validation["chosen_step_size"] else ""
        lines.append(f"| {step_size}{chosen} | {cap} | {mae:.2f} |")
    lines += ["",
              ("**Read this table before the one above it.** On validation every step size "
              "loses to the median; on test the chosen one wins by 6.5% against the old median "
              "(4.6% against the back-off bar, D-075). The rule was applied as written rather than "
              "re-opened once the test score was known."), ""]
    return lines


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def layer2() -> list[str]:
    lines = ["## Layer 2 — the agents", "",
             ("Each row names the set it was scored on and the trivial policy on that same "
             "set. Full method and caveats: `benchmarks/agent_evaluation.md`."), "",
             "| agent | metric | value | trivial policy | set |", "|---|---|---|---|---|"]

    doc = _json("w7_doc_extraction_eval.json")
    rows_scored = doc["documents_evaluated"]
    # One overall number with its n and interval leads (the clean and noisy rows are splits of
    # it, not alternative headlines): clean-only used to be quoted alone as 98.7% (UPGRADE A2).
    overall = wilson(doc["overall"]["correct"], doc["overall"]["fields_in_truth"])
    lines += [
        (f"| Document extraction | per-field accuracy, overall (clean + noisy) | "
         f"**{overall.point:.1%}** [{overall.lower:.1%}–{overall.upper:.1%}] "
         f"| predict nothing: 0.0% | {doc['overall']['correct']} of {doc['overall']['fields_in_truth']} fields, "
         f"{rows_scored} of {doc['rows_planned']} rows |"),
        (f"| Document extraction | per-field accuracy, clean PDF (split) | **{_pct(doc['by_split']['clean']['accuracy'])}** "
        f"| predict nothing: 0.0% | {doc['by_split']['clean']['correct']} of "
        f"{doc['by_split']['clean']['fields_in_truth']} fields |"),
        (f"| Document extraction | per-field accuracy, noisy scan (split) | **{_pct(doc['by_split']['noisy']['accuracy'])}** "
        f"| predict nothing: 0.0% | {doc['by_split']['noisy']['correct']} of "
        f"{doc['by_split']['noisy']['fields_in_truth']} fields |"),
        (f"| Document extraction | hallucinated fields | **{_pct(doc['overall']['hallucination_rate'])}** "
        f"| — | {doc['overall']['fields_in_truth']} fields |"),
    ]

    order = _json("w5_order_eval_summary.json")
    file_share = 1 - order["expected_clarification_rate"]
    lines += [
        (f"| Order entry | end-to-end success | **{_pct(order['success_rate'])}** "
        f"| always file: {_pct(file_share)} | {order['n_run']} of {order['n_cases']} cases |"),
        (f"| Order entry | clarification recall / precision | **{_pct(order['clarify_recall'])} / "
        f"{_pct(order['clarify_precision'])}** | always file: 0% recall | the clarify cases |"),
        (f"| Order entry | invented orders · needless questions | **{order['invented_orders']} · "
        f"{order['needless_questions']}** | — | {order['n_run']} cases |"),
    ]

    # As-of, not the replay's first measurement: the replay scored early legs with
    # end-of-data history and inflated precision by 13.5 points (D-054, P-62). Latency is
    # unaffected by that, so it still comes from the original evaluation.
    exc = _json("w6_exception_eval.json")
    leak = _json("w8_replay_leakage.json")["exception_agent_as_of"]
    base = exc["legs_truly_delayed"] / exc["legs_in_replay"]
    critical = next(r for r in leak["by_severity"] if r["severity"] == "critical")
    lines += [
        (f"| Tracking & exception | notification precision (as-of) | **{_pct(leak['notification_precision'])}** "
         f"(first published {_pct(exc['notification_precision'])}, D-054) "
         f"| alert every leg: {_pct(base)} | {leak['alerts_scored']:,} alerts |"),
        (f"| Tracking & exception | precision at critical (as-of) | **{_pct(critical['precision'])}** "
         f"| alert every leg: {_pct(base)} | {critical['notified']:,} alerts |"),
        (f"| Tracking & exception | event-to-alert p50 / p95 | **{exc['time_to_notification_s']['stream_p50']:.1f} s / "
         f"{exc['time_to_notification_s']['stream_p95']:.1f} s** | — | replay |"),
    ]

    inv = _json("w6_invoice_eval.json")
    dispute_share = sum(k["n"] for k in inv["by_kind"] if k["expected"] == "dispute") / inv["cases"]
    lines += [
        (f"| Invoice auditor | dispute precision / recall | **{_pct(inv['precision'])} / {_pct(inv['recall'])}** "
        f"| dispute everything: {_pct(dispute_share)} / 100% | {inv['cases']} invoices |"),
        (f"| Invoice auditor | right reason on disputes | **{_pct(inv['right_reason'])}** | — | "
        f"{int(dispute_share * inv['cases'])} invoices that should be disputed |"),
    ]

    orch = _json("w6_orchestrator_runs.json")
    lines.append(f"| Orchestrator | lifecycles with no human step | **{orch['cases'] - orch['errors']} of "
                 f"{orch['cases']}** | — | {orch['booked']} booked, {orch['ticketed']} ticketed |")

    assistant = _json("w7_assistant_run_llm.json")
    grounded = _json("w7_groundedness_summary.json")
    lines += [
        (f"| Analytics assistant | correct route / source | **{_pct(assistant['route_accuracy'])} / "
         f"{_pct(assistant['source_accuracy'])}** | — | {assistant['answered']} fixed questions |"),
        (f"| Analytics assistant | refusal recall, both layers | "
         f"**{_pct(assistant['refusal_recall_both_layers'])}** (gate alone {_pct(assistant['refusal_recall'])}) "
         f"| refuse nothing: 0% | 6 out-of-scope questions |"),
        (f"| Analytics assistant | groundedness, model-written | **{_pct(grounded['groundedness_rate_model_written'])}** "
         f"({grounded['model_written_in_scope'] - grounded['not_grounded']} of {grounded['model_written_in_scope']}), "
         f"hand-judged | — | {grounded['extractive_fallbacks']} provider-error fallbacks excluded |"),
    ]
    lines.append("")
    return lines


def run(out: Path = OUT) -> Path:
    lines = ["# Final metric tables", "",
             "**Owner: Lahari.** Generated by `python -m src.report.tables`; do not edit by hand.",
             "", (f"Generated {datetime.now(UTC).date().isoformat()}. Every value is read from a "
             "file in `benchmarks/raw/`; `benchmarks/experiments_appendix.md` maps each one to the "
             "command that writes it."), ""]
    lines += layer1_upgrade()
    lines += layer1()
    lines += layer2()
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s", out)
    return out


if __name__ == "__main__":
    print(run())
