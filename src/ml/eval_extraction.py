"""
Field-level evaluation of the Document Intelligence Agent (execution plan v3.1, G-01).

Closes the Week 4 gate half that was reported only partially: Week 4's
`src/ml/doc_eval.py` scored 22 and 16 documents with no clean/noisy split and no
hallucination rate. This adds both, over a stratified subsample of the corpus.

Place at:  src/ml/eval_extraction.py
Run as:    python -m src.ml.eval_extraction --consignments 5              # smoke run
           python -m src.ml.eval_extraction --consignments 20             # the G-01 subsample
           python -m src.ml.eval_extraction --consignments 20 --cache-only  # score, no LLM calls
           python -m src.ml.eval_extraction --split noisy --prompt-version v2

Writes:    benchmarks/raw/w7_doc_extraction_eval.json   (full per-field detail)
           benchmarks/raw/w7_doc_extraction_summary.csv (the table for the paper)
           benchmarks/raw/w7_doc_extraction_cache.jsonl (every extraction, keyed)

How this corpus maps onto the template
--------------------------------------
* **Two document types, one schema.** The corpus (Week 3, D-021) is 120 consignments,
  each with a BOL and an INVOICE carrying the same fifteen fields; there are no POD
  documents and no line items, so FIELD_SPEC below has two entries, not three.
* **clean vs noisy is the same document read two ways.** Every document exists as the
  rendered PDF and as a degraded scan. `clean` extracts from the PDF's text layer (no OCR
  noise at all); `noisy` OCRs the scan with Tesseract. The difference between the two
  rows is therefore the cost of OCR, with the extraction prompt held constant -- which is
  also exactly the comparison the Week 11 Textract benchmark needs.
* **A stratified subsample, because of quota.** Extraction is one Gemini call per
  document per split: the full corpus is 480 calls against a 20-a-day free tier (D-032),
  24 days. `--consignments N` draws N consignments keeping the corpus's clean/seeded-
  error ratio, deterministically, and the report states the N. The v3.1 plan's own
  Textract benchmark samples for the same reason.
* **Cached, and a quota refusal is never a score.** Every extraction is appended to the
  cache before it is scored, keyed by document, split, engine and prompt version, so a run
  spread over several days never pays for a document twice. A 429 stops the run and the
  document is left out -- scoring it as a total miss, which is what this template did with
  any exception, would publish the free-tier limit as an accuracy number.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common import config

try:
    from rapidfuzz import fuzz
except ImportError:  # handled at scoring time, deliberately not here
    fuzz = None


# --------------------------------------------------------------------------
# 1. Field specification — matches the Week 3 corpus labels (D-021)
# --------------------------------------------------------------------------
# Each field maps to a comparison kind:
#   money   -> parsed to float, compared to the cent
#   date    -> parsed to a date, compared exactly
#   code    -> uppercased, non-alphanumerics stripped, compared exactly
#   text    -> normalised, then fuzzy-compared at TEXT_SIMILARITY_THRESHOLD
#   enum    -> uppercased, compared exactly
#   number  -> parsed to float, compared with NUMERIC_TOLERANCE

_COMMON_FIELDS: dict[str, str] = {
    "document_type": "enum",
    "document_number": "code",
    "document_date": "date",
    "shipper_name": "text",
    "consignee_name": "text",
    "origin_facility": "text",
    "destination_facility": "text",
    "origin_centre_code": "code",
    "destination_centre_code": "code",
    "weight_kg": "number",
    "pieces": "number",
    "freight_charge": "money",
    "other_charges": "money",
    "total_amount": "money",
    "currency": "enum",
}

# Same fifteen fields on both. A BOL's label carries null `other_charges` and
# `total_amount` because the printed BOL does not show them: a model that fills them in
# anyway is scored as a hallucination, which is exactly the behaviour worth catching.
FIELD_SPEC: dict[str, dict[str, str]] = {
    "BOL": dict(_COMMON_FIELDS),
    "INVOICE": dict(_COMMON_FIELDS),
}

TEXT_SIMILARITY_THRESHOLD = 90  # rapidfuzz ratio, 0-100
NUMERIC_TOLERANCE = 0.01
MONEY_TOLERANCE = 0.005  # half a cent


# --------------------------------------------------------------------------
# 2. Normalisation and comparison
# --------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def norm_text(value: Any) -> str:
    """Lowercase, strip accents, collapse whitespace and punctuation runs."""
    s = _strip_accents(str(value)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def norm_code(value: Any) -> str:
    """Uppercase, drop everything that is not a letter or digit."""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def parse_money(value: Any) -> float | None:
    """'Rs. 1,700.00' / '₹1700' / 1700 -> 1700.0"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d.\-]", "", str(value).replace(",", ""))
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_number(value: Any) -> float | None:
    return parse_money(value)


DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%Y/%m/%d", "%d.%m.%Y",
]


def parse_date(value: Any) -> str | None:
    """Return an ISO date string, or None if unparseable."""
    if value is None:
        return None
    s = str(value).strip()
    # Tolerate an ISO datetime
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", s):
        return s[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()  # noqa: DTZ007 -- a date, no zone
        except ValueError:
            continue
    return None


TRUE_TOKENS = {"true", "yes", "y", "1", "present", "signed"}
FALSE_TOKENS = {"false", "no", "n", "0", "absent", "unsigned", "none"}


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in TRUE_TOKENS:
        return True
    if s in FALSE_TOKENS:
        return False
    return None


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return str(value).strip().lower() in {"null", "none", "n/a", "na", "-"}


def values_match(kind: str, truth: Any, pred: Any) -> bool:
    """The single place where 'is this extraction correct' is decided."""
    if kind == "money":
        t, p = parse_money(truth), parse_money(pred)
        return t is not None and p is not None and abs(t - p) <= MONEY_TOLERANCE
    if kind == "number":
        t, p = parse_number(truth), parse_number(pred)
        return t is not None and p is not None and abs(t - p) <= NUMERIC_TOLERANCE
    if kind == "date":
        t, p = parse_date(truth), parse_date(pred)
        return t is not None and t == p
    if kind == "code":
        return norm_code(truth) == norm_code(pred) != ""
    if kind == "enum":
        return str(truth).strip().upper() == str(pred).strip().upper()
    if kind == "bool":
        t, p = parse_bool(truth), parse_bool(pred)
        return t is not None and t == p
    # default: text
    t, p = norm_text(truth), norm_text(pred)
    if t == p:
        return True
    if fuzz is None:
        # Deliberately a crash, not a False.
        #
        # Returning False here meant that on a machine without rapidfuzz every
        # near-miss counted as a wrong answer, and the run still produced a
        # report. Facility names come off a scan with a character or two
        # changed -- `Pnchlght` for `Pnchight` -- so the accuracy this file
        # publishes would drop by several points with nothing in the output
        # saying the matcher was missing. That is P-58 again: an evaluation
        # harness must distinguish "the agent was wrong" from "the harness was
        # not installed", and if it cannot, its worst numbers are reports about
        # the machine.
        raise RuntimeError(
            "rapidfuzz is not installed, so text fields can only be compared "
            "exactly and the accuracy this run reports would be understated. "
            "Install it (pip install rapidfuzz) and re-run; it is in "
            "requirements.txt."
        )
    return fuzz.ratio(t, p) >= TEXT_SIMILARITY_THRESHOLD


# --------------------------------------------------------------------------
# 3. Scoring
# --------------------------------------------------------------------------

@dataclass
class Tally:
    correct: int = 0
    wrong: int = 0
    missed: int = 0
    hallucinated: int = 0

    @property
    def in_truth(self) -> int:
        return self.correct + self.wrong + self.missed

    @property
    def extracted(self) -> int:
        return self.correct + self.wrong + self.hallucinated

    def metrics(self) -> dict[str, float | int]:
        acc = self.correct / self.in_truth if self.in_truth else 0.0
        prec = self.correct / self.extracted if self.extracted else 0.0
        rec = self.correct / self.in_truth if self.in_truth else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        halluc = self.hallucinated / self.extracted if self.extracted else 0.0
        return {
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "hallucination_rate": round(halluc, 4),
            "correct": self.correct,
            "wrong": self.wrong,
            "missed": self.missed,
            "hallucinated": self.hallucinated,
            "fields_in_truth": self.in_truth,
            "fields_extracted": self.extracted,
        }


def score_document(doc_type: str, truth: dict, pred: dict) -> tuple[Tally, list[dict]]:
    """Score one document. Returns the tally plus a per-field error record."""
    spec = FIELD_SPEC.get(doc_type.upper(), {})
    tally = Tally()
    errors: list[dict] = []

    for name, kind in spec.items():
        t_val, p_val = truth.get(name), pred.get(name)
        t_empty, p_empty = is_empty(t_val), is_empty(p_val)

        if t_empty and p_empty:
            continue  # correctly absent — not scored either way
        if t_empty and not p_empty:
            tally.hallucinated += 1
            outcome = "hallucinated"
        elif not t_empty and p_empty:
            tally.missed += 1
            outcome = "missed"
        elif values_match(kind, t_val, p_val):
            tally.correct += 1
            continue  # no error record for correct fields
        else:
            tally.wrong += 1
            outcome = "wrong"

        errors.append({
            "field": name,
            "kind": kind,
            "outcome": outcome,
            "truth": t_val,
            "predicted": p_val,
        })

    return tally, errors


# --------------------------------------------------------------------------
# 4. Corpus loading and extraction — wired to the real corpus and agent
# --------------------------------------------------------------------------

RAW_DIR = config.BENCHMARKS_RAW_DIR
MANIFEST = RAW_DIR / "w3_doc_corpus_manifest.csv"
CACHE = RAW_DIR / "w7_doc_extraction_cache.jsonl"
DOC_COLUMNS = {
    "BOL": ("bol_pdf", "bol_scan_jpg", "bol_label_json"),
    "INVOICE": ("invoice_pdf", "invoice_scan_jpg", "invoice_label_json"),
}
#: The text source for each split. `clean` never touches OCR, so the engine label only
#: describes the `noisy` half; it is recorded per row rather than assumed.
SPLIT_ENGINE = {"clean": "pdf-text"}


#: Failures of this machine, not of the agent: no API key, no network, a stalled request,
#: a provider outage. A row that fails this way is left unscored, like a quota refusal.
#: Anything else -- unparseable JSON, a missing field, a broken PDF -- is the agent's
#: answer and is scored as a miss.
_ENVIRONMENTAL = re.compile(
    r"api[_ ]?key|credential|not set|unauthorized|permission denied|timeout|timed out|deadline|"
    r"connect|network|unavailable|503|502|500|internal server error",
    re.IGNORECASE,
)


def is_environmental(exc: Exception) -> bool:
    return bool(_ENVIRONMENTAL.search(f"{type(exc).__name__}: {exc}"))


class QuotaExhausted(RuntimeError):
    """The provider refused for quota. Stop the run; never score the document."""


def select_consignments(rows: list[dict], n: int | None, seed: int) -> list[dict]:
    """N consignments keeping the corpus's clean : seeded-error ratio, deterministically.

    Stratified rather than the first N, because the corpus is not shuffled by error type
    and a prefix could hold none of the seeded-error consignments at all -- the order
    corpus in Week 5 learned that lesson the expensive way.
    """
    if not n or n >= len(rows):
        return rows
    rng = random.Random(seed)
    seeded = [r for r in rows if r["error_types"].strip()]
    clean = [r for r in rows if not r["error_types"].strip()]
    n_seeded = max(1, round(n * len(seeded) / len(rows))) if seeded else 0
    picked = rng.sample(seeded, min(n_seeded, len(seeded))) + rng.sample(clean, min(n - n_seeded, len(clean)))
    return sorted(picked, key=lambda r: int(r["seq"]))


def load_corpus(docs_dir: Path, manifest: Path = MANIFEST, consignments: int | None = None,
                seed: int = 16) -> list[dict]:
    """
    One dict per (document, split):
        doc_id    e.g. "w3_00001_bol"
        path      the PDF for `clean`, the degraded scan for `noisy`
        doc_type  "BOL" | "INVOICE"
        split     "clean" | "noisy"
        truth     the label JSON -- what is printed on the document (D-021)
        seq, error_types   for slicing
    """
    with manifest.open(encoding="utf-8") as fh:
        rows = select_consignments(list(csv.DictReader(fh)), consignments, seed)

    corpus = []
    for row in rows:
        for doc_type, (pdf_col, scan_col, label_col) in DOC_COLUMNS.items():
            label_path = docs_dir / row[label_col]
            if not label_path.exists():
                print(f"  ! no label for {row[label_col]}, skipping")
                continue
            truth = json.loads(label_path.read_text(encoding="utf-8"))
            doc_id = Path(row[label_col]).stem
            for split, col in (("clean", pdf_col), ("noisy", scan_col)):
                path = docs_dir / row[col]
                if not path.exists():
                    print(f"  ! no rendered file {row[col]}, skipping")
                    continue
                corpus.append({
                    "doc_id": doc_id,
                    "path": path,
                    "doc_type": doc_type,
                    "split": split,
                    "truth": truth,
                    "seq": int(row["seq"]),
                    "error_types": row["error_types"],
                })
    return corpus


def document_text(path: Path, engine: str) -> str:
    """The text the extraction prompt sees: the PDF text layer, or OCR of the scan."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    if engine != "tesseract":
        raise ValueError(f"engine {engine!r} is not wired yet -- only tesseract (Week 11 adds textract)")
    from src.agents.document_agent import ocr_image

    return ocr_image(path)


def _cache_key(doc: dict, engine: str, prompt_label: str) -> str:
    return f"{doc['doc_id']}|{doc['split']}|{engine}|{prompt_label}"


def load_cache(path: Path = CACHE) -> dict[str, dict]:
    if not path.exists():
        return {}
    cache = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            cache[record["key"]] = record
    return cache


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("429", "resource_exhausted", "quota"))


def run_extraction(doc: dict, engine: str, prompt, cache: dict[str, dict],
                   cache_only: bool = False, cache_path: Path = CACHE) -> dict | None:
    """Extract one document, from the cache when it has already been paid for.

    Returns the predicted fields, or None when `cache_only` and nothing is cached (the
    caller leaves that document out of the scores). Raises QuotaExhausted on a provider
    quota refusal, and ValueError for a real extraction failure, which *is* scored.
    """
    engine_used = SPLIT_ENGINE.get(doc["split"], engine)
    key = _cache_key(doc, engine_used, prompt.label)
    if key in cache:
        return cache[key]["fields"]
    if cache_only:
        return None

    from src.agents.document_agent import extract_fields

    text = document_text(doc["path"], engine)
    try:
        fields = extract_fields(text, doc["doc_type"], prompt)
    except Exception as exc:
        if _is_quota_error(exc):
            raise QuotaExhausted(str(exc)[:200]) from exc
        raise

    record = {
        "key": key, "doc_id": doc["doc_id"], "split": doc["split"], "engine": engine_used,
        "prompt_version": prompt.label, "text_chars": len(text),
        "extracted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fields": fields,
    }
    cache[key] = record
    with cache_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return fields


# --------------------------------------------------------------------------
# 5. Driver
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    # Absolute, not "data/documents": the corpus lives in the checkout's own data
    # directory, and a relative default silently finds nothing when the run starts from a
    # git worktree or any other directory, reporting it as "no label for ...".
    ap.add_argument("--docs", type=Path, default=config.DOCUMENTS_DIR)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--out", type=Path, default=RAW_DIR)
    ap.add_argument("--engine", default="tesseract",
                    help="OCR engine for the noisy split, recorded in the output")
    ap.add_argument("--split", choices=["all", "clean", "noisy"], default="all")
    ap.add_argument("--consignments", type=int, default=None,
                    help="stratified subsample of N consignments (2 documents x 2 splits each)")
    ap.add_argument("--seed", type=int, default=16)
    ap.add_argument("--limit", type=int, default=None, help="cap on (document, split) rows")
    ap.add_argument("--prompt-version", default=None, help="pin a prompt, e.g. v2")
    ap.add_argument("--cache-only", action="store_true", help="score what is cached; no LLM calls")
    ap.add_argument("--tag", default="", help="suffix for the output files, e.g. _v3")
    args = ap.parse_args()

    from src.agents.prompts.registry import load_prompt

    prompt = load_prompt("doc_extraction", args.prompt_version)
    corpus = load_corpus(args.docs, args.manifest, args.consignments, args.seed)
    if args.split != "all":
        corpus = [d for d in corpus if d["split"] == args.split]
    if args.limit:
        corpus = corpus[: args.limit]

    if not corpus:
        raise SystemExit("No documents matched. Check --docs and --split.")

    print(f"Evaluating {len(corpus)} (document, split) rows with engine={args.engine}, "
          f"prompt={prompt.label}" + (" [cache only]" if args.cache_only else ""))

    cache = load_cache(args.out / CACHE.name)
    overall = Tally()
    by_type: dict[str, Tally] = defaultdict(Tally)
    by_split: dict[str, Tally] = defaultdict(Tally)
    by_field: dict[str, Tally] = defaultdict(Tally)
    per_doc: list[dict] = []
    failures: list[dict] = []
    not_run: list[str] = []
    stopped_for_quota = None

    for i, doc in enumerate(corpus, 1):
        label = f"{doc['doc_id']}/{doc['split']}"
        try:
            pred = run_extraction(doc, args.engine, prompt, cache, args.cache_only, args.out / CACHE.name)
        except QuotaExhausted as exc:
            stopped_for_quota = str(exc)
            not_run = [f"{d['doc_id']}/{d['split']}" for d in corpus[i - 1:]]
            print(f"  [{i}/{len(corpus)}] {label}: QUOTA — stopping; {len(not_run)} row(s) left unscored")
            break
        except Exception as exc:  # noqa: BLE001 -- see the two kinds below
            environmental = is_environmental(exc)
            kind = "ENVIRONMENT" if environmental else "EXTRACTION FAILED"
            print(f"  [{i}/{len(corpus)}] {label}: {kind} — {exc}")
            failures.append({"doc_id": doc["doc_id"], "split": doc["split"], "error": str(exc),
                             "scored": not environmental})
            if environmental:
                # No key, no network, a timeout: the agent never answered, so there is
                # nothing to score. Counting these as missed fields publishes the state of
                # this machine as the agent's accuracy -- a first run with no `.env`
                # produced "7.0% accuracy" from 37 such rows, which is the same mistake
                # the quota branch above exists to prevent.
                not_run.append(label)
                continue
            spec = FIELD_SPEC.get(doc["doc_type"], {})
            n_fields = sum(1 for f in spec if not is_empty(doc["truth"].get(f)))
            overall.missed += n_fields
            by_type[doc["doc_type"]].missed += n_fields
            by_split[doc["split"]].missed += n_fields
            continue

        if pred is None:  # --cache-only and nothing cached yet
            not_run.append(label)
            continue

        tally, errors = score_document(doc["doc_type"], doc["truth"], pred)

        for t in (overall, by_type[doc["doc_type"]], by_split[doc["split"]]):
            t.correct += tally.correct
            t.wrong += tally.wrong
            t.missed += tally.missed
            t.hallucinated += tally.hallucinated

        # per-field tallies
        spec = FIELD_SPEC.get(doc["doc_type"], {})
        err_by_field = {e["field"]: e["outcome"] for e in errors}
        for name in spec:
            t_empty = is_empty(doc["truth"].get(name))
            p_empty = is_empty(pred.get(name))
            if t_empty and p_empty:
                continue
            key = f"{doc['doc_type']}.{name}"
            outcome = err_by_field.get(name, "correct")
            setattr(by_field[key], outcome, getattr(by_field[key], outcome) + 1)

        per_doc.append({
            "doc_id": doc["doc_id"],
            "doc_type": doc["doc_type"],
            "split": doc["split"],
            "seq": doc["seq"],
            "error_types": doc["error_types"],
            **tally.metrics(),
            "errors": errors,
        })
        print(f"  [{i}/{len(corpus)}] {label}: "
              f"{tally.correct}/{tally.in_truth} correct"
              + (f", {tally.hallucinated} hallucinated" if tally.hallucinated else ""))

    args.out.mkdir(parents=True, exist_ok=True)
    scored_failures = [f for f in failures if f["scored"]]
    evaluated = len(per_doc) + len(scored_failures)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": args.engine,
        "prompt_version": prompt.label,
        "split_filter": args.split,
        "split_definition": {"clean": "PDF text layer, no OCR", "noisy": f"degraded scan, {args.engine} OCR"},
        "consignments": args.consignments or "all",
        "seed": args.seed,
        "rows_planned": len(corpus),
        "documents_evaluated": evaluated,
        "rows_not_run": not_run,
        "stopped_for_quota": stopped_for_quota,
        "extraction_failures": failures,
        "overall": overall.metrics(),
        "by_document_type": {k: v.metrics() for k, v in sorted(by_type.items())},
        "by_split": {k: v.metrics() for k, v in sorted(by_split.items())},
        "by_field": {k: v.metrics() for k, v in sorted(by_field.items())},
        "per_document": per_doc,
    }

    json_path = args.out / f"w7_doc_extraction_eval{args.tag}.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    csv_path = args.out / f"w7_doc_extraction_summary{args.tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scope", "group", "accuracy", "precision", "recall", "f1",
                    "hallucination_rate", "fields_in_truth"])
        for scope, groups in (("overall", {"all": overall}),
                              ("doc_type", by_type),
                              ("split", by_split),
                              ("field", by_field)):
            for name, tally in sorted(groups.items()):
                m = tally.metrics()
                w.writerow([scope, name, m["accuracy"], m["precision"], m["recall"],
                            m["f1"], m["hallucination_rate"], m["fields_in_truth"]])

    m = overall.metrics()
    print("\n" + "=" * 62)
    print(f"  Rows evaluated {evaluated} of {len(corpus)}   (scored failures: {len(scored_failures)}, "
          f"not run: {len(not_run)}, of which environmental: {len(failures) - len(scored_failures)})")
    print(f"  Accuracy       {m['accuracy']:.1%}   ({m['correct']}/{m['fields_in_truth']})")
    print(f"  Precision      {m['precision']:.1%}")
    print(f"  Recall         {m['recall']:.1%}")
    print(f"  F1             {m['f1']:.3f}")
    print(f"  Hallucination  {m['hallucination_rate']:.1%}   ({m['hallucinated']} fields)")
    for split_name, tally in sorted(by_split.items()):
        print(f"    {split_name:<12} accuracy {tally.metrics()['accuracy']:.1%}")
    print("=" * 62)

    worst = sorted(by_field.items(), key=lambda kv: kv[1].metrics()["accuracy"])[:5]
    if worst:
        print("\n  Weakest fields:")
        for name, tally in worst:
            print(f"    {name:<34} {tally.metrics()['accuracy']:.1%}")

    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
