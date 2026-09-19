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
| Document Intelligence | per-field accuracy, clean PDF | **98.7%** | predict nothing: 0.0% | 20 of 40 rows so far (quota), 10 consignments stratified by seeded error type | `doc_extraction/v2` | `gemini-3.6-flash` |
| Document Intelligence | per-field accuracy, noisy scan (Tesseract OCR) | **96.9%** | predict nothing: 0.0% | the same rows | `doc_extraction/v2` | `gemini-3.6-flash` |
| Document Intelligence | hallucinated fields (value returned where the document is blank) | **0.4%** (1 of 280) | | the same rows | `doc_extraction/v2` | `gemini-3.6-flash` |
| Order Entry | end-to-end success rate | **100%** (50 of 50) | always file: 50.0% | all 50 cases; 25 file, 25 clarify | `order_entry/v1` | `gemini-3.6-flash` |
| Order Entry | clarification recall / precision | **100% / 100%** | always file: 0% recall | the 25 clarify cases | `order_entry/v1` | `gemini-3.6-flash` |
| Order Entry | invented orders · needless questions | **0 · 0** | | 50 cases | `order_entry/v1` | `gemini-3.6-flash` |
| Tracking & Exception | notification precision, notify every alert | **58.6%** as-of (72.1% as first published — replay leak, D-054) | notify every leg in the replay: 54.1% | 1,720 alerts over the earliest 2,000 legs | verdict computed, no prompt | none (D-041) |
| Tracking & Exception | recall of all truly delayed legs | **93.1%** as-of | notify every leg: 100% | 1,082 delayed legs | — | none |
| Tracking & Exception | precision at critical only | **85.3%** as-of (91.8% published) | | 292 alerts | — | none |
| Tracking & Exception | time to notification, p50 / p95 | **60.3 s / 63.3 s** stream; agent decision 0.04 ms | | replay | — | none |
| Invoice Auditor | dispute precision / recall | **100% / 82.2%** | dispute everything: 75.0% / 100%; approve everything: 25% accuracy | 60 seeded invoices, 10 kinds | verdict computed, no prompt | none (D-041) |
| Invoice Auditor | right reason on disputes | **82.2%** | | 45 invoices that should be disputed | — | none |
| Orchestrator | lifecycles completed with no intervention | **10 of 10**, 0 errors | | 10 order emails: 5 clarify, 5 booked, 2 ticketed | `--no-llm` demonstration mode | none |
| Analytics Assistant | route correct / source correct | **93.3% / 86.7%** (with the model); 90.0% / 83.3% without | | fixed 30 questions | `analytics_assistant/v1` | `gemini-3.6-flash` |
| Analytics Assistant | refusal recall, both layers | **100%** (6 of 6): 4 by the distance gate, 2 by the model itself; precision 100% | refuse nothing: 0% recall | 6 out-of-scope questions of the 30 | `analytics_assistant/v1` | `gemini-3.6-flash` |
| Analytics Assistant | groundedness, model-written answers | **94.4%** (17 of 18), hand-judged | | 18 in-scope answers the model wrote; 6 provider-error fallbacks excluded (P-60) | `analytics_assistant/v1` | `gemini-3.6-flash` |

## What the numbers do and do not show

**Order Entry is complete at 50 of 50** (G-02 closed 2026-09-18). The case set is
balanced (25 file, 25 clarify), so "always file" is the honest floor at 50%, not zero. The
run spans five quota days (20 calls a day, D-032) and every case records the day it ran
on. A perfect score on templated email is a ceiling, not a verdict: D-040's reading, that
the next evaluation should be built from email the agent gets wrong, is unchanged.

**Extraction is at 20 of 40 rows, and OCR now costs what it should.** At 11 rows the noisy
scans scored *above* the clean PDFs (98.6% against 97.6%), which this table called a
sample-size artefact at the time. At 20 rows it reversed: clean 98.7%, noisy 96.9%. One
field in 280 was hallucinated — a value returned where the document is blank. The remaining
20 rows run on later quota days.

**The Exception Agent's numbers were inflated by the replay, and are re-stated as-of (D-054,
P-62).** The replay joined early legs to end-of-data history; scored with only what a live
system would have known, precision is **58.6%** against a 54.1% trivial policy — a gain of
4.5 points, not the 18 first reported. The agent makes no LLM decision (D-041), so this is a
correction to the *model's* input, not the agent's logic. **D-047's conclusion survives:**
precision still rises monotonically with severity — low 39.7%, medium 51.3%, high 76.6%,
critical 85.3% — so severity still works as a filter. `low` is now below the trivial policy,
which makes the case for notifying at `medium` and above stronger, not weaker.

**The Invoice Auditor misses one kind of problem completely.** All 8 `overcharge_hidden`
invoices were approved: freight 10% above the rate band, which sits inside the auditor's
15% tolerance, so a supplier can overcharge by up to 15% and pass (D-047). The case was
seeded to put a number on that tolerance. Every other kind is 100% right. Its rate band is the
corpus's own pricing model, so the recall figure is evidence about the rules, not about
real freight pricing (D-043).

**The Orchestrator row is wiring, not quality.** `--no-llm` takes the order from the case's
ground truth. It proves the lifecycle runs without a human between steps; the quality of
the one generated step is the Order Entry row.

**The Assistant's two refusal layers together refuse all six out-of-scope questions.** The
distance gate alone refused four (P-56: questions close to the project's topic retrieve
documents as near as real ones do). The two it let through — freight GST and Delhivery's
fleet size — the model refused in its own answer, naming what data would have been needed.

**Groundedness: 17 of 18 model-written answers**, judged by reading each against the
context it was given (`w7_groundedness_verdicts.csv`, one reason per answer). The one
failure is instructive: asked how many corridors are statistically slower (273), the model
counted the three slower corridors among its five retrieved passages and stated "3" as the
network's answer. Every number was in its context, which is exactly why the mechanical
pre-check passed it — the error was the generalisation, not a digit. Two more verdicts are
worth reading: D08 is faithful to its context but out of date, because retrieval returned
the superseded D-024 instead of D-048; and T03 answered **Hubli** where the question set
expected Aluva, and the model was right (P-61).

## Groundedness judging — method, fixed before the answers exist

For each model-phrased answer in `benchmarks/raw/w7_assistant_answers_llm.jsonl`:

- **grounded** if every number in the answer appears in its returned context, and no claim
  goes beyond that context;
- **refusal correct** if an out-of-scope question's answer begins with the refusal
  sentence (the prompt asks the model to follow it with what data would be needed), and an
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
| Tracking & Exception | `benchmarks/raw/w8_replay_leakage.json` (as-of, reported); `w6_exception_eval.json` (superseded); D-041, D-047, D-054, P-62 |
| Invoice Auditor | `benchmarks/raw/w6_invoice_eval.json`, `w6_invoice_eval_cases.csv`; D-043 |
| Orchestrator | `benchmarks/raw/w6_orchestrator_runs.json` |
| Analytics Assistant | `benchmarks/raw/w7_assistant_run_llm.json`, `w7_assistant_run_no_llm.json`, `w7_groundedness_verdicts.csv`, `w7_groundedness_summary.json`; P-56, P-60, P-61 |
