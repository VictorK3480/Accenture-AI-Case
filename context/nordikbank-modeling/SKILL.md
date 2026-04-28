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
- **Customer types**: `personal` (864), `corporate` (100), `sole_trader` (147), `SME` (89) — **four** types. `SME` behaves like `corporate` for null-field purposes but is its own cohort. Never collapse types without documenting it.
- **Imbalance**: positives are rare. Always report base rate alongside metrics.
- See the `nordikbank-eda` skill for the full data layout, field descriptions, and gotchas.

## Hard rules — apply when finalizing a model run

These rules apply when declaring a training run **complete** — i.e. the user is treating this as a real result, not iterating on broken code, debugging a feature pipeline, or sanity-checking that data loads. For exploratory or in-progress code, focus on the immediate task.

1. **Compute AUC-ROC on the val split** before declaring a result complete.
2. **Append the result to a results log.** Default filename `results.csv` in the user's project directory — confirm the location with the user the first time, then keep using it. Schema:
   ```
   timestamp, model_name, features_version, val_auc, train_auc, n_train, n_val, base_rate_train, notes
   ```
   If the file doesn't exist, create it with this header. Never overwrite — only append.
3. **Compare against the previous best** in the results log and state whether this run is better, worse, or within noise (treat ±0.01 AUC as noise unless the user has set a different threshold). If worse, say so plainly — don't bury it.
4. **Verify no leakage on every new feature.** Per the case brief, the ground-truth labels were produced by a compliance audit *independent of* the existing TMS alerts. Features derived from `alert_history.csv` are not target leakage and are fair to use. The leakage risks to watch for: features that include the target itself, features computed using future data relative to the scoring time, or features inadvertently constructed from val/test rows.

## Feature sources

### baselines.csv — use directly

`baselines.csv` provides pre-computed 6-month behavioral features per customer (Jul–Dec 2024). Use these columns as model features directly — don't recompute what's already there:
- `avg_monthly_transaction_count`, `avg_monthly_volume`, `max_single_transaction_6m`
- `pct_international_transactions`, `pct_cash_transactions`
- `num_unique_counterparties_6m`, `transaction_time_entropy`, `geographic_spread_score`, `dormancy_periods_count`

This is also the *reference window* for self-deviation features — see Profile-based features below.

### Alert history

Features from `alert_history.csv` are fair to use (see Hard Rules §4). Useful aggregations per customer:
- Count of historical alerts
- Distribution of analyst decisions (escalated / closed / SAR filed / etc.)
- Mean and recent investigation time
- Rate of alerts escalated vs. closed
- Recency of last alert

### Profile-based features — self-deviation

The strongest AML signal is often *behavioral change*: a customer deviating from their own history. The data supports exactly one non-overlapping comparison:

- **H2 2024 (Jul–Dec)** = `baselines.csv` — the **scoring period**, the most recent window
- **H1 2024 (Jan–Jun)** = compute from `transactions.csv` filtered to `timestamp < 2024-07-01`

Deviation = how much did this customer's behavior change from H1 to H2? A cash rate that doubled from H1 to H2 is a red flag regardless of what the cohort does.

**Self-deviation ratios** — H2 value relative to H1:
```python
# Pattern: (h2 - h1) / (h1 + 1e-6)
# h2 values come from baselines.csv; h1 values computed from transactions Jan–Jun 2024
cash_rate_deviation    = (h2_pct_cash - h1_pct_cash) / (h1_pct_cash + 1e-6)
volume_deviation       = (h2_avg_volume - h1_avg_volume) / (h1_avg_volume + 1e-6)
counterparty_deviation = (h2_n_counterparties - h1_n_counterparties) / (h1_n_counterparties + 1e-6)
frequency_deviation    = (h2_txn_count - h1_txn_count) / (h1_txn_count + 1e-6)
```

Save the H1 feature table (one row per customer, same columns as baselines) as `features_h1_2024.parquet`. The workbench needs this file to display "H1 value → H2 value" for each driver — it cannot reconstruct absolute values from the deviation ratio alone.

**Velocity features** — within the H2 window (month-over-month from transactions Jul–Dec 2024):
- Month-over-month change in transaction volume
- Month-over-month change in unique counterparty count

Name deviation features explicitly (e.g. `cash_rate_deviation_h1_h2`) so the workbench display name table can label them for analysts.

### Country risk

