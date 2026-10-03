"""Stage and push the public API to a Hugging Face Docker Space (WP-04).

    python scripts/deploy_api_space.py --stage-only        # build the folder, push nothing
    python scripts/deploy_api_space.py                     # stage, then create/update the Space

Needs `HF_TOKEN` (write) in `.env`. The Space is `<your HF user>/agentic-control-tower-api`
unless `--repo` says otherwise.

What goes up is an **allow-list**, never the working tree: the API's code, the committed
benchmark tables the assistant and the alert feed read, the docs the assistant indexes,
the served model, and the three serving files built from local data (facts, alert feed,
agent traces). `.env`, `.env.git`, the parquet caches, the TMS database and everything
else under `data/` stay on this machine. The staged folder is listed before upload so
what is about to become public can be read first.

Secrets go to the Space's secret store, never into a file: `GEMINI_API_KEY` (only used
when a visitor opts into a model answer, capped at 10 a day). `LLM_MODEL` goes as a
plain variable. There is no TMS in the container (D-072), so `TMS_API_KEY` is not sent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import config  # noqa: E402 -- the repo root has to be on the path first

STAGE = config.DATA_DIR / "api_space_stage"
SPACE_NAME = "agentic-control-tower-api"
MODEL_DIR = config.MODELS_DIR / "v2_gbt_residual_stepsize"
SERVING = config.DATA_DIR / "serving"
TRACES = config.DATA_DIR / "traces" / "agent_calls.jsonl"
NEVER = (".env", ".env.git", "tms.sqlite")


def stage() -> list[Path]:
    """Build the Space folder from the allow-list. Returns every staged file."""
    for required in (MODEL_DIR, SERVING / "facts.jsonl.gz", SERVING / "alert_feed.jsonl.gz"):
        if not required.exists():
            raise SystemExit(f"missing {required} -- see the deploy section of docs/deploy_api.md")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    def copy_tree(src: Path, dest: Path, patterns=("*",)) -> None:
        for pattern in patterns:
            for path in src.rglob(pattern):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    target = dest / path.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)

    deploy = ROOT / "deploy" / "api_space"
    for name in ("Dockerfile", "requirements-api.txt", "README.md"):
        shutil.copy2(deploy / name, STAGE / name)
    copy_tree(ROOT / "src", STAGE / "src", ("*.py", "*.yaml", "*.yml", "*.md", "*.txt", "*.json"))
    copy_tree(ROOT / "docs", STAGE / "docs", ("*.md",))
    copy_tree(ROOT / "benchmarks" / "raw", STAGE / "benchmarks" / "raw", ("*.csv", "*.json"))
    copy_tree(MODEL_DIR, STAGE / "data" / "models" / MODEL_DIR.name)
    copy_tree(SERVING, STAGE / "data" / "serving")
    if TRACES.exists():
        # Trimmed to what `/api/traces` returns: a Space's files are downloadable, so the
        # raw log -- every input every agent was given -- must not be among them.
        (STAGE / "data" / "traces").mkdir(parents=True, exist_ok=True)
        keep = ("route", "decision", "verdict")
        trimmed = []
        for line in TRACES.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            outputs = {k: v for k, v in (r.get("outputs") or {}).items() if k in keep}
            trimmed.append(json.dumps({
                "agent": r.get("agent"), "started_at": r.get("started_at"),
                "duration_ms": r.get("duration_ms"),
                "error": None if r.get("error") is None else "error", "outputs": outputs,
            }))
        (STAGE / "data" / "traces" / TRACES.name).write_text("\n".join(trimmed) + "\n", encoding="utf-8")

    staged = sorted(p for p in STAGE.rglob("*") if p.is_file())
    leaked = [p for p in staged if p.name in NEVER or p.name.startswith(".env")]
    if leaked:
        raise SystemExit(f"refusing to stage {leaked}")
    return staged


def push(repo: str, token: str) -> str:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    gemini = os.environ.get("GEMINI_API_KEY", "")
    if gemini:
        api.add_space_secret(repo, "GEMINI_API_KEY", gemini)
    api.add_space_variable(repo, "LLM_MODEL", config.LLM_MODEL)
    api.add_space_variable(repo, "LLM_PROVIDER", "gemini")
    api.upload_folder(repo_id=repo, repo_type="space", folder_path=str(STAGE),
                      commit_message="deploy the public API", delete_patterns=["src/**", "docs/**"])
    return f"https://huggingface.co/spaces/{repo}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--repo", default=None, help="owner/name; default <HF user>/" + SPACE_NAME)
    args = parser.parse_args()

    staged = stage()
    size = sum(p.stat().st_size for p in staged)
    print(f"staged {len(staged)} files, {size / 1e6:.1f} MB, in {STAGE}")
    for top in sorted({p.relative_to(STAGE).parts[0] for p in staged}):
        count = sum(1 for p in staged if p.relative_to(STAGE).parts[0] == top)
        print(f"  {top:24s} {count} file(s)")
    if args.stage_only:
        return 0

    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise SystemExit("HF_TOKEN is not set in .env")
    from huggingface_hub import HfApi

    repo = args.repo or f"{HfApi(token=token).whoami()['name']}/{SPACE_NAME}"
    print("pushed:", push(repo, token))
    print("API URL:", f"https://{repo.replace('/', '-').replace('_', '-').lower()}.hf.space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
