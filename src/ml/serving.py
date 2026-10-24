"""Which model is served, and how a prediction is made from it (WP-11, closes D-053).

One place for the three things every scorer of the reported model has to agree on --
the stream, the what-if predictor and the stream-equals-batch validation:

* **which model**: the step-1.0 residual GBT D-050 adopted, the one whose 30.90-minute
  test MAE the paper reports (`src.ml.models_v2_stepsize`);
* **what it is called** on every answer (`MODEL_ID`), so a consumer can always say which
  model produced a number;
* **how a prediction is formed**: the corridor's as-of median plus the model's
  correction. The model predicts a residual, so scoring it without the baseline gives a
  number in the wrong units that nothing downstream would catch.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import numpy as np
import pandas as pd

from src.common import config
from src.ml.models_v2 import FEATURES_V2, prepare_serving
from src.ml.models_v2_stepsize import MODEL_PATH
from src.streaming.state import FEATURE_COLUMNS

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

#: Which model is served: `v2_gbt` (Spark MLlib, the default) or `lightgbm_l1` (the reported model, D-077, served through the
#: numpy tree reader and proven exact on every leg, D-101). One switch for the API, the what-if predictor and the stream.
SERVING_MODEL = os.environ.get("SERVING_MODEL", "v2_gbt")
#: The name the results use for each model (`w7_model_metrics_v2_stepsize.csv`, `b6_model_zoo.json`).
MODEL_IDS = {"v2_gbt": "v2_gbt_residual_absolute_step1", "lightgbm_l1": "lightgbm_l1_residual_old_median"}
if SERVING_MODEL not in MODEL_IDS:
    raise ValueError(f"SERVING_MODEL={SERVING_MODEL!r}; expected one of {sorted(MODEL_IDS)}")
MODEL_ID = MODEL_IDS[SERVING_MODEL]
LGBM_FOREST = config.DATA_DIR / "serving" / "lgbm_forest.json.gz"


def load_model(path=MODEL_PATH):
    """The served model: a Spark PipelineModel, or the LightGBM forest for the numpy reader."""
    if SERVING_MODEL == "lightgbm_l1":
        from src.ml import gbt_local

        if not LGBM_FOREST.exists():
            raise FileNotFoundError(f"No served forest at {LGBM_FOREST} -- run `python -m src.ml.lgbm_export` first.")
        return gbt_local.from_json(LGBM_FOREST)
    from pyspark.ml import PipelineModel

    if not path.exists():
        raise FileNotFoundError(
            f"No served model at {path} -- run `python -m src.ml.models_v2_stepsize` first."
        )
    return PipelineModel.load(str(path))


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    # History arrives as Python values from the stream and the predictor, where a column
    # can be all None in a small batch; as floats it means the same and prepares cleanly.
    history = [c for c in FEATURE_COLUMNS if c in frame.columns]
    return prepare_serving(frame.astype(dict.fromkeys(history, float))).reset_index(drop=True)


def _finish(prepared: pd.DataFrame, correction) -> pd.DataFrame:
    prepared["correction"] = correction
    prepared["predicted_gap_min"] = prepared["baseline_median"].to_numpy() + np.asarray(correction)
    return prepared


def score(spark: SparkSession, model, frame: pd.DataFrame) -> pd.DataFrame:
    """`frame` holds raw history columns as `features_v2` stores them (nulls and all).

    Returns it prepared, with `correction` and `predicted_gap_min` added, in input order.
    """
    if not hasattr(model, "transform"):  # a numpy forest: no Spark needed, same inputs, same baseline
        return score_local(model, frame)
    prepared = prepare(frame)
    features = prepared[FEATURES_V2].copy()
    # Spark does not promise `toPandas()` returns rows in the order they went in.
    features["_row"] = range(len(features))
    out = cast(pd.DataFrame, model.transform(spark.createDataFrame(features)).select("_row", "prediction").toPandas())
    return _finish(prepared, out.sort_values("_row")["prediction"].to_numpy())


def score_local(forest, frame: pd.DataFrame) -> pd.DataFrame:
    """`score` without Spark: the same trees walked in numpy (`src.ml.gbt_local`), proven
    identical to Spark on every leg (`w10_gbt_local_equivalence.json`). For hosts with no JVM."""
    from src.ml import gbt_local

    prepared = prepare(frame)
    return _finish(prepared, gbt_local.predict(forest, prepared))