Join `transactions.counterparty_bank_country` to `country_risk.country_code` per transaction, then aggregate to customer level:
- Share of transaction volume to/from FATF non-compliant countries
- Share of transaction volume to/from EU high-risk list countries
- Number of distinct high-risk counterparty countries

Use the `country_risk` table — don't hardcode FATF lists.

Also join `customers.residency_country` and `customers.nationality` to `country_risk` as direct customer-level features.

### Account-level features

Aggregate `accounts.csv` to customer level:
- Number of accounts
- Number of distinct `account_type` values (a personal customer with a business account is unusual)
- Sum or average of `avg_monthly_balance_6m`
- Ratio of total inflow to total outflow across accounts (layering signal)

### KYC and demographic features

Use directly from `customers.csv`:
- `kyc_risk_rating` — encode as ordinal (low=0, medium=1, high=2)
- `pep_status`, `sanctions_screening_flag` — binary
- `customer_type` — four values: `personal`, `corporate`, `sole_trader`, `SME`. Encode; consider separate models per segment if performance warrants it.
- `industry_code` — NACE codes; group high-risk sectors (gambling, money services, cash-heavy retail) into a risk tier rather than one-hot at full cardinality
- `occupation_category` (personal/sole_trader) and `declared_annual_income` vs. volume ratio (income-to-transaction incongruence)

## Modeling conventions

- **Start simple**: logistic regression or a single gradient-boosted baseline before anything fancy. If `results.csv` is empty, the first run should be that baseline. If it's not empty, don't redo the baseline.
- **Library default**: scikit-learn for baselines; LightGBM or XGBoost for the main model. CatBoost is fine if categorical features are heavy. Ask before reaching for deep learning — for ~1,200 customers it's almost never the right answer.
- **Cross-validation**: stratified k-fold on the train split. Report mean ± std AUC.
- **Class imbalance**: try `class_weight='balanced'` or `scale_pos_weight` before resampling. SMOTE on mixed-type tabular data often hurts more than it helps; if used, justify it.
- **Feature versioning**: save the feature table as `features_v{N}.parquet` (versioned) in the directory the user designates. Bump the version when changes are non-trivial.
- **Reproducibility**: set `random_state=42` (or the user's preferred seed — ask once). Do not re-split data; the `split` column is canonical.

## What the workbench needs

The workbench needs two files beyond `predictions.csv`:

**1. `all_predictions.csv`** — probabilities for every customer across all splits (train + val + test), not just the 500 test rows. The demo queue and customer directory display scores for all customers, but `predictions.csv` only covers test.
Schema: `customer_id, predicted_probability` (same as predictions.csv but all 1,200 rows).

**2. `prediction_drivers.csv`** — top-N feature contributions per customer. Schema:

```
customer_id, rank, feature_name, feature_value, shap_value
```

- `rank`: 1 = top driver, 2 = second, 3 = third
- `feature_name`: raw column name — the workbench maps this to display labels and looks up raw values independently
- `feature_value`: this customer's model-input value for that feature (for deviation features this is the ratio, not an absolute value)
- `shap_value`: SHAP contribution (positive = pushes toward suspicious)

**Do not** put cohort means or personal baselines in this file. The workbench retrieves those directly from `baselines.csv` (H2 values), `features_h1_2024.parquet` (H1 values), and the cohort baseline computation at startup. Keeping raw values out of the driver file avoids duplication and keeps it simple.

## Submission format

`predictions.csv` must have exactly:
- 500 rows (one per test customer)
- Two columns: `customer_id`, `predicted_probability`
- Probabilities in [0.0, 1.0]
- No nulls, no duplicates

Validate before declaring submission done:
```python
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

- If the user wants to skip the val check on a final result, push back and run val first.
- If early results land notably above the baseline (e.g. a large AUC jump on the first non-baseline model), suspect leakage before celebrating.
- If the user proposes a complex model and `results.csv` is empty, push for the baseline first.
- If the user wants to chase AUC by adding features that wouldn't survive an audit, say so.
- If a self-deviation feature uses a window that overlaps with the baselines period, flag it before building.

## What "done" looks like

For a finalized training run: val AUC computed → comparison to previous best in `results.csv` → row appended → one sentence on what changed and why.

For a submission: all assertions pass → `predictions.csv` saved (500 test rows) → `all_predictions.csv` saved (1,200 rows, all splits) → `prediction_drivers.csv` saved → `features_h1_2024.parquet` saved → confirmation of all file locations and row counts.
