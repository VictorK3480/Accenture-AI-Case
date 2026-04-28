---
name: nordikbank-modeling
description: Use whenever the user is training, tuning, evaluating, or comparing supervised models for the NordikBank AML case, or producing the predictions.csv submission. Triggers on "train a model", "fit", "evaluate", "AUC", "ROC", "cross-validation", "class imbalance", "hyperparameter", "feature importance", "submission", "predictions.csv", or any reference to model performance against the suspicious_activity_confirmed target. Do NOT use for raw EDA or feature exploration (that's the EDA skill) or for the analyst UI (that's the workbench skill).
---

# NordikBank AML — Modeling

## Business context

NordikBank wants a customer-level risk score that beats their current rule-based TMS (97% false-positive rate) while remaining auditable for the Danish FSA. The case is graded on **AUC-ROC** against held-out test labels — no threshold required. The panel is mixed technical and business, so model choice has to be defensible in plain language.

## The objective

Produce a per-customer probability in [0, 1] that ranks suspicious customers above clean ones. Higher AUC-ROC on the held-out test set wins. Submission is a CSV of 500 rows.

## Data and target

- **Target**: `customers.suspicious_activity_confirmed` — binary.
- **Splits**: `customers.split` ∈ {`train`, `val`, `test`}. Train on `train`, evaluate on `val`, score `test` for submission. The target is null for `test` rows by design — that's normal, not a bug.
- **Imbalance**: positives are rare. Always report base rate alongside metrics.
- See the `nordikbank-eda` skill for the full data layout and gotchas.

## Hard rules — apply when finalizing a model run

These rules apply when declaring a training run **complete** — i.e. the user is treating this as a real result, not iterating on broken code, debugging a feature pipeline, or sanity-checking that data loads. For exploratory or in-progress code, focus on the immediate task.

1. **Compute AUC-ROC on the val split** before declaring a result complete.
2. **Append the result to a results log.** Default filename `results.csv` in the user's project directory — confirm the location with the user the first time, then keep using it. Schema:
   ```
   timestamp, model_name, features_version, val_auc, train_auc, n_train, n_val, base_rate_train, notes
   ```
   If the file doesn't exist, create it with this header. Never overwrite — only append.
3. **Compare against the previous best** in the results log and state whether this run is better, worse, or within noise (treat ±0.01 AUC as noise unless the user has set a different threshold). If worse, say so plainly — don't bury it.
4. **Verify no leakage on every new feature.** Per the case brief, the ground-truth labels were produced by a compliance audit *independent of* the existing TMS alerts. This means features derived from `alert_history.csv` (analyst decisions, alert counts, investigation times) are not target leakage and are fair to use. The leakage risks to actually watch for are: features that include the target itself, features computed using future data relative to the scoring time, or features inadvertently constructed from val/test rows.

## Alert history as features

The user has decided to **treat `alert_history.csv` as feature signal**. Useful aggregations per customer:
- Count of historical alerts
- Distribution of analyst decisions (escalated / closed / SAR filed / etc.)
- Mean and recent investigation time
- Rate of alerts escalated vs closed
- Recency of last alert

These describe past behavior and are not leakage given the brief. If the user proposes deriving a feature that *does* peek at the target (e.g. "did this customer ever get a SAR filed" where SAR-filed status is itself part of the audit), flag it.

## Modeling conventions

- **Start simple**: a logistic regression or single gradient-boosted baseline before anything fancy. If `results.csv` is empty when starting work on this project, the first run should be that baseline. If it's not empty, don't redo the baseline.
- **Library default**: scikit-learn for baselines; LightGBM or XGBoost for the main model. CatBoost is fine if categorical features are heavy. Ask before reaching for deep learning — for ~1,200 customers it's almost never the right answer.
- **Cross-validation**: stratified k-fold on the train split. Report mean ± std AUC.
- **Class imbalance handling**: try `class_weight='balanced'` or `scale_pos_weight` before resampling. SMOTE on this kind of mixed-type tabular data often hurts more than it helps; if used, justify it.
- **Feature engineering**: customer-level features. Aggregate transactions and accounts up to `customer_id`. Save the feature table as `features_v{N}.parquet` (versioned), in the directory the user designates. Bump the version when changes are non-trivial.
- **Reproducibility**: in any new code I write, set `random_state=42` (or whatever seed the user prefers — ask once). Do not re-split data that the user has already split via the `split` column; that column is the canonical split.

## What the workbench needs

The workbench skill expects per-customer top-N feature contributions ("drivers"), not just a probability. When producing predictions for the workbench, also output the top-3 features pushing each prediction up — typically via SHAP or permutation importance. Save these alongside the predictions in a parallel file (e.g. `prediction_drivers.csv`).

## Submission format

`predictions.csv` must have exactly:
- 500 rows (one per test customer)
- Two columns: `customer_id`, `predicted_probability`
- Probabilities in [0.0, 1.0]
- No nulls, no duplicates

Validate before declaring submission done. Pseudocode:
```python
# `preds` is the submission DataFrame
# `test_ids` is the set of customer_id values where customers.split == "test"
assert len(preds) == 500
assert set(preds.columns) == {"customer_id", "predicted_probability"}
assert preds["predicted_probability"].between(0, 1).all()
assert preds["predicted_probability"].notna().all()
assert preds["customer_id"].is_unique
assert set(preds["customer_id"]) == set(test_ids)
```
Replace `test_ids` with the actual variable in your code.

## Explainability

The case is graded partly on whether choices are defensible to a compliance stakeholder. For the chosen model, always be able to produce:
- Top-N feature importances (built-in or permutation-based)
- A SHAP plot or equivalent for a single flagged customer (the workbench will display this)
- A one-paragraph plain-language explanation of *why* the model ranks customer X high

If a model is more accurate but unexplainable, flag the trade-off explicitly. Don't quietly pick the black box.

## How to push back

- If the user wants to skip the val check on what they're treating as a final result, push back and run val first.
- If early results land notably above the baseline (e.g. a large jump on the first non-baseline model), suspect leakage before celebrating. Investigate the new features.
- If the user proposes a complex model and `results.csv` is empty, push for the baseline first — you need something to compare against.
- If the user wants to chase AUC by adding features that wouldn't survive an audit, say so.

## What "done" looks like

For a finalized training run: val AUC computed → comparison to previous best in `results.csv` → row appended → one sentence on what changed and why.

For a submission: all assertions pass → `predictions.csv` saved → confirmation of file location and row count → if drivers were requested, `prediction_drivers.csv` also saved.
