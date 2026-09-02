"""Auto-retraining script: clean -> features -> train -> evaluate -> champion swap
(execution plan W4 D1-D2, MLOps track).

    python -m src.automation.retrain
    python -m src.automation.retrain --force-rebuild    # rebuild every cached stage first

One command runs the whole batch chain and ends with a decision: does the model this
run just trained replace the one the dashboard's what-if page
(`config.MODELS_DIR / "champion"`, `src/dashboard/app.py`) actually reads? Nothing
here retrains a model from scratch — it calls **Lahari's entry point**
(`src.ml.models.run`, split out of her CLI for exactly this reason) and acts on what
it returns, which is the whole point of an entry point rather than a second
implementation of Stage 6 living in `src/automation/`.

Pipeline stages are skipped when their frozen output already exists (D-016's cached
Parquet contract) rather than rebuilt every run — a versioned cache is not something
"auto-retraining" should silently blow away on a schedule. `--force-rebuild` is the
explicit opt-in for "the raw data changed, start from Stage 1."

Champion/challenger, concretely
--------------------------------
Every run trains both Random Forest and GBT (Lahari's `run()` already picks the
better of the two on test MAE, D-024) and calls that model the **challenger**. It is
promoted to **champion** — copied to `MODELS_DIR / "champion"`, the exact path the
dashboard's artefact-status check and the not-yet-built what-if page both read — only
if its test MAE beats the champion metrics already on record, or if there is no
champion yet. A challenger that does not win changes nothing: the file the dashboard
reads keeps pointing at whichever model actually has the best measured error, not the
most recently trained one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("automation.retrain")

#: (module, output path) for each batch stage, in dependency order. A stage is run
#: only if its output does not already exist -- see module docstring.
PIPELINE_STAGES: list[tuple[str, Path]] = [
    ("src.pipeline.clean", config.CLEAN_V1),
    ("src.pipeline.reconstruct", config.TRIPS_V1),
    ("src.pipeline.hubs", config.HUBS_V1),
    ("src.pipeline.features", config.FEATURES_V1),
]

CHAMPION_DIR = config.MODELS_DIR / "champion"
CHAMPION_METRICS_JSON = config.MODELS_DIR / "champion_metrics.json"
#: Committed evidence that the loop actually ran more than once -- one line per
#: invocation, append-only. Small, text, and traceable the same way every other
#: number in `benchmarks/` is (GIT_RULES SS4).
RETRAIN_HISTORY_JSONL = config.BENCHMARKS_RAW_DIR / "w4_retrain_history.jsonl"

#: A stage gets this many attempts before the run gives up on it -- bounded, not
#: infinite, because a genuinely broken stage (bad code, bad input) will fail the
#: same way every time and a retry loop should not turn that into a long silent hang.
#: Two is enough to ride out the transient case this project has actually hit (P-30's
#: driver-heap exhaustion, where a retry after other processes free memory can
#: succeed) without masking a real failure as a slow one.
MAX_STAGE_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 10


class EnvironmentNotReady(RuntimeError):
    """Raised by `preflight()` -- the run stopped before touching Spark at all."""


def preflight() -> None:
    """Fail fast, with one clear message, rather than let all four Spark stages fail
    the same cryptic way one after another.

    D-012 / P-06 already found what a broken `JAVA_HOME` looks like from inside
    Spark's own boot sequence: a stack trace with no mention of Java anywhere near
    the top. Checking the same thing `check_env.check_java` checks -- before
    `ensure_batch_pipeline` spends minutes running stages that cannot possibly
    succeed -- is the difference between a one-line error naming the actual cause
    and a person reading four identical Spark tracebacks to find it themselves.
    """
    java_home = os.environ.get("JAVA_HOME", "")
    exe_name = "java.exe" if os.name == "nt" else "java"
    if not java_home or not (Path(java_home) / "bin" / exe_name).exists():
        raise EnvironmentNotReady(
            f"JAVA_HOME is not set to a valid JDK (got {java_home!r}). Every stage "
            "below needs Spark, and Spark will not start without it -- see "
            "docs/decisions.md D-012 or run `python -m src.common.check_env`."
        )


def ensure_batch_pipeline(force: bool = False) -> None:
    """Run each Stage 1-4 module as a subprocess, skipping one whose frozen output
    already exists. Each stage owns and stops its own SparkSession (`src.common.spark`);
    running them as separate processes rather than in-process imports means this
    script never has to reason about two stages sharing one JVM.

    Each stage gets up to `MAX_STAGE_ATTEMPTS` tries with a short backoff between them
    -- hardening against the transient case (a Spark job that fails once under memory
    pressure and would succeed a moment later, P-30's own shape of problem), not
    against a stage that is actually broken, which will exhaust its attempts and raise
    exactly as before.
    """
    for module, output_path in PIPELINE_STAGES:
        if output_path.exists() and not force:
            log.info("%s -> %s already exists, skipping", module, output_path.name)
            continue

        last_returncode = None
        for attempt in range(1, MAX_STAGE_ATTEMPTS + 1):
            log.info("running python -m %s (attempt %d/%d)...", module, attempt, MAX_STAGE_ATTEMPTS)
            result = subprocess.run([sys.executable, "-m", module], check=False)
            if result.returncode == 0:
                break
            last_returncode = result.returncode
            log.warning("%s exited %d on attempt %d/%d", module, result.returncode, attempt, MAX_STAGE_ATTEMPTS)
            if attempt < MAX_STAGE_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)
        else:
            raise RuntimeError(
                f"{module} exited {last_returncode} on every one of {MAX_STAGE_ATTEMPTS} "
                "attempts -- batch pipeline stopped"
            )


def train_challenger(folds: int, models_dir: Path) -> dict:
    """Lahari's entry point, called rather than reimplemented (module docstring)."""
    from src.ml.models import run as train_and_evaluate

    log.info("training challenger (Random Forest + GBT, %d-fold CV)...", folds)
    return train_and_evaluate(folds=folds, models_dir=models_dir)


def load_champion_metrics() -> dict | None:
    if not CHAMPION_METRICS_JSON.exists():
        return None
    return json.loads(CHAMPION_METRICS_JSON.read_text(encoding="utf-8"))


def promote_challenger(report: dict, models_dir: Path) -> dict:
    """Compare the challenger this run just trained against the champion on record,
    and swap only if it genuinely wins.

    Returns a small result dict logged to `RETRAIN_HISTORY_JSONL` regardless of
    outcome -- "the challenger did not win" is as much a fact about this run as a
    promotion is, and silently recording only the promotions would make the history
    read like every run wins.
    """
    winner = report["winner"]
    challenger_mae = report["test_mae"][winner]
    champion = load_champion_metrics()

    if champion is None:
        promote = True
        reason = "no champion on record yet"
    elif challenger_mae < champion["test_mae"]:
        promote = True
        reason = f"{challenger_mae:.2f} < champion's {champion['test_mae']:.2f} min MAE"
    else:
        promote = False
        reason = f"{challenger_mae:.2f} >= champion's {champion['test_mae']:.2f} min MAE"

    outcome = {
        "promoted": promote,
        "challenger_model": winner,
        "challenger_test_mae": challenger_mae,
        "champion_test_mae_before": champion["test_mae"] if champion else None,
        "reason": reason,
        "generated_at": report["generated_at"],
    }

    if promote:
        source = models_dir / f"{winner}_v1"
        if CHAMPION_DIR.exists():
            shutil.rmtree(CHAMPION_DIR)
        shutil.copytree(source, CHAMPION_DIR)
        CHAMPION_METRICS_JSON.write_text(
            json.dumps(
                {
                    "model_name": winner,
                    "test_mae": challenger_mae,
                    "test_mae_by_model": report["test_mae"],
                    "n_train": report["n_train"],
                    "n_test": report["n_test"],
                    "promoted_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("PROMOTED %s -> champion (%s)", winner, reason)
    else:
        log.info("challenger not promoted (%s)", reason)

    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-rebuild", action="store_true", help="rebuild every cached stage, not only missing ones")
    parser.add_argument("--folds", type=int, default=3, help="CV folds for the challenger fit (src.ml.models default)")
    parser.add_argument("--models-dir", type=Path, default=config.MODELS_DIR)
    args = parser.parse_args()

    config.ensure_dirs()
    try:
        preflight()
    except EnvironmentNotReady as exc:
        log.error(str(exc))
        return 1

    ensure_batch_pipeline(force=args.force_rebuild)
    report = train_challenger(args.folds, args.models_dir)
    outcome = promote_challenger(report, args.models_dir)

    RETRAIN_HISTORY_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RETRAIN_HISTORY_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(outcome) + "\n")

    log.info(
        "retrain run complete: %s (%s min MAE), promoted=%s",
        outcome["challenger_model"], outcome["challenger_test_mae"], outcome["promoted"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
