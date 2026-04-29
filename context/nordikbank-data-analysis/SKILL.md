---
name: nordikbank-eda
description: Use whenever the user is exploring, profiling, joining, or engineering features from the NordikBank AML case data. Triggers on EDA-flavored requests — "what does X look like", "distribution of", "are there nulls", "join customers and transactions", "build a feature for cash intensity", "check correlation with the target", or any reference to the case files (customers.csv, transactions.csv, accounts.csv, baselines.csv, alert_history.csv, country_risk.csv) where the goal is understanding or transforming the data rather than training a model. Do NOT use for model training, evaluation, or producing predictions.csv — that is the modeling skill.
---

# NordikBank AML — Exploratory Data Analysis

## Business context

NordikBank is a Nordic retail + corporate bank with ~1.2M customers and ~5M transactions/month at full scale. The case dataset is a **sample of 1,200 customers and ~77,000 transactions** covering Jan–Dec 2024 — do not make performance or scale decisions (chunking, sampling, Spark, etc.) based on the full-bank numbers. Their current rule-based transaction monitoring system produces a 97% false-positive rate. The Danish FSA's Q3 2025 review is expected to demand more sophisticated monitoring. Ground-truth labels come from a compliance audit independent of the existing TMS alerts. The end goal is a customer-level risk score that can be explained to a compliance stakeholder.

When producing analysis, ask: would a compliance analyst find this interpretable? If not, flag it.

## File locations

The six case CSVs are typically supplied by the user — either as project files (read them where the user has placed them) or as uploads. Do not assume a fixed path. If unclear where the files live in the current environment, ask the user once and use that path consistently.

Anything you write (cleaned features, lookup tables) goes in a working directory the user can access. Confirm the path with the user the first time you save something — don't pick one silently.

## Data layout

| File                | Grain                                                                         | Key                                              |
| ------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| `customers.csv`     | one row per customer                                                          | `customer_id`                                    |
| `accounts.csv`      | one row per account (multiple per customer)                                   | `account_id`, FK `customer_id`                   |
| `baselines.csv`     | one row per customer, pre-computed 6-month behavioral features (Jul–Dec 2024) | `customer_id`                                    |
| `transactions.csv`  | one row per transaction                                                       | `transaction_id`, FK `customer_id`, `account_id` |
| `alert_history.csv` | one row per historical TMS alert                                              | `alert_id`, FK `customer_id`                     |
| `country_risk.csv`  | one row per country                                                           | `country_code`                                   |

**Target**: `customers.suspicious_activity_confirmed` — binary, 0 or 1.

- Has values for `train` and `val` rows.
- **Null for `test` rows** (by design — the panel grades against held-back labels).
- Evaluation is done on `val`, never on `test`.

**Splits**: `customers.split` ∈ {`train`, `val`, `test`}.

## Key fields by file

### customers.csv

- `customer_type` ∈ {`personal`, `corporate`, `sole_trader`, `SME`} — **four** distinct types. `SME` (89 customers) behaves like `corporate` for null-field purposes but is a separate cohort. Never collapse any type into another without documenting it.
- `kyc_risk_rating` ∈ {`low`, `medium`, `high`}
- `pep_status`, `sanctions_screening_flag` — boolean
- `industry_code` — NACE sector code (corporate and sole_trader only; null for personal). Certain sectors carry elevated AML risk (gambling, money services, cash-heavy retail). Profile the distribution before treating as a raw categorical — cardinality may be high enough to warrant risk-tier grouping.
- `occupation_category` — personal and sole_trader only; null for corporate.
- `declared_annual_income` — personal and sole_trader; null for corporate.
- `declared_annual_turnover` — corporate and sole_trader; null for personal.
- `residency_country`, `nationality` — join to `country_risk` for risk enrichment.

### accounts.csv

- `account_type` ∈ {`current`, `savings`, `business`} — a personal customer holding a business account is worth flagging.
- `avg_monthly_balance_6m`, `avg_monthly_inflow_6m`, `avg_monthly_outflow_6m` — pre-aggregated balance features; can be used directly or as a baseline for deviation.

### transactions.csv

- `amount` — can be negative in this dataset (outflows). Clarify whether you're summing signed amounts or absolute values; never mix without noting it.
- `transaction_type` — categories include standing_order, direct_debit, wire_transfer, cash_deposit, etc. Profile the distribution; cash-type transactions are the core AML signal.
- `channel` — online_banking, branch, ATM, etc. Branch and ATM cash transactions carry higher risk.
- `status` — includes `approved`, `declined`, and potentially others. A high rate of declined transactions is an AML signal (structuring attempts, velocity checks). **Do not filter out declined rows.**
- `counterparty_bank_country` — join to `country_risk.country_code`. Many transactions will have no counterparty country (domestic or missing); treat nulls as a separate category, don't drop.
- `merchant_category_code` — MCC codes; cash advances, gambling, and money transfer MCCs are elevated risk. High cardinality — group into risk tiers rather than one-hot encoding.
- `reference_text_length` — character count of the payment reference field. Very short references on large transactions (length 2–5) are a structuring signal.
- `is_recurring` — recurring transactions are generally lower risk; non-recurring large transfers merit more scrutiny.

