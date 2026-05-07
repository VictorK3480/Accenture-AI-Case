# NordikBank AML — Accenture Case

## What this project is

A data science case competition. The task is to build a customer-level AML (Anti-Money Laundering) risk scoring system for NordikBank, a Nordic retail and corporate bank whose current rule-based system produces a 97% false-positive rate.

There are three deliverables:
1. **Exploratory data analysis and feature engineering** — understand the data, build customer-level features
2. **Predictive model** — customer-level risk score (AUC-ROC graded), submitted as `predictions.csv`
3. **Analyst workbench** — a Streamlit web app demoed live to a mixed technical/business panel

## Skill files — read before working in each area

Each deliverable has a skill file with domain knowledge, conventions, gotchas, and code patterns. **Read the relevant file before starting any work in that area.** Do not rely on memory from a previous session.

| You are working on | Read this file first |
|---|---|
| Data exploration, feature engineering, joining CSVs | `context/nordikbank-data-analysis/SKILL.md` |
| Model training, evaluation, predictions.csv, SHAP | `context/nordikbank-modeling/SKILL.md` |
| Streamlit UI, alert queue, investigation view, demo | `context/nordikbank-workbench-ui/SKILL.md` |

If a task spans two areas (e.g. producing driver output for the UI while modeling), read both files.

## Data files

The six case CSVs are in `data/`. Ask the user if anything is missing or the path is unclear — do not assume.

| File | Contents |
|---|---|
| `data/customers.csv` | 1,200 customers, target label, split assignment |
| `data/accounts.csv` | Account-level data, multiple per customer |
| `data/transactions.csv` | 77,384 transactions, Jan–Dec 2024 |
| `data/baselines.csv` | Pre-computed 6-month features per customer (Jul–Dec 2024) |
| `data/alert_history.csv` | Historical TMS alerts per customer |
| `data/country_risk.csv` | Country-level FATF and EU risk flags |

## Universal facts — always apply

- **Four customer types**: `personal` (864), `corporate` (100), `sole_trader` (147), `SME` (89). Never collapse types; each is its own cohort.
- **Three splits**: `train` (500), `val` (200), `test` (500). The target label is null for test rows by design.
- **Submission**: 500 rows, one per test customer, columns `customer_id` and `predicted_probability`.
- **Do not fabricate data.** If a required file is missing (predictions, driver output, H1 features), stop and ask the user how it will be supplied.
- **Do not assume file paths** beyond the `data/` directory above. Confirm with the user once when saving outputs.
