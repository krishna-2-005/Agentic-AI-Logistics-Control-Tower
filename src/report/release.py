"""Archive the generated artefacts as release assets (execution plan v3.1 W8 D3-D4).

    python -m src.report.release --out dist/            # build the archives
    python -m src.report.release --manifest-only        # just report what would be in them

`data/` is gitignored on purpose: 900 MB of regenerable output does not belong in a git
history. But "regenerable" assumes a machine with Spark, a JDK, 16 GB of RAM and four
hours. A release asset is the difference between *reproducible in principle* and *openable
by a reader*, so this packages the caches, the models, the document corpus and the TMS
database into archives to attach to the v1.0 GitHub release.

What is **not** archived, and why:

* `data/raw/delhivery_data.csv` — someone else's dataset. It is linked, not redistributed.
* `data/raw/nyc_taxi/` — 914 MB of public NYC TLC parquet, downloadable by the script that
  used it (`src.pipeline.scale_benchmark`).
* `.env`, `.env.git` — secrets, which have never been in this repository and are not going
  to arrive in a zip file.
* `data/chroma_db/` — rebuilt in 90 seconds from the documents it indexes, and an embedding
  index is version-locked to the library that wrote it.

Every archive gets a manifest line with its size and SHA-256, so a download can be checked
rather than trusted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("report.release")

#: name -> (paths to include, what it is for)
BUNDLES: dict[str, tuple[list[Path], str]] = {
    "parquet-caches": (
        [config.CLEAN_V1, config.PROCESSED_DIR / "trips_v1", config.PROCESSED_DIR / "hubs_v1",
         config.FEATURES_V1, config.FEATURES_V2],
        "Stage 1-4 Spark outputs: cleaned legs, trips, hub dwell, and both feature tables",
    ),
    "models": (
        [config.MODELS_DIR],
        "every fitted model, including the Week 4 champion and the Week 7 adopted residual model",
    ),
    "documents": (
        [config.DOCUMENTS_DIR],
        "the 120-consignment synthetic document corpus (240 PDFs, 240 scans, 240 label files)",
    ),
    "tms-database": (
        [config.TMS_DB_PATH],
        "the mock TMS SQLite file, with the orders and tickets the agents actually filed",
    ),
}


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file())


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def plan() -> dict[str, dict]:
    """What each bundle would contain, without building anything."""
    summary = {}
    for name, (paths, purpose) in BUNDLES.items():
        present = [p for p in paths if p.exists()]
        missing = [str(p.relative_to(config.REPO_ROOT)) for p in paths if not p.exists()]
        files = [f for p in present for f in _files(p)]
        summary[name] = {
            "purpose": purpose,
            "sources": [str(p.relative_to(config.REPO_ROOT)).replace("\\", "/") for p in present],
            "missing": missing,
            "files": len(files),
            "bytes": sum(f.stat().st_size for f in files),
        }
    return summary


def build(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": ("Attach these to the v1.0 GitHub release. The raw Delhivery CSV is not "
                 "redistributed here — see data/README.md for where to get it."),
        "bundles": {},
    }
    for name, (paths, purpose) in BUNDLES.items():
        present = [p for p in paths if p.exists()]
        if not present:
            log.warning("%s: nothing to archive", name)
            continue
        archive = out_dir / f"control-tower-{name}-v1.0.zip"
        count = 0
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for source in present:
                for file in _files(source):
                    zf.write(file, file.relative_to(config.REPO_ROOT))
                    count += 1
        size = archive.stat().st_size
        manifest["bundles"][name] = {
            "purpose": purpose,
            "archive": archive.name,
            "files": count,
            "bytes": size,
            "sha256": _digest(archive),
        }
        log.info("%s: %s file(s), %.1f MB", archive.name, f"{count:,}", size / 1e6)
    path = out_dir / "release_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("wrote %s", path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the generated artefacts for a release")
    parser.add_argument("--out", type=Path, default=config.REPO_ROOT / "dist")
    parser.add_argument("--manifest-only", action="store_true", help="report contents, build nothing")
    args = parser.parse_args()
    if args.manifest_only:
        print(json.dumps(plan(), indent=2))
        return 0
    build(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
