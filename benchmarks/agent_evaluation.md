# Agent evaluation

**Owner: Lahari** (deliberately not Krishna, who builds the agents — execution plan §4
keeps builder and judge separate). Populated Weeks 4-7.

## Status: Week 4 D5 done (the first number)

Source: `python -m src.ml.doc_eval` → `docs/W4_lahari_beat_osrm.md` (doc-eval section),
`benchmarks/raw/w4_doc_eval_field_accuracy.csv`, `w4_doc_eval_summary.json`. Scored
against Krishna's predictions files (`week4-krishna-doc-agent`) and the Week 3
labelled corpus — D-028 has the full method (micro-averaged P/R/F1, why a
correctly-returned null is neither a hit nor a miss) and its own gap (no
regex-on-raw-OCR baseline is computable — `document_agent` does not persist OCR
text).

| Agent | Metric | Value | Prompt version | Test set | LLM |
|---|---|---|---|---|---|
| Document Intelligence | field-level F1 (micro) | **0.853** | `doc_extraction/v1` | 22 of 40 documents (D-032 quota cap) | `gemini-3.6-flash` |
| Document Intelligence | field-level F1 (micro) | **0.929** | `doc_extraction/v2` | 16 of 20 documents (D-032 quota cap) | `gemini-3.6-flash` |
| Document Intelligence | null baseline (predict nothing) | 0.000 F1 | — | same documents as v1 | — |
| Document Intelligence | character error rate post-OCR | _not measured_ — no reference transcript exists to diff against, only the field-level label | | |
| Order Entry | end-to-end success rate | _pending W5_ | | 50-case set |
| Order Entry | clarification-instead-of-guess rate | _pending W5_ | | ambiguous subset |
| Tracking & Exception | notification precision | _pending W6_ | | replay |
| Tracking & Exception | time-to-notification | _pending W6_ | | replay |
| Invoice Auditor | precision / recall | _pending W6_ | | seeded-error set |
| Analytics Assistant | groundedness | _pending W7_ | | fixed 30 questions |
| Orchestrator | lifecycle completion without intervention | _pending W6_ | | |

## Recording rules

- **Always record the prompt version** (`doc_extraction/v2`, …). A score without one is
  not reproducible, and D-008 exists precisely so the comparison stays possible.
- Record the LLM provider and model with every number — free-tier models change
  underneath you, and a score from `gemini-2.0-flash` is not a score from a local 8B.
- Report the trivial baseline beside every metric: for extraction, what a
  regex-only extractor scores; for the auditor, what "approve everything" scores.
- Groundedness is human-judged on a fixed question set (Lahari + Krishna, W7 D5).
  Record the questions, not just the aggregate.
