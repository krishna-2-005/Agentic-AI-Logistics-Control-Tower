# After a person has filled the sheets

Three human results are waiting on people. Each has a one-command path from the filled file to the number in the paper. Nothing here
runs without the filled files, and the numbers it writes are real only if real people filled them. (The tests use synthetic sheets to
prove the pipeline works; those are tests, never results.)

| Waiting on | Filled file | Command | Writes | Then |
|---|---|---|---|---|
| a second labeller of assistant answers | the groundedness sheet with `verdict` filled | `python -m src.ml.groundedness --agreement docs/human_tasks/second_labeller_groundedness_sheet.csv` | `benchmarks/raw/w7_groundedness_agreement.json` | add the kappa to `results_freeze.ENTRIES`, re-cut the freeze, `make numbers`, rebuild the papers |
| two labellers of order emails | two copies of the order sheet with `label` filled | `python -m src.ml.human_sheets --agreement a.csv b.csv` | `benchmarks/raw/b7_order_label_agreement.json` | same |
| phone photographs | ten photographs, redacted, with `truth.csv` (`phone_photo_protocol.md`) | `python -m src.ml.eval_extraction --docs <photo dir> --manifest <truth.csv> --out <dir>` (the evaluator takes these three options; check that the truth file matches the manifest format in `phone_photo_protocol.md` before relying on it) | a photo evaluation file | report beside the synthetic-document accuracy, never instead of it |
| the user test | the filled SUS forms (`user_test_script.md`) | compute the SUS score by the formula in the script | a table in the paper's evaluation | state n = 3 and that it is a usability smoke test |

A kappa below 0.6 is a result about the task, not a failure of the labellers: report it, and say what disagreed (the sheets keep
the reasons).