### baselines.csv

Pre-computed behavioral features covering **Jul–Dec 2024** — this is the **most recent** (scoring-period) window. `transactions.csv` covers **Jan–Dec 2024** in full. For self-deviation features, the non-overlapping historical window available is **Jan–Jun 2024**: compute features from transactions in that window and compare to baselines. The deviation captures how behavior changed from H1 to H2 2024.

### alert_history.csv

- `trigger_rule` — which rule fired (threshold, structuring, etc.)
- `analyst_decision` ∈ {`escalated`, `closed`, `SAR_filed`, ...}
- `investigation_time_minutes` — can be aggregated per customer as a behavioral feature.

### country_risk.csv

- `fatf_status` — `compliant` vs. non-compliant (or grey list)
- `eu_high_risk_list` — boolean
- `corruption_perception_index` — numeric score; can be used as a continuous feature rather than binned.

## Gotchas to remember every time

- `age`, `declared_annual_income`, `occupation_category` are **null for corporate and SME customers** by design. Don't silently drop these rows. Acceptable treatments: segment all four customer types separately, impute with a documented value, or branch logic. State which one you used.
- `declared_annual_turnover` is null for personal customers — same logic, opposite direction.
- **`sole_trader`** has both `declared_annual_income` and `declared_annual_turnover` populated. It is a distinct type — don't collapse it into personal or corporate for any analysis that touches either income field.
- **`SME`** (Small/Medium Enterprise) is a fourth type; treat like `corporate` for null-field logic but keep as its own cohort in any segment-level analysis.
- The `baselines.csv` features cover Jul–Dec 2024. If you compute your own features over a different window, document the window and timezone.
- `transactions.counterparty_bank_country` joins to `country_risk.country_code`. Use the country_risk table — don't hardcode FATF lists.
- Class imbalance is severe (true positives are rare). Stratify any sampling and report base rate alongside any aggregate metric.
- Currency: transactions are in their native currency. If aggregating amounts across currencies, convert (with a stated rate) or note the currency mix instead of summing blindly.
- `transactions.amount` can be negative. Use absolute value or split by direction when computing volume — never sum signed amounts and call it "volume."
- Don't filter out `status = 'declined'` transactions during EDA. Declined patterns are signal, not noise.

## tsfresh usage

tsfresh is appropriate for extracting **time-series features** from the transaction series — things like amount volatility, trend, periodicity, and acceleration of activity over time. Follow this sequence:

1. Complete EDA first — understand distributions, nulls, currency mix, and customer type breakdowns before feeding data to tsfresh.
2. Build core manual features first (cash intensity, counterparty network, geographic spread, income consistency) — these require table joins and business logic that tsfresh cannot handle.
3. Apply tsfresh on top, using `RelevantFeatureAugmenter` to filter down to statistically significant features only. Run it on **approved transactions only**, with currency and customer type documented.
4. Every tsfresh feature carried into the model must have a compliance narrative — "this captures accelerating transaction volume" not just a feature name. Drop any that cannot be explained.

## Conventions

- **Library**: pandas by default. Polars is fine if the user prefers it; ask once at the start, then stick with the choice.
- **No silent imputation.** If you fill nulls, say what value and why, in one sentence.
- **State the grain when producing an aggregation.** "This is at customer-month grain" or "one row per customer." Grain confusion is the most common bug in this dataset. Don't force a grain statement when it's not relevant (e.g. a row count of a single table).

## Expected outputs

EDA work in this project typically produces one or more of:

- **Feature tables** — customer-level aggregations ready for modeling, saved as `features_v{N}.parquet` (versioned). Coordinate naming and version number with the modeling skill.
- **Profiling summaries** — null counts, distributions, class-stratified stats. Save these where the user can revisit them; don't just print to stdout.
- **Lookup/enrichment tables** — e.g. customer + country_risk join, industry risk tiers.

Confirm the output location with the user before saving anything.

## How to push back

- If the user proposes a feature that uses information not available at scoring time (data leakage), stop and explain.
- If the user wants to drop corporate rows because of nulls, point out that corporates are a major risk segment in AML and dropping them defeats the purpose.
- If the user asks for a feature whose business meaning isn't clear, ask what compliance signal it's meant to capture before building it.
- If the user wants to filter out `declined` transactions, push back — declined patterns are signal, not noise.
- If the user proposes a self-deviation feature using a window that overlaps with `baselines.csv` (Jul–Dec 2024), flag the overlap before building.

## When to ask vs. assume

If the user's request is ambiguous about which split, which grain, or which file path — ask. Don't pick a default and proceed; the cost of asking is one message, the cost of guessing wrong is a wasted analysis.
