"""The served v2 model without Spark: MLlib's saved trees, evaluated in numpy (WP-04, D-073).

A free host has 512 MB and no JVM; Spark needs both. What the model actually *is*, though,
is 200 regression trees and 200 weights, saved by MLlib as two small parquet files beside
its metadata. This reads those files with pyarrow and walks the trees in numpy, so the
public API can serve the reported model with no JVM at all.

It is held to Spark, not trusted: `python -m src.ml.gbt_local --verify` scores every leg in
`features_v2` both ways and requires identical predictions, and the result is committed as
`benchmarks/raw/w10_gbt_local_equivalence.json`. Two details decide whether the answers are
equal or only close:

* **Splits.** A continuous split sends a row left when `value <= threshold`. Categorical
  splits do not occur in this model (no feature is declared categorical); a model that had
  one is refused at load time rather than walked wrong.
* **The sum.** Spark combines the trees with a BLAS dot product of tree outputs and
  weights, and floating-point addition depends on grouping. The Java BLAS Spark falls back
  to accumulates in four lanes; that grouping reproduces Spark on every leg, and the
  verification run compares it against the alternatives so the choice is measured, not
  assumed (`WEIGHTED_SUM`).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


@dataclass
class Forest:
    feature_names: list[str]
    weights: np.ndarray            # (trees,)
    # Flat node arrays, one row per node across all trees; children are global indices.
    feature: np.ndarray            # split feature, -1 at a leaf
    threshold: np.ndarray
    left: np.ndarray
    right: np.ndarray
    value: np.ndarray              # node prediction (used at leaves)
    roots: np.ndarray              # global index of each tree's root


def _stage(model_dir: Path, prefix: str) -> Path:
    found = sorted((model_dir / "stages").glob(f"*_{prefix}_*"))
    if not found:
        raise FileNotFoundError(f"no {prefix} stage under {model_dir}")
    return found[0]


def load(model_dir: Path) -> Forest:
    """Read a saved `PipelineModel(VectorAssembler, GBTRegressionModel)` without Spark."""
    assembler = _stage(model_dir, "VectorAssembler")
    meta = json.loads(next((assembler / "metadata").glob("part-*")).read_text(encoding="utf-8"))
    feature_names = meta["paramMap"]["inputCols"]

    gbt = _stage(model_dir, "GBTRegressor")
    nodes = pq.read_table(next((gbt / "data").glob("*.parquet"))).to_pylist()
    trees_meta = pq.read_table(next((gbt / "treesMetadata").glob("*.parquet"))).to_pylist()
    weights = np.array([t["weights"] for t in sorted(trees_meta, key=lambda t: t["treeID"])])

    by_tree: dict[int, dict[int, dict]] = {}
    for row in nodes:
        by_tree.setdefault(row["treeID"], {})[row["nodeData"]["id"]] = row["nodeData"]
    n_trees = len(weights)
    if sorted(by_tree) != list(range(n_trees)):
        raise ValueError("tree ids in the data do not match the tree metadata")

    feature: list[int] = []
    left: list[int] = []
    right: list[int] = []
    roots: list[int] = []
    threshold: list[float] = []
    value: list[float] = []
    for tree_id in range(n_trees):
        tree = by_tree[tree_id]
        offset = len(feature)
        index = {node_id: offset + i for i, node_id in enumerate(sorted(tree))}
        roots.append(index[0])
        for node_id in sorted(tree):
            node = tree[node_id]
            value.append(node["prediction"])
            if node["leftChild"] < 0:
                feature.append(-1)
                threshold.append(0.0)
                left.append(-1)
                right.append(-1)
                continue
            split = node["split"]
            if split["numCategories"] != -1:
                raise ValueError(f"tree {tree_id} has a categorical split; this reader handles continuous only")
            feature.append(split["featureIndex"])
            threshold.append(split["leftCategoriesOrThreshold"][0])
            left.append(index[node["leftChild"]])
            right.append(index[node["rightChild"]])
    return Forest(feature_names, weights, np.array(feature), np.array(threshold), np.array(left),
                  np.array(right), np.array(value), np.array(roots))


def to_json(forest: Forest, path: Path) -> None:
    """The forest as gzipped JSON: a host can read it with no parquet and no Spark.
    Floats go through `json` as their shortest round-tripping repr, so nothing moves."""
    import gzip

    payload = {"feature_names": forest.feature_names, **{
        name: getattr(forest, name).tolist()
        for name in ("weights", "feature", "threshold", "left", "right", "value", "roots")}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def from_json(path: Path) -> Forest:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    return Forest(raw["feature_names"], *(np.array(raw[name]) for name in
                  ("weights", "feature", "threshold", "left", "right", "value", "roots")))


def tree_outputs(forest: Forest, x: np.ndarray) -> np.ndarray:
    """(rows, trees) leaf values, walking all rows of one tree at once."""
    x = np.asarray(x, dtype=float)
    out = np.empty((x.shape[0], len(forest.roots)))
    rows = np.arange(x.shape[0])
    for t, root in enumerate(forest.roots):
        node = np.full(x.shape[0], root)
        while True:
            internal = forest.feature[node] >= 0
            if not internal.any():
                break
            idx = rows[internal]
            at = node[internal]
            go_left = x[idx, forest.feature[at]] <= forest.threshold[at]
            node[idx] = np.where(go_left, forest.left[at], forest.right[at])
        out[:, t] = forest.value[node]
    return out


def sequential_sum(outputs: np.ndarray, weights: np.ndarray) -> np.ndarray:
    total = np.zeros(outputs.shape[0])
    for t in range(outputs.shape[1]):
        total = total + outputs[:, t] * weights[t]
    return total


def unrolled_sum(outputs: np.ndarray, weights: np.ndarray, width: int) -> np.ndarray:
    """`width` running accumulators over strided terms, then summed in order, then the tail
    added one at a time -- the shape of an unrolled BLAS `ddot` loop."""
    n = outputs.shape[1]
    body = n - n % width
    acc = [np.zeros(outputs.shape[0]) for _ in range(width)]
    for t in range(0, body, width):
        for lane in range(width):
            acc[lane] = acc[lane] + outputs[:, t + lane] * weights[t + lane]
    total = acc[0]
    for lane in range(1, width):
        total = total + acc[lane]
    for t in range(body, n):
        total = total + outputs[:, t] * weights[t]
    return total


def f2j_sum(outputs: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """netlib-java's F2J `ddot`: the first `n % 5` terms one at a time, then groups of five
    added left to right into one accumulator."""
    n = outputs.shape[1]
    m = n % 5
    total = np.zeros(outputs.shape[0])
    for t in range(m):
        total = total + outputs[:, t] * weights[t]
    for t in range(m, n, 5):
        total = (total + outputs[:, t] * weights[t] + outputs[:, t + 1] * weights[t + 1]
                 + outputs[:, t + 2] * weights[t + 2] + outputs[:, t + 3] * weights[t + 3]
                 + outputs[:, t + 4] * weights[t + 4])
    return total


SUMS = {
    "sequential": sequential_sum,
    "f2j_unroll5": f2j_sum,
    "lanes4": lambda o, w: unrolled_sum(o, w, 4),
    "lanes8": lambda o, w: unrolled_sum(o, w, 8),
}

#: Set from the verification run (`w10_gbt_local_equivalence.json`): four running lanes
#: matched Spark on **26,369 of 26,369** legs, difference 0.0. A plain left-to-right sum
#: matched on only 2,009, every other leg off in its last bits -- close enough to
#: look right, not equal, which is the difference the verification exists to catch.
WEIGHTED_SUM = "lanes4"


def predict(forest: Forest, frame) -> np.ndarray:
    """Predictions for a pandas frame holding every column the assembler named."""
    x = frame[forest.feature_names].to_numpy(dtype=float)
    return SUMS[WEIGHTED_SUM](tree_outputs(forest, x), forest.weights)


def verify(out: Path) -> dict:
    """Score every leg of features_v2 with Spark and with this reader; compare exactly."""
    import pandas as pd

    from src.common import config
    from src.common.spark import get_spark, stop_spark
    from src.ml import serving
    from src.ml.models_v2 import FEATURES_V2, prepare_serving

    frame = pd.read_parquet(config.FEATURES_V2)
    spark = get_spark("gbt-local-verify")
    try:
        spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")
        spark_scored = serving.score(spark, serving.load_model(), frame)
    finally:
        stop_spark(spark)
    prepared = prepare_serving(frame.astype({c: float for c in serving.FEATURE_COLUMNS}))
    forest = load(serving.MODEL_PATH)
    # Verified through the JSON file the public host reads, not only the parquet original.
    exported = config.DATA_DIR / "serving" / "v2_forest.json.gz"
    to_json(forest, exported)
    forest = from_json(exported)
    outputs = tree_outputs(forest, prepared[FEATURES_V2].to_numpy(dtype=float))
    spark_correction = spark_scored["correction"].to_numpy()
    candidates = {}
    for name, fn in SUMS.items():
        local = fn(outputs, forest.weights)
        diff = np.abs(local - spark_correction)
        candidates[name] = {"identical": int((diff == 0).sum()), "max_abs_difference": float(diff.max())}
    best = max(candidates, key=lambda k: (candidates[k]["identical"], -candidates[k]["max_abs_difference"]))
    local_gap = prepared["baseline_median"].to_numpy() + SUMS[best](outputs, forest.weights)
    report = {
        "model": serving.MODEL_ID,
        "legs": len(frame),
        "trees": len(forest.roots),
        "nodes": int(len(forest.value)),
        "summation_candidates": candidates,
        "chosen_summation": best,
        "identical_predictions": candidates[best]["identical"],
        "max_abs_difference_min": candidates[best]["max_abs_difference"],
        "identical_final_predictions": int((local_gap == spark_scored["predicted_gap_min"].to_numpy()).sum()),
        "verified_through": "data/serving/v2_forest.json.gz (the file the public API reads)",
    }
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true", help="compare with Spark on every leg")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/raw/w10_gbt_local_equivalence.json"))
    args = parser.parse_args()
    if args.verify:
        report = verify(args.out)
        print(json.dumps(report, indent=2))
        return 0 if report["identical_predictions"] == report["legs"] else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
