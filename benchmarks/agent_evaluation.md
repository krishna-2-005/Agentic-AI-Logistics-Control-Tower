# Agent evaluation

**Owner: Lahari** (deliberately not Krishna, who builds the agents — execution plan §4
keeps builder and judge separate). Consolidated in Week 7 (execution plan v3.1 W7 D5).

Every row names its test set, its prompt version, the model, and the trivial policy it
has to beat. Numbers are read from the files under **Evidence**; where a figure is still
owed, the row says what it waits on instead of carrying an old number forward.

## The table

| Agent | Metric | Value | Trivial policy on the same set | Test set | Prompt | LLM |
|---|---|---|---|---|---|---|
| Document Intelligence | field-level F1 (micro) | **0.929** | predict nothing: 0.000 | 16 of 20 scanned documents (W4, quota cap) | `doc_extraction/v2` | `gemini-3.6-flash` |
| Document Intelligence | field-level F1 (micro), v1 | 0.853 | predict nothing: 0.000 | 22 of 40 scanned documents | `doc_extraction/v1` | `gemini-3.6-flash` |
| Document Intelligence | per-field accuracy, clean PDF | **97.6%** | predict nothing: 0.0% | 11 of 40 rows so far (quota), 10 consignments stratified by seeded error type | `doc_extraction/v2` | `gemini-3.6-flash` |
| Document Intelligence | per-field accuracy, noisy scan (Tesseract OCR) | **98.6%** | predict nothing: 0.0% | the same rows | `doc_extraction/v2` | `gemini-3.6-flash` |
| Document Intelligence | hallucinated fields (value returned where the document is blank) | **0.0%** (0 of 153) | | the same rows | `doc_extraction/v2` | `gemini-3.6-flash` |
| Order Entry | end-to-end success rate | **100%** (50 of 50) | always file: 50.0% | all 50 cases; 25 file, 25 clarify | `order_entry/v1` | `gemini-3.6-flash` |
| Order Entry | clarification recall / precision | **100% / 100%** | always file: 0% recall | the 25 clarify cases | `order_entry/v1` | `gemini-3.6-flash` |
| Order Entry | invented orders · needless questions | **0 · 0** | | 50 cases | `order_entry/v1` | `gemini-3.6-flash` |
| Tracking & Exception | notification precision, notify every alert | **72.1%** | notify every leg in the replay: 54.1% | 1,347 alerts over a 2,000-leg replay | verdict computed, no prompt | none (D-041) |
| Tracking & Exception | recall of all truly delayed legs | **89.7%** | notify every leg: 100% | 1,082 delayed legs | — | none |
| Tracking & Exception | precision at critical only | **91.8%**, recall 25.0% | | 294 alerts | — | none |
| Tracking & Exception | time to notification, p50 / p95 | **60.3 s / 63.3 s** stream; agent decision 0.04 ms | | replay | — | none |
| Invoice Auditor | dispute precision / recall | **100% / 82.2%** | dispute everything: 75.0% / 100%; approve everything: 25% accuracy | 60 seeded invoices, 10 kinds | verdict computed, no prompt | none (D-041) |
| Invoice Auditor | right reason on disputes | **82.2%** | | 45 invoices that should be disputed | — | none |
| Orchestrator | lifecycles completed with no intervention | **10 of 10**, 0 errors | | 10 order emails: 5 clarify, 5 booked, 2 ticketed | `--no-llm` demonstration mode | none |
| Analytics Assistant | route correct / source correct | **90.0% / 83.3%** | | fixed 30 questions | extractive, no model | none |
| Analytics Assistant | refusal precision / recall | **100% / 50%** | refuse nothing: 0% recall | 6 out-of-scope questions of the 30 | extractive, no model | none |
| Analytics Assistant | groundedness | _owed — judged by hand on the model-phrased run_ | | fixed 30 questions | `analytics_assistant/v1` | `gemini-3.6-flash` |

## What the numbers do and do not show

