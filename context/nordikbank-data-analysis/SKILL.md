---
name: nordikbank-eda
description: Use whenever the user is exploring, profiling, joining, or engineering features from the NordikBank AML case data. Triggers on EDA-flavored requests — "what does X look like", "distribution of", "are there nulls", "join customers and transactions", "build a feature for cash intensity", "check correlation with the target", or any reference to the case files (customers.csv, transactions.csv, accounts.csv, baselines.csv, alert_history.csv, country_risk.csv) where the goal is understanding or transforming the data rather than training a model. Do NOT use for model training, evaluation, or producing predictions.csv — that is the modeling skill.
---

# NordikBank AML — Exploratory Data Analysis

## Business context

NordikBank is a Nordic retail + corporate bank with ~1.2M customers and ~5M transactions/month. Their current rule-based transaction monitoring system produces a 97% false-positive rate. The Danish FSA's Q3 2025 review is expected to demand more sophisticated monitoring. The case dataset is a sample with confirmed ground-truth labels from a compliance audit (per the brief, this audit was independent of the existing TMS alerts). The end goal is a customer-level risk score that can be explained to a compliance stakeholder.

When producing analysis, ask: would a compliance analyst find this interpretable? If not, flag it.

## File locations

The six case CSVs are typically supplied by the user — either as project files (read them where the user has placed them) or as uploads. Do not assume a fixed path. If unclear where the files live in the current environment, ask the user once and use that path consistently.

Anything you write (cleaned features, lookup tables) goes in a working directory the user can access. Confirm the path with the user the first time you save something — don't pick one silently.

## Data layout

| File | Grain | Key |
|---|---|---|
| `customers.csv` | one row per customer | `customer_id` |
| `accounts.csv` | one row per account (multiple per customer) | `account_id`, FK `customer_id` |
| `baselines.csv` | one row per customer, pre-computed 6-month features | `customer_id` |
| `transactions.csv` | one row per transaction | `transaction_id`, FK `customer_id`, `account_id` |
| `alert_history.csv` | one row per historical TMS alert | `alert_id`, FK `customer_id` |
| `country_risk.csv` | one row per country | `country_code` |

**Target**: `customers.suspicious_activity_confirmed` — binary, 0 or 1.
- Has values for `train` and `val` rows.
- **Null for `test` rows** (this is by design — the panel grades against held-back labels).
- Evaluation is done on `val`, never on `test`.

**Splits**: `customers.split` ∈ {`train`, `val`, `test`}.

## Gotchas to remember every time

- `age`, `declared_annual_income`, `occupation_category` are **null for corporate customers** by design. Don't silently drop these rows. Acceptable treatments: segment personal vs. corporate as separate populations, impute with a documented value, or branch logic. State which one you used.
- `declared_annual_turnover` is null for personal customers — same logic, opposite direction.
- The `baselines.csv` features cover Jul–Dec 2024. If you compute your own features over a different window, document the window and timezone.
- `transactions.counterparty_bank_country` joins to `country_risk.country_code`. Use the country_risk table — don't hardcode FATF lists.
- Class imbalance is severe (true positives are rare). Stratify any sampling and report base rate alongside any aggregate metric.
- Currency: transactions are in their native currency. If aggregating amounts across currencies, convert (with a stated rate) or note the currency mix instead of summing blindly.

## Conventions

- **Library**: pandas by default. Polars is fine if the user prefers it; ask once at the start, then stick with the choice.
- **No silent imputation.** If you fill nulls, say what value and why, in one sentence.
- **State the grain when producing an aggregation.** "This is at customer-month grain" or "one row per customer". Grain confusion is the most common bug in this dataset. Don't force a grain statement when it's not relevant (e.g. a row count of a single table).

## How to push back

- If the user proposes a feature that uses information not available at scoring time (data leakage), stop and explain.
- If the user wants to drop corporate rows because of nulls, point out that corporates are a major risk segment in AML and dropping them defeats the purpose.
- If the user asks for a feature whose business meaning isn't clear, ask what compliance signal it's meant to capture before building it.

## When to ask vs. assume

If the user's request is ambiguous about which split, which grain, or which file path — ask. Don't pick a default and proceed; the cost of asking is one message, the cost of guessing wrong is a wasted analysis.
