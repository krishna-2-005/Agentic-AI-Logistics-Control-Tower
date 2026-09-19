"""Publish the dashboard as a Hugging Face Space (G-08), or stage the exact upload locally.

    python scripts/deploy_hf_space.py --stage dist/hf_space        # build the bundle, upload nothing
    HF_TOKEN=... python scripts/deploy_hf_space.py --repo <user>/control-tower

The bundle is the smallest set of files the dashboard reads: `src/`, the committed
`benchmarks/`, `.streamlit/`, the cloud requirements, and a Docker SDK wrapper whose README
carries the Space metadata. `data/` is never uploaded — it is gitignored for the same
reason it is not deployed (see docs/deploy_dashboard.md).

`--stage` exists so the upload can be tested before it happens: install
`requirements-cloud.txt` into a clean environment, run the dashboard from the staged folder,
and render every page. That is how the bundle was verified before anything was published.

A token is read from `HF_TOKEN` or the local `huggingface-cli login`; it is never written
anywhere by this script.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "deploy" / "hf_space"

#: (source relative to the repo root, destination inside the Space)
BUNDLE = [
    ("src", "src"),
    ("benchmarks", "benchmarks"),
    (".streamlit", ".streamlit"),
    ("requirements-cloud.txt", "requirements-cloud.txt"),
    ("deploy/hf_space/Dockerfile", "Dockerfile"),
    ("deploy/hf_space/README.md", "README.md"),
]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def stage(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for source, dest in BUNDLE:
        src, dst = ROOT / source, out / dest
        if src.is_dir():
            shutil.copytree(src, dst, ignore=SKIP)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    files = [p for p in out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"staged {len(files)} files, {size / 1e6:.1f} MB -> {out}")
    return out


def publish(repo: str, staged: Path) -> str:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo_id=repo, repo_type="space", space_sdk="docker", exist_ok=True)
    api.upload_folder(folder_path=str(staged), repo_id=repo, repo_type="space",
                      commit_message="deploy the control tower dashboard")
    url = f"https://huggingface.co/spaces/{repo}"
    print(f"published: {url}")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the dashboard as a Hugging Face Space")
    parser.add_argument("--stage", type=Path, default=None, help="build the bundle here and stop")
    parser.add_argument("--repo", default=None, help="<user>/<space> to publish to")
    args = parser.parse_args()
    staged = stage(args.stage or ROOT / "dist" / "hf_space")
    if args.stage:
        return 0
    if not args.repo:
        print("pass --repo <user>/<space> to publish, or --stage to only build", file=sys.stderr)
        return 2
    publish(args.repo, staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
