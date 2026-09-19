# doc_extraction prompts

Bill of lading and invoice scans (Week 3's corpus, D-021) into the fifteen-field dict
`src/ml/eval_extraction.py` scores. One model call per document; the OCR text goes in,
bare JSON comes out.

| version | landed | what changed | measured |
|---|---|---|---|
| `v1` | W4 D1-D2 | first version: field list, null rules, "return bare JSON" | field F1 **0.853** on 22 documents |
| `v2` | W4 D3-D4 | stricter null handling and an explicit rule against inferring a field from another field | field F1 **0.929** on 16 documents; **98.0%** per-field on the G-01 subsample |

Versions are never edited in place (GIT_RULES §1): a score names the version it was
produced by, and an edited prompt would silently invalidate every earlier number.

**What v2 still gets wrong**, from `benchmarks/raw/w7_doc_extraction_eval.json`: the
invoice's `origin_facility` and `destination_facility` (80% each) — facility names on the
invoice layout sit next to the centre codes, and the model sometimes returns the code as
the name. That is the field a v3 should target, and it is the one worth measuring twice
before changing, because the fix is a wording change that could cost the codes.
