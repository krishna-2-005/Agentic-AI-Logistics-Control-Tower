"""CLI entry point — the Week 3 Gate 3 deliverable.

    python -m src.agents.doc_corpus.generate                       # 120 docs, seed 42
    python -m src.agents.doc_corpus.generate --count 200 --seed 7
    python -m src.agents.doc_corpus.generate --error-rate 0.0      # a clean-only run

Writes, per consignment, a BOL + invoice PDF pair, a ground-truth JSON label per
document (`labels.py`'s fifteen fields — exactly what `doc_extraction/v1.md` expects
back), and a degraded "scan" JPEG per document (`noise.py`). All of that goes to
`data/documents/` (gitignored, regenerate on demand — the same D-009 discipline the
Spark caches follow). Two things are committed instead: the manifest CSV in
`benchmarks/raw/` and a curated handful of PDFs in `demo/sample_documents/`
(GIT_RULES §3's "5-10 examples, not the full corpus").
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from src.agents.doc_corpus import labels, seed_errors, templates
from src.agents.doc_corpus.noise import render_scan_image
from src.agents.doc_corpus.records import generate_records
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.doc_corpus")

MANIFEST_CSV = config.BENCHMARKS_RAW_DIR / "w3_doc_corpus_manifest.csv"

MANIFEST_FIELDS = (
    "seq", "shipment_ref", "corridor_id", "source_center", "dest_center",
    "route_type", "document_date", "error_types",
    "bol_pdf", "bol_label_json", "bol_scan_jpg",
    "invoice_pdf", "invoice_label_json", "invoice_scan_jpg",
)


def _write_json(obj: dict, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def run(count: int, seed: int, error_rate: float, output_dir: Path, demo_samples: int) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    records = generate_records(count, seed)
    bol_labels = {r.seq: labels.bol_label(r) for r in records}
    invoice_labels = {r.seq: labels.invoice_label(r) for r in records}

    for d in (*bol_labels.values(), *invoice_labels.values()):
        assert tuple(d.keys()) == labels.LABEL_FIELDS, "label dict drifted from doc_extraction/v1.md's schema"

    applied = seed_errors.apply_seeded_errors(records, bol_labels, invoice_labels, seed, error_rate)

    manifest_rows: list[dict] = []
    for rec in records:
        bol = bol_labels[rec.seq]
        invoice = invoice_labels[rec.seq]
        base = f"w3_{rec.seq:05d}"

        bol_pdf = output_dir / f"{base}_bol.pdf"
        bol_json = output_dir / f"{base}_bol.json"
        bol_scan = output_dir / f"{base}_bol_scan.jpg"
        invoice_pdf = output_dir / f"{base}_invoice.pdf"
        invoice_json = output_dir / f"{base}_invoice.json"
        invoice_scan = output_dir / f"{base}_invoice_scan.jpg"

        templates.render_bol_pdf(rec, bol, bol_pdf)
        _write_json(bol, bol_json)
        render_scan_image(rec, bol, "BOL", bol_scan, seed=seed * 1000 + rec.seq * 2)

        templates.render_invoice_pdf(rec, invoice, invoice_pdf)
        _write_json(invoice, invoice_json)
        render_scan_image(rec, invoice, "INVOICE", invoice_scan, seed=seed * 1000 + rec.seq * 2 + 1)

        manifest_rows.append({
            "seq": rec.seq,
            "shipment_ref": rec.shipment_ref,
            "corridor_id": rec.corridor_id,
            "source_center": rec.source_center,
            "dest_center": rec.dest_center,
            "route_type": rec.route_type,
            "document_date": rec.document_date,
            "error_types": ";".join(applied[rec.seq]),
            "bol_pdf": bol_pdf.name,
            "bol_label_json": bol_json.name,
            "bol_scan_jpg": bol_scan.name,
            "invoice_pdf": invoice_pdf.name,
            "invoice_label_json": invoice_json.name,
            "invoice_scan_jpg": invoice_scan.name,
        })

    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest_rows)

    n_errors = sum(1 for r in manifest_rows if r["error_types"])
    log.info("generated %d consignments (%d BOL+invoice pairs) -> %s", count, count, output_dir)
    log.info("seeded errors on %d/%d records (rate=%.2f)", n_errors, count, error_rate)
    for kind in seed_errors.ERROR_TYPES:
        n = sum(1 for r in manifest_rows if kind in r["error_types"].split(";"))
        log.info("  %-28s %d", kind, n)
    log.info("manifest -> %s", MANIFEST_CSV)

    _copy_demo_samples(manifest_rows, output_dir, demo_samples)
    return manifest_rows


def _copy_demo_samples(manifest_rows: list[dict], output_dir: Path, demo_samples: int) -> None:
    """Curate a handful of pairs for `demo/sample_documents/` — one clean pair and one
    pair per error kind where the corpus happens to contain one, per GIT_RULES §3
    ("5-10 examples, not the full corpus")."""
    by_seq = {r["seq"]: r for r in manifest_rows}
    wanted: list[tuple[str, int]] = []
    clean = next((r["seq"] for r in manifest_rows if not r["error_types"]), None)
    if clean:
        wanted.append(("clean", clean))
    for kind in seed_errors.ERROR_TYPES:
        seq = next((r["seq"] for r in manifest_rows if kind in r["error_types"].split(";")), None)
        if seq:
            wanted.append((kind, seq))
    wanted = wanted[:demo_samples]
    if not wanted:
        return

    config.DEMO_SAMPLE_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_lines = [
        "# Curated Week 3 document samples\n",
        ("Full corpus: `python -m src.agents.doc_corpus.generate` -> `data/documents/` "
         "(gitignored; see `benchmarks/raw/w3_doc_corpus_manifest.csv` for every record).\n\n"),
        "| Sample | Seq | Kind | Shipment |\n|---|---|---|---|\n",
    ]
    for i, (kind, seq) in enumerate(wanted, start=1):
        row = by_seq[seq]
        for doc_type, src_name in (("bol", row["bol_pdf"]), ("invoice", row["invoice_pdf"])):
            shutil.copy(output_dir / src_name, config.DEMO_SAMPLE_DOCUMENTS_DIR / f"sample{i:02d}_{doc_type}.pdf")
        manifest_lines.append(f"| sample{i:02d} | {seq} | {kind} | {row['shipment_ref']} |\n")

    (config.DEMO_SAMPLE_DOCUMENTS_DIR / "MANIFEST.md").write_text("".join(manifest_lines), encoding="utf-8")
    log.info("copied %d curated pairs -> %s", len(wanted), config.DEMO_SAMPLE_DOCUMENTS_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=120, help="consignments to generate (Gate 3 wants 100+)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--error-rate", type=float, default=0.15)
    parser.add_argument("--output", type=str, default=str(config.DOCUMENTS_DIR))
    # GIT_RULES §3: demo/sample_documents/ is "5-10 examples, not the full corpus" -
    # 5 pairs = 10 files, the top of that range.
    parser.add_argument("--demo-samples", type=int, default=5)
    args = parser.parse_args()

    run(args.count, args.seed, args.error_rate, Path(args.output), args.demo_samples)


if __name__ == "__main__":
    main()
