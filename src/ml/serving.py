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

from typing import cast

import numpy as np
import pandas as pd
from pyspark.ml import PipelineModel
from pyspark.sql import SparkSession

from src.ml.models_v2 import FEATURES_V2, prepare_serving
from src.ml.models_v2_stepsize import MODEL_PATH
from src.streaming.state import FEATURE_COLUMNS

#: The name the results use for this model (`w7_model_metrics_v2_stepsize.csv`).
MODEL_ID = "v2_gbt_residual_absolute_step1"


def load_model(path=MODEL_PATH) -> PipelineModel:
    if not path.exists():
        raise FileNotFoundError(
            f"No served model at {path} -- run `python -m src.ml.models_v2_stepsize` first."
        )
    return PipelineModel.load(str(path))


def score(spark: SparkSession, model: PipelineModel, frame: pd.DataFrame) -> pd.DataFrame:
    """`frame` holds raw history columns as `features_v2` stores them (nulls and all).

    Returns it prepared, with `correction` and `predicted_gap_min` added, in input order.
    """
    # History arrives as Python values from the stream and the predictor, where a column
    # can be all None in a small batch; as floats it means the same and prepares cleanly.
    history = [c for c in FEATURE_COLUMNS if c in frame.columns]
    prepared = prepare_serving(frame.astype(dict.fromkeys(history, float))).reset_index(drop=True)
    features = prepared[FEATURES_V2].copy()
    # Spark does not promise `toPandas()` returns rows in the order they went in.
    features["_row"] = range(len(features))
    out = cast(pd.DataFrame, model.transform(spark.createDataFrame(features)).select("_row", "prediction").toPandas())
    correction = out.sort_values("_row")["prediction"].to_numpy()
    prepared["correction"] = correction
    prepared["predicted_gap_min"] = prepared["baseline_median"].to_numpy() + np.asarray(correction)
    return prepared
