# W3 · Krishna — Synthetic document corpus

Week 3 deliverable (execution plan W3 D1-D5): the BOL + GST-invoice generator, its
noise augmentation, and a 100+-document labelled corpus — Gate 3's document half.

```bash
python -m src.agents.doc_corpus.generate            # 120 consignments, seed 42
```

Writes to `data/documents/` (gitignored, regenerate on demand — D-009's discipline).
Committed instead: `benchmarks/raw/w3_doc_corpus_manifest.csv` (every record) and five
curated pairs in `demo/sample_documents/` (GIT_RULES §3).

---

## 1. One record backs both documents, on purpose

W2's template research (`docs/W2_krishna_india_map.md` §4) landed on the point that
matters most for this week: a BOL and its invoice have to be generated **together**
from one consignment, because "an auditor agent's real job is cross-document
consistency ... a template set that generates the three independently would make that
job impossible to evaluate." `records.ConsignmentRecord` is that one shared object —
`templates.py` prints from it, `noise.py` rasterises the same field list
(`templates.field_rows`), and `labels.py` reads the ground truth back out of exactly
what got printed. Nothing about a document's content is decided twice, which is also
what makes `seed_errors.py`'s `corridor_mismatch` kind meaningful: it has to
deliberately break an agreement that would otherwise hold by construction.

## 2. What is real, and what is declared scaffolding

Corridor, both centre codes, both facility names, distance and the FTL/Carting split
come from `benchmarks/raw/w2_corridor_audit.csv` — the same 1,130 audited corridors
the India map reads. Every one of the 120 generated consignments draws a **distinct**
audited corridor (120 of 1,130, no repeats at this corpus size).

| Field | Source |
|---|---|
| Corridor, centre codes, facility names, distance | `w2_corridor_audit.csv` (real) |
| Route type (FTL / Carting) | Sampled per-corridor from its real `ftl_share` |
| Shipper / consignee names, GSTINs, vehicle numbers, amounts | Synthesised — do not exist anywhere in the Delhivery data |

The synthesised fields are declared as such the same way D-017 declares the mock
TMS scaffolding: GSTINs are shape-valid (state code + PAN-shaped body + entity digit,
`D-021`) but **not** checksum-valid, and must never be read as real. Vehicle numbers
use the standard RTO state letters with a random series. HSN/SAC `996791` (Goods
Transport Agency services) is the one code on the invoice that is a real, correct
public reference rather than a synthesised value.

## 3. Seeded-error taxonomy — functional now, open for Lahari's sign-off

The execution plan puts this design jointly with Lahari (W3 D3-D4, and W3 D5 "defines
the ground-truth label schema and seeded-error taxonomy ... with Sai Krishna"). This
session built and ran Krishna's half solo, so it is logged as **D-021, OPEN pending
Lahari's confirmation** — the same status D-014 carried until she confirmed it —
rather than presented as an already-agreed team decision.

Each record gets at most one error kind, independently, at a 15% target rate:

| Error kind | Count (of 120) | Extraction-prompt rule it exercises |
|---|---|---|
| `total_mismatch` | 5 | rule 5 — report the mismatch, do not reconcile it |
| `duplicate_document_number` | 4 | an operational error, not a corruption |
| `corridor_mismatch` | 2 | the cross-document consistency check from §1 |
| `ocr_confusable_corruption` | 6 | rule 6's own confusion classes (0/O, 1/I/l, 5/S, 8/B, 2/Z) |
| `missing_field` | 3 | rule 1 — return `null`, never invent |
| **Clean** | **100** | — |

20 of 120 documents (16.7%, close to the 15% target — the draw is random per record)
carry a deliberate error. A label is always **what is printed**, not the intended
clean value — `labels.py`'s docstring states this explicitly, because rule 5 above
only makes sense if the ground truth an extraction agent is scored against is the
printed number, corrupted or not.

## 4. Noise augmentation — no poppler dependency

The natural pipeline — render the PDF, rasterise it with `pdf2image` (`poppler`),
degrade the raster — needs a system binary none of the three machines this project
runs on has installed, the same class of problem D-012 already spent an afternoon on
for Spark. `noise.py` instead draws the same field list straight onto a Pillow canvas
and degrades that: small rotation, Gaussian pixel noise, a light blur, a
brightness/contrast jitter, and a random-quality JPEG re-encode. The clean PDF and the
noisy "scan" are two independent renderers over one shared field list rather than a
render-then-rasterise pipeline, so they cannot drift relative to each other — recorded
as P-26. `pdf2image` and `pytesseract` stay in `requirements.txt`, reserved for Week 4
when they will run OCR against these rasterised images for real.

## 5. Gate 3 numbers

| Result | Value |
|---|---|
| Consignments generated | **120** (Gate 3 asks 100+) |
| Documents (BOL + invoice pairs) | 240, each with a PDF, a ground-truth JSON label, and a noisy scan JPEG |
| Distinct audited corridors used | 120 of 1,130 |
| Route type split | 66 FTL / 54 Carting |
| Seeded-error rate | 20/120 (16.7%) across 5 kinds |
| Label schema | Exactly the 15 fields in `doc_extraction/v1.md` — asserted by `generate.py` and by `test_label_schema_matches_doc_extraction_prompt` |
| Curated demo samples | 5 pairs in `demo/sample_documents/` — 1 clean + 1 per error kind for 4 of the 5 kinds (`--demo-samples 5` is GIT_RULES §3's 5-10-example ceiling, one pair short of covering all five; `missing_field` is the one not represented) |
| Tests | 16 in `tests/test_doc_corpus.py`, all passing; `ruff` clean |

## 6. What's next

- **D-021 confirmed by Lahari (W3 D5).** One fix came out of the review —
  `total_mismatch` was printing a negative invoice total on the network's smallest
  Carting shipments (P-27) — applied in `seed_errors.py` and the corpus regenerated;
  every other record's assigned error kind is unchanged. Carried forward as a caveat
  rather than a blocker: `corridor_mismatch` landed on only 2 of 120 records, so
  Week 4's per-kind accuracy on it is a lead, not a result, at this corpus size.
- **Week 4** reads this corpus for real: `pytesseract` OCR over the noisy scans, then
  the Document Intelligence Agent's LLM extraction against `doc_extraction/v1.md`,
  scored field-by-field against `data/documents/*.json`. First agent-eval numbers land
  in `benchmarks/agent_evaluation.md`.
- **Dashboard screenshots** (`demo/screenshots/`) are still empty — carried from Week 2
  and now Week 3, owner unchanged.
