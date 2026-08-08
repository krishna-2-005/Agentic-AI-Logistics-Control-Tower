# Agent evaluation

**Owner: Lahari** (deliberately not Krishna, who builds the agents — execution plan §4
keeps builder and judge separate). Populated Weeks 4-7.

## Status: awaiting Week 4

| Agent | Metric | Value | Prompt version | Test set |
|---|---|---|---|---|
| Document Intelligence | field-level accuracy / F1 | _pending W4_ | | labelled synthetic corpus |
| Document Intelligence | character error rate post-OCR | _pending W4_ | | |
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