**Order Entry is complete at 50 of 50** (G-02 closed 2026-09-18). The case set is
balanced (25 file, 25 clarify), so "always file" is the honest floor at 50%, not zero. The
run spans five quota days (20 calls a day, D-032) and every case records the day it ran
on. A perfect score on templated email is a ceiling, not a verdict: D-040's reading, that
the next evaluation should be built from email the agent gets wrong, is unchanged.

**The extraction rows are 11 of 40 and OCR looks free, which is the part to distrust.**
Noisy scans scoring *above* clean PDFs (98.6% against 97.6%) is a sample-size artefact, not
a finding: one field's difference across 11 rows moves it either way. The number worth
carrying is the zero hallucination rate and the two facility fields at 80%. The remaining 29
rows run on later quota days.

**The Exception Agent's precision comes from the model, and its severity from the audit.**
It makes no LLM decision (D-041); the notification text is the only generated part. Across
severity grades, precision rises monotonically: low 53.2%, medium 68.6%, high 85.1%,
critical 91.8%. That is D-047's evidence that severity works as a filter, and the policy
table in `w6_exception_eval.json` gives the precision/recall trade for each cut-off.

**The Invoice Auditor misses one kind of problem completely.** All 8 `overcharge_hidden`
invoices were approved: freight 10% above the rate band, which sits inside the auditor's
15% tolerance, so a supplier can overcharge by up to 15% and pass (D-047). The case was
seeded to put a number on that tolerance. Every other kind is 100% right. Its rate band is the
corpus's own pricing model, so the recall figure is evidence about the rules, not about
real freight pricing (D-043).

**The Orchestrator row is wiring, not quality.** `--no-llm` takes the order from the case's
ground truth. It proves the lifecycle runs without a human between steps; the quality of
the one generated step is the Order Entry row.

**The Assistant's refusal recall is 50% on the distance check alone.** The three misses
are questions close to the project's topic, such as fleet size and freight tax. Their
nearest documents are as close as those for real questions (P-56). The second refusal
layer, the prompt's own rule, is measured by the model-phrased run, and so is
groundedness. Both rows stay owed until that run exists.

## Groundedness judging — method, fixed before the answers exist

For each model-phrased answer in `benchmarks/raw/w7_assistant_answers_llm.jsonl`:

- **grounded** if every number in the answer appears in its returned context, and no claim
  goes beyond that context;
- **refusal correct** if an out-of-scope question gets the exact refusal sentence, and an
  in-scope one does not;
- judged by Lahari, not by the assistant's own scoring script (D-028), with the verdict and
  a one-line reason recorded per question, not only the total.

## Recording rules

- **Always record the prompt version** (`doc_extraction/v2`, …). A score without one is
  not reproducible, and D-008 exists precisely so the comparison stays possible.
- Record the LLM provider and model with every number — free-tier models change
  underneath you, and a score from `gemini-2.0-flash` is not a score from a local 8B.
- Report the trivial policy beside every metric, computed on the same set.
- Groundedness is human-judged on a fixed question set. Record the questions, not just
  the aggregate.

## Evidence

| Row | Files |
|---|---|
| Document Intelligence | `benchmarks/raw/w4_doc_eval_summary.json`, `w4_doc_eval_field_accuracy.csv`; D-028 |
| Order Entry | `benchmarks/raw/w5_order_eval_summary.json`, `w5_order_eval_runs.jsonl`, `w5_order_eval_set.json` |
| Tracking & Exception | `benchmarks/raw/w6_exception_eval.json`, `w6_exception_eval_cases.csv`; D-041, D-047 |
| Invoice Auditor | `benchmarks/raw/w6_invoice_eval.json`, `w6_invoice_eval_cases.csv`; D-043 |
| Orchestrator | `benchmarks/raw/w6_orchestrator_runs.json` |
| Analytics Assistant | `benchmarks/raw/w7_assistant_run_no_llm.json`, `w7_assistant_questions_v1.json`; P-56 (branch `week7-krishna-rag-assistant`) |
