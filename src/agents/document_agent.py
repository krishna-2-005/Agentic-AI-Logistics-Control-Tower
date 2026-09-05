"""Document Intelligence Agent v1 (execution plan W4 D1-D2).

    python -m src.agents.document_agent --demo          # a handful of sample docs
    python -m src.agents.document_agent --count 40       # first 20 consignments (40 docs)

Two stages, kept as two functions rather than one because the plan lets either be
swapped independently later (D3-D4 iterates the prompt; a future version could swap
the OCR engine without touching extraction):

1. **`ocr_image()`** — Tesseract reads the degraded scan JPEG (`src.agents.doc_corpus`,
   Week 3) into raw text. No layout reconstruction beyond what Tesseract does itself;
   the prompt is written to tolerate a flat text dump (D-008, `doc_extraction/v1.md`).
2. **`extract_fields()`** — one LLM call, through `src.agents.llm.get_llm()` (D-007,
   "one LLM construction site"), rendering the versioned prompt
   (`src.agents.prompts.registry`, D-008) with the OCR text and parsing its JSON
   response into the fifteen-field dict `labels.py` already promises `generate.py`'s
   ground truth will match key-for-key.

What this module does **not** do: score anything. Lahari's evaluation harness (D5)
is a deliberately separate piece of code, per the execution plan's own note that
keeping builder and judge apart is "better science, better viva answers" — this
module's job ends at producing a prediction, saved to
`benchmarks/raw/w4_doc_agent_predictions.json` alongside the OCR text and any error,
so her harness can score it without re-running OCR or spending a second LLM call per
document.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import pytesseract
from PIL import Image

from src.agents.llm import get_llm
from src.agents.prompts.registry import Prompt, load_prompt
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.document_agent")

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

MANIFEST_CSV = config.BENCHMARKS_RAW_DIR / "w3_doc_corpus_manifest.csv"
PREDICTIONS_JSON = config.BENCHMARKS_RAW_DIR / "w4_doc_agent_predictions.json"

#: The prompt's rule 13 asks for bare JSON; models occasionally wrap it in a fence
#: anyway (rule 13 is a request, not a constraint the API enforces), so this is
#: stripped rather than treated as a hard failure the prompt already tried to prevent.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def ocr_image(path: Path) -> str:
    """Raw OCR text from one scanned document image."""
    with Image.open(path) as img:
        return pytesseract.image_to_string(img).strip()


def _parse_json_response(raw: str) -> dict:
    cleaned = _JSON_FENCE_RE.sub("", raw.strip()).strip()
    return json.loads(cleaned)


def _response_text(response: object) -> str:
    """Flatten a chat model's `.content` to plain text.

    Most providers return a plain string. Some (Gemini among them, as of the
    `gemini-3.6-flash` pin -- P-35) return a list of content-block dicts instead, each
    carrying its text under a `"text"` key. Handling both here, once, is the same
    reasoning as D-007's single LLM construction site: every agent that calls
    `get_llm()` gets this for free rather than each writing its own unwrap.
    """
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts)
    return str(content)


def extract_fields(document_text: str, doc_type: str, prompt: Prompt | None = None) -> dict:
    """One LLM call -> the fifteen-field dict `doc_extraction/vN.md` specifies."""
    prompt = prompt or load_prompt("doc_extraction")
    rendered = prompt.render(doc_type=doc_type, document_text=document_text)
    response = get_llm().invoke(rendered)
    raw = _response_text(response)
    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{prompt.label} returned non-JSON: {raw[:300]!r}") from e


def process_document(image_path: Path, doc_type: str, prompt: Prompt | None = None) -> dict:
    """OCR -> extraction, for one scanned document image."""
    text = ocr_image(image_path)
    fields = extract_fields(text, doc_type, prompt)
    return {"ocr_text": text, "fields": fields}


def run_corpus(
    manifest_csv: Path,
    documents_dir: Path,
    limit: int | None,
    prompt_version: str | None,
    out_json: Path,
) -> list[dict]:
    """Run the agent over the first `limit` consignments' BOL + invoice pair each."""
    prompt = load_prompt("doc_extraction", prompt_version)
    with open(manifest_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]

    predictions: list[dict] = []
    for row in rows:
        for doc_type, img_col, label_col in (
            ("BOL", "bol_scan_jpg", "bol_label_json"),
            ("INVOICE", "invoice_scan_jpg", "invoice_label_json"),
        ):
            image_path = documents_dir / row[img_col]
            entry = {
                "seq": int(row["seq"]),
                "shipment_ref": row["shipment_ref"],
                "doc_type": doc_type,
                "image": row[img_col],
                "label_json": row[label_col],
                "prompt_version": prompt.label,
            }
            try:
                result = process_document(image_path, doc_type, prompt)
                entry["ocr_chars"] = len(result["ocr_text"])
                entry["predicted_fields"] = result["fields"]
                log.info("seq=%s %-7s -> ok (%d OCR chars)", row["seq"], doc_type, entry["ocr_chars"])
            except Exception as e:  # noqa: BLE001 -- one bad document must not abort the run
                entry["predicted_fields"] = None
                entry["error"] = str(e)
                log.warning("seq=%s %-7s -> FAILED: %s", row["seq"], doc_type, e)
            predictions.append(entry)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {
                "prompt_version": prompt.label,
                "n_documents": len(predictions),
                "n_failed": sum(1 for p in predictions if p["predicted_fields"] is None),
                "predictions": predictions,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_CSV)
    parser.add_argument("--documents-dir", type=Path, default=config.DOCUMENTS_DIR)
    parser.add_argument(
        "--count", type=int, default=20,
        help="consignments to run (2 documents each) -- default keeps the smoke test cheap on LLM calls",
    )
    parser.add_argument("--demo", action="store_true", help="run just the 5 curated demo consignments")
    parser.add_argument("--prompt-version", type=str, default=None, help="pin a version, e.g. v1")
    parser.add_argument("--out", type=Path, default=PREDICTIONS_JSON)
    args = parser.parse_args()

    if not args.manifest.exists():
        log.error(
            "Missing %s -- run `python -m src.agents.doc_corpus.generate` first "
            "to build the local (gitignored) corpus.",
            args.manifest,
        )
        return 1

    limit = 5 if args.demo else args.count
    predictions = run_corpus(args.manifest, args.documents_dir, limit, args.prompt_version, args.out)
    n_ok = sum(1 for p in predictions if p["predicted_fields"] is not None)
    log.info("%d/%d documents extracted -> %s", n_ok, len(predictions), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
