"""Tests for the auto-retraining orchestration (execution plan W4 D1-D2, D3-D4).

    pytest tests/test_retrain.py -q

Never touches Spark and never trains a real model — `src.ml.models.run()` is Lahari's
own tested code (`docs/W4_lahari_beat_osrm.md`); what belongs to this module, and what
these tests actually cover, is the orchestration *around* it: does a stage get skipped
correctly, does a failing stage retry and then fail loudly, does the preflight check
catch a broken environment before Spark ever starts, and does champion/challenger
promotion compare and swap correctly given a `report` dict shaped like `run()`'s.
"""

from __future__ import annotations

import json

import pytest

from src.automation import retrain


# ── preflight ────────────────────────────────────────────────────────────────
def test_preflight_raises_on_missing_java_home(monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    with pytest.raises(retrain.EnvironmentNotReady, match="JAVA_HOME"):
        retrain.preflight()


def test_preflight_raises_on_java_home_with_no_bin(monkeypatch, tmp_path):
    # A JAVA_HOME that exists as a path but has no bin/java(.exe) under it -- the
    # exact shape this project's real bug took (a stale path from another machine).
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    with pytest.raises(retrain.EnvironmentNotReady, match="JAVA_HOME"):
        retrain.preflight()


def test_preflight_passes_with_a_valid_java_home(monkeypatch, tmp_path):
    exe_name = "java.exe" if __import__("os").name == "nt" else "java"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / exe_name).write_text("", encoding="utf-8")
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    retrain.preflight()  # must not raise


# ── ensure_batch_pipeline ────────────────────────────────────────────────────
def test_ensure_batch_pipeline_skips_an_existing_output(monkeypatch, tmp_path):
    existing = tmp_path / "already_here"
    existing.mkdir()
    # A module that would fail loudly if it were ever actually invoked -- proves the
    # skip, rather than a lucky pass, is what happened.
    monkeypatch.setattr(retrain, "PIPELINE_STAGES", [("src.this_module_does_not_exist", existing)])
    retrain.ensure_batch_pipeline(force=False)  # must not raise / must not run anything


def test_ensure_batch_pipeline_retries_then_raises(monkeypatch, tmp_path):
    missing = tmp_path / "never_produced"
    calls: list[int] = []
    original_run = retrain.subprocess.run

    def fake_run(cmd, check=False):
        calls.append(1)
        return original_run(cmd, check=False)

    monkeypatch.setattr(retrain, "PIPELINE_STAGES", [("src.this_module_does_not_exist", missing)])
    monkeypatch.setattr(retrain, "RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(retrain.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="every one of 2 attempts"):
        retrain.ensure_batch_pipeline(force=True)
    assert len(calls) == retrain.MAX_STAGE_ATTEMPTS


# ── champion / challenger ────────────────────────────────────────────────────
def _fake_report(winner: str, mae: float) -> dict:
    return {
        "winner": winner,
        "test_mae": {"random_forest": mae if winner == "random_forest" else mae + 5, "gbt": mae if winner == "gbt" else mae + 5},
        "n_train": 21_095,
        "n_test": 5_274,
        "generated_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture(autouse=True)
def _isolated_champion_paths(monkeypatch, tmp_path):
    """Every champion/challenger test gets its own throwaway `models_dir` and
    champion paths -- never the developer's real `data/models/champion`.
    """
    monkeypatch.setattr(retrain, "CHAMPION_DIR", tmp_path / "champion")
    monkeypatch.setattr(retrain, "CHAMPION_METRICS_JSON", tmp_path / "champion_metrics.json")
    return tmp_path


def _make_challenger_dir(models_dir, name: str) -> None:
    d = models_dir / f"{name}_v1"
    d.mkdir(parents=True)
    (d / "marker.txt").write_text(name, encoding="utf-8")


def test_promotes_when_no_champion_on_record(tmp_path):
    _make_challenger_dir(tmp_path, "random_forest")
    report = _fake_report("random_forest", 36.9)

    outcome = retrain.promote_challenger(report, tmp_path)

    assert outcome["promoted"] is True
    assert outcome["champion_test_mae_before"] is None
    assert retrain.CHAMPION_DIR.exists()
    assert (retrain.CHAMPION_DIR / "marker.txt").read_text(encoding="utf-8") == "random_forest"
    metrics = json.loads(retrain.CHAMPION_METRICS_JSON.read_text(encoding="utf-8"))
    assert metrics["model_name"] == "random_forest"
    assert metrics["test_mae"] == 36.9


def test_declines_a_challenger_that_does_not_beat_the_champion(tmp_path):
    retrain.CHAMPION_DIR.mkdir()
    (retrain.CHAMPION_DIR / "marker.txt").write_text("incumbent", encoding="utf-8")
    retrain.CHAMPION_METRICS_JSON.write_text(json.dumps({"test_mae": 30.0}), encoding="utf-8")
    _make_challenger_dir(tmp_path, "gbt")

    outcome = retrain.promote_challenger(_fake_report("gbt", 38.0), tmp_path)

    assert outcome["promoted"] is False
    # the champion on disk must be untouched -- a decline is a no-op, not a partial swap
    assert (retrain.CHAMPION_DIR / "marker.txt").read_text(encoding="utf-8") == "incumbent"


def test_promotes_a_challenger_that_beats_the_champion(tmp_path):
    retrain.CHAMPION_DIR.mkdir()
    (retrain.CHAMPION_DIR / "marker.txt").write_text("incumbent", encoding="utf-8")
    retrain.CHAMPION_METRICS_JSON.write_text(json.dumps({"test_mae": 50.0}), encoding="utf-8")
    _make_challenger_dir(tmp_path, "random_forest")

    outcome = retrain.promote_challenger(_fake_report("random_forest", 36.9), tmp_path)

    assert outcome["promoted"] is True
    assert (retrain.CHAMPION_DIR / "marker.txt").read_text(encoding="utf-8") == "random_forest"


def test_load_champion_metrics_returns_none_when_absent():
    assert retrain.load_champion_metrics() is None
