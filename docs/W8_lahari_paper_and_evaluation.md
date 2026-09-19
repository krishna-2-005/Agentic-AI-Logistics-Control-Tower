# W8 · Lahari — the paper, the final tables, groundedness, and a leak in our own evaluation

```bash
python -m src.report.tables                       # both metric tables, from the cache files
python -m src.ml.groundedness --precheck --report # the assistant's groundedness judging
python -m src.ml.replay_leakage --legs 2000       # the replay leak, measured
python -m src.ml.stream_validation --adopted      # stream-equals-batch for the reported model
```

## 1. The paper

`docs/paper_outline.md` sets eight claims, each with its evidence file and figure, a
related-work table, and five things the paper must not claim. `docs/paper_skeleton.md` is the
methodology and results scaffold with every number carrying its source.
**`docs/paper_draft.md` is a full first draft** for ICCCI 2027 (D-052): the corridor audit
leads, the support-floor instability is a result rather than a limitation paragraph, and the
two evaluation traps in this project are reported as findings.

The related-work search turned up one useful surprise: Uber's DeepETA uses our exact
formulation — a residual over a routing engine's estimate, an absolute-error-family loss,
MAE reported — arrived at independently. It also found **no peer-reviewed paper on this
dataset**, which the draft states as a fact about our search rather than about the world.

## 2. Final metric tables

`benchmarks/final_tables.md` is generated, not typed: Layer 1 (every baseline, both Week 7
candidates, the single-node ceiling, the full slice table and the validation grid) and Layer 2
(five agents and the orchestrator, each beside the trivial policy on its own set).

## 3. Stream-equals-batch on the reported model

**500 of 500 identical**, maximum difference 0. The first run sampled the earliest 500 legs,
where 484 corridors have no history — so the baseline was zero on 97% of rows and the run
tested the correction alone while reporting both halves. Sampling across the timeline brings
cold rows to 57 of 500. The summary records `served_by_the_streaming_job: false`, because the
stream does not serve this model yet (D-053).

## 4. Groundedness judging

Each of the assistant's 30 answers was checked mechanically — every number against a context
rebuilt from the same index — and then read against that context, with a one-line reason per
verdict (`w7_groundedness_verdicts.csv`). **17 of 18 model-written answers are grounded**;
all six out-of-scope questions were refused.

The mechanical check found nothing. Reading found the one failure: asked how many corridors
are statistically slower, the model counted the three among its five retrieved passages and
answered "3" where the network's answer is 273 — every digit in context, the claim not. And
reading found the answer that looked wrong and was right: Hubli, not Aluva, for the longest
dwell *time* (P-61).

Six answers were provider errors recorded as extractive fallbacks (P-60). They are counted
apart, not credited to the model.

## 5. The leak in our own evaluation (D-054, P-62)

Reading the streaming job's history join for Mounika's D-053 raised a question nobody had
asked: on a replay, "latest history" means the end of the data. The replay the Exception agent
was evaluated on took the **earliest** 2,000 legs, and 1,290 of them had no corridor history
at their own creation time — but were scored as if they had fourteen prior legs.

Scoring the same legs twice with the served model, the snapshot side reproduced the published
evaluation **exactly**, which made the rest certain:

| | first published | as-of |
|---|---|---|
| notification precision | 72.1% | **58.6%** |
| by severity (low/medium/high/critical) | 53.2 / 68.6 / 85.1 / 91.8% | **39.7 / 51.3 / 76.6 / 85.3%** |
| trivial policy | 54.1% | 54.1% |

D-047's conclusion survives — precision still rises with every grade — at a gain of 4.5 points
over the trivial policy, not 18. The Week 6 write-up and D-047 carry a note pointing forward
instead of being rewritten, and every current document, table and figure uses the as-of
numbers. No Layer 1 result is affected: the batch path is strictly as-of.

The stream-equals-batch test could not have caught this. Both of its paths read the same
feature row, so it proved the event format lossless — never that the running job's history
was the history of the moment.

## 6. Carried into Phase 3

- Serving the reported model needs event-time windows in the stream (D-053).
- A live-deployment measurement of alert precision, where "latest history" is the truth.
- Extraction rows 21-40 and one prompt iteration (quota).

Decisions: D-054. Problems: P-62.
