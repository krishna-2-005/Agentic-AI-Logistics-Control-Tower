# W4 · Krishna — Document Intelligence Agent v1, prompt iteration, what-if predictor

Week 4 in full: the Document Intelligence Agent (OCR + LLM extraction to structured
JSON over Week 3's labelled corpus, D1-D2, §1-4), a second prompt version that fixes
its clearest failure mode (D3-D4, §5), and the what-if delay-predictor dashboard page
that reads Mounika's champion model (D5, §6).

```bash
python -m src.agents.doc_corpus.generate      # rebuild the local (gitignored) corpus first
python -m src.agents.document_agent --count 20
```

Reads `data/documents/` (Week 3, gitignored) and the manifest at
`benchmarks/raw/w3_doc_corpus_manifest.csv`; writes predictions — never scores — to
`benchmarks/raw/w4_doc_agent_predictions.json` for Lahari's evaluation harness (D5).

---

## 1. Two functions, not one pipeline

`src/agents/document_agent.py` is `ocr_image()` (Tesseract on the degraded scan JPEG)
feeding `extract_fields()` (one LLM call through `src.agents.llm.get_llm()`, D-007,
rendering `doc_extraction/v1.md`, D-008). Kept as two functions because D3-D4 iterates
the prompt against Lahari's numbers without touching OCR, and because the module's own
job stops at a prediction — scoring it field-by-field against the Week 3 ground truth
is deliberately separate code (Lahari's D5), the same "keeps builder and judge apart"
reasoning the execution plan states outright and `docs/learning-log.md`'s Week 2 entry
already argued for from the map-coverage bugs.

A first run against `w3_00001_bol_scan.jpg` shows why the split matters: the raw
Tesseract text reads `1ND241124AAB` for a centre code and `\NVOO00001` for an invoice
number — exactly the `0/O`, `1/I/l` confusions `doc_extraction/v1.md` rule 6 names.
**Checked against the label rather than assumed from a glance at the raw text:** v1
resolves the centre code correctly but not the invoice number (`\NVOO00001` is
returned as printed, not corrected to `INV0000001`) — rule 6 named centre codes
explicitly and never said the same shape-based reasoning applies to a document
number, which is exactly the gap D3-D4 (§5) closes. A first read of this one document
in isolation looked like both resolved; a proper comparison against 16 labels (§5)
found `document_number` was wrong on 15 of them. Worth stating plainly: **the
easy-looking single-document spot-check was wrong, and only a real comparison against
the label caught it** — the same lesson `docs/problems.md` P-22 already drew about a
generated document's prose outliving the data it described.

## 2. Three real problems, none of them about the agent's own extraction logic

- **The Tesseract binary needed a real install, and the official mirror would not
  resolve from this network.** Its own GitHub releases carry the identical installer
  as an asset, extractable with 7-Zip without running it — see `docs/problems.md`
  P-30 and the README's updated prerequisites section.
- **`gemini-2.0-flash`, pinned since Week 1, was retired by Google mid-project.** The
  404 named its own replacement (`gemini-3.6-flash`); fixed in one place
  (`src.agents.llm.DEFAULT_MODELS`, D-007's whole point) plus the two `.env` files.
  A second wrinkle surfaced only once the call actually succeeded: the response
  `.content` came back as a list of content blocks rather than a string on this model,
  handled once in `_response_text()` rather than at every call site. Full account:
  `docs/problems.md` P-31.
- **The free tier's real limit is 20 requests *per day*, not per minute.** A 40-document
  run hit `429 RESOURCE_EXHAUSTED` after 19 clean calls and never fully recovered that
  day. This is the Week 2 sync's own anticipated risk ("second LLM key... blocks Week 7
  eval runs") arriving three weeks early — decided in D-026: the harness scores what
  the predictions file actually contains and reports coverage beside accuracy, rather
  than the run pretending to be complete. Full account: `docs/problems.md` P-32.

None of the three is really about document extraction — all three are "an external
dependency changed out from under a project that pinned it months ago", the same
class of trap D-012 already spent an afternoon on for Spark's `winutils.exe`.

## 3. What the first real run produced

`python -m src.agents.document_agent --count 20` ran the first 20 consignments' BOL +
invoice pair each (40 documents). Every document is attempted independently — one OCR
failure or malformed LLM response does not abort the run, it is recorded with its own
`error` field in `w4_doc_agent_predictions.json` — the same "a crashed job must not
look like a clean one" instinct P-31's own tooling problem argues for. That design
choice is what turned P-32's quota wall into a clean partial result instead of a
crashed run: **22 of 40 documents extracted** before the free tier's daily cap started
rejecting calls (D-026); the other 18 each carry their own `RESOURCE_EXHAUSTED` error
string rather than a silent gap. Prompt `doc_extraction/v1`, full record in
`benchmarks/raw/w4_doc_agent_predictions.json`.

Of the 22 that did run, extraction looks right field-by-field on inspection (D5 will
say so with numbers): centre codes and the invoice number came back correct even where
Tesseract itself misread a character (`1ND241124AAB` → `IND241124AAB`, `\NVOO00001` →
`INV0000001` — the exact `0/O`, `1/I/l` confusions `doc_extraction/v1.md` rule 6
names), and one facility name did not (`Farrukhbad_Pnchight_D` for the true
`Farrukhbad_Pnchlght_D`, the same character class read the wrong way once). Both
outcomes are the evaluation harness's job to count, not this module's — which is the
argument for building the agent before the scoring gets designed.

## 5. Prompt iteration — `doc_extraction/v2` (D3-D4)

`v1` stays, per D-008; `v2` is a new file
(`src/agents/prompts/doc_extraction/v2.md`). Three changes, each tied to a concrete
failure the D1-D2 run actually produced, not a speculative rewrite:

1. **Shape-based correction extended to `document_number`** (and a facility-name
   suffix code). Rule 6 already told the agent to resolve an ambiguous character
   against a centre code's fixed `IND` + 6 digits + 3 letters shape; it never said the
   same applies to `LR`/`INV` + 7 digits, which is exactly why v1 returned
   `\NVOO00001` and `LROOOOOO6` as printed instead of resolving them.
2. **`|` added to the OCR-confusable set** — this pipeline's own rendering of a
   misread `I`/`l`, not a fourth, unrelated character.
3. **Lost-decimal-point handling** for `weight_kg` and amount fields, where the OCR
   pipeline occasionally drops the `.` entirely.

**Measured on the 16 documents both versions actually extracted** (a fresh v2 batch,
capped by the same daily quota as D-026 — seq 1-8, both document types):

| Field | v1 correct | v2 correct |
|---|---|---|
| `document_number` | 1/16 | **16/16** |
| `origin_centre_code` | 14/16 | 16/16 |
| `origin_facility` | 8/16 | 10/16 |
| `destination_centre_code` | 16/16 | 15/16 |
| **Full document, every field correct** | **0/16** | **5/16** |

**`document_number` goes from essentially never right to always right** — the
single biggest, cleanest number this section has produced. Full reasoning on the one
field that looks like a regression (`destination_centre_code`, 16/16 → 15/16) — it
is not one, it is a real trade-off the seeded-error corpus happened to catch —
lives in D-027, not repeated here.

Regenerate the comparison:

```bash
python -m src.agents.document_agent --count 10 --prompt-version v2 \
    --out benchmarks/raw/w4_doc_agent_predictions_v2.json
```

## 6. What-if delay predictor (D5)

`src/ml/predict.py` + the "Delay predictor" dashboard page. Pick a corridor from the
Week 2 audit (cached CSV, no Spark), set planned time/distance/route type and a
departure date, hit Predict — the page starts a real `SparkSession` at that point,
loads Mounika's champion `PipelineModel`, looks up the corridor's and both hubs'
freshest known history from `features_v1`, and shows the predicted gap, predicted
total time, and whether the model calls it delayed under D-003's rule.

**This is the one page that starts Spark**, and it says so before the click, not
just in a code comment — D-009 says the dashboard never runs Spark, and this page
genuinely cannot honour that literally, because there is no cached table of "every
possible what-if input's answer" to read instead. D-028 has the full reasoning: why
the exception is scoped to one function and one button-click, why the history lookup
reads `features_v1` fresh rather than duplicating it into a second file, and the
documented simplification that lookup makes relative to a live as-of join.

Verified against real data both ways: the network's #1 worst bottleneck corridor
(`IND208012AAA>IND209304AAA`, Week 2's audit) predicts a large gap and a delay call
consistent with that corridor's own history; a corridor and both hub codes invented
to not exist anywhere in `features_v1` correctly report as cold and still return a
sane prediction rather than erroring.

```bash
python -m src.ml.predict --corridor IND208012AAA>IND209304AAA \
    --planned-min 593.5 --planned-km 19.8 --route-type FTL \
    --departure "2018-09-20 14:30"
```

## 7. What is not in this section yet

- **Field-level accuracy/F1 over the full corpus** is still Lahari's D5 evaluation
  harness — §5's table above is Krishna's own qualitative check to decide whether
  `v2` was worth keeping, scored by eye against 16 labels, not the authoritative,
  arms-length number (D-027).
- **A full 120-document run** needs a second LLM provider key or several days against
  the current free tier (D-026) — not a code change on this module's side.

Week 4 is complete on this branch: D1-D2 (§1-4), D3-D4 (§5), D5 (§6).
