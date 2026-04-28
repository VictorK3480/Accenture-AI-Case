---
name: nordikbank-workbench-ui
description: Use when the user is designing or building the analyst workbench UI for the NordikBank AML case — the web app that compliance analysts would use to review flagged customers. Triggers on "workbench", "dashboard", "UI", "frontend", "alert queue", "investigation view", "customer drill-down", "score explanation", "demo", or any reference to the third deliverable (the analyst-facing application). Do NOT use for model training (that's the modeling skill) or raw data analysis (that's the EDA skill).
---

# NordikBank AML — Analyst Workbench UI

## Business context

The third deliverable for the NordikBank case is a **web-based analyst workbench** — the tool that compliance analysts would use day-to-day to review the model's flagged customers. This is what gets demoed live to the panel. The brief states explicitly that a live demo of the workbench is worth more than slides of methodology.

The audience for the demo is mixed technical/business. The workbench has to make sense to a compliance analyst, not just a data scientist.

## What the workbench must do

Four required views. Everything else is optional polish.

1. **Prioritized alert queue** — list of customers ranked by predicted probability, descending. Show enough at-a-glance to triage: customer ID, type badge, risk score, top 2–3 driver features, and a status (new / under review / cleared / escalated).

2. **Customer investigation view** — a single page with three sections: (a) KYC header, (b) score explanation ("why flagged" in plain language with H1→H2 self-deviation and cohort comparisons), (c) evidence tabs (accounts, transactions, alerts). Views 2 and 3 are **not separate pages** — they are sections within one investigation page. Do not build a standalone Score Explanation page.

4. **Investigation workflow** — the analyst can mark a customer as cleared, under review, or escalated, and add a free-text note. Persist this to SQLite so a refresh doesn't wipe state. Pure in-memory state will be lost on reload, which is fatal during a live demo.

5. **Customer directory** *(optional, high demo value)* — a searchable table of all customers, not just flagged ones. Lets analysts look up a customer proactively rather than waiting for them to appear in the queue. See the Customer Directory section.

## Data the UI needs at runtime

The workbench is downstream of the modeling pipeline. It needs:
- **Predictions**: Load from `all_predictions.csv` (1,200 rows, all customers across all splits — produced by the modeling skill). Do **not** use `predictions.csv` for the UI; that file has only the 500 test-split rows needed for submission. `prediction_drivers.csv` provides top-3 drivers per customer. If these files don't exist when starting UI work, ask the user how predictions will be supplied — don't fabricate them.
- **Customer data**: the case CSVs (`customers.csv`, `accounts.csv`, `transactions.csv`, `alert_history.csv`, `country_risk.csv`, `baselines.csv`). Load from wherever the user has placed them.
- **Cohort baselines** for "vs. cohort average" explanations: computed at app startup from `baselines.csv`, grouped by `customer_type`. See the Cohort Baselines section.
- **H1 features** (`features_h1_2024.parquet`): Jan–Jun 2024 per-customer features, same schema as `baselines.csv`. Needed to display the H1→H2 self-deviation comparison in the investigation view. Produced by the modeling pipeline alongside the driver file.

If any of these are missing when implementing a feature that needs them, stop and confirm with the user — don't invent placeholder data that might survive into a demo.

## Stack

**Streamlit.** Single `app.py` file, no `pages/` directory. All views live in one file as tabs. No JS required.

Conventions for this app:
- `st.set_page_config(layout="wide")` — the alert queue needs horizontal space.
- Use `st.tabs()` for top-level navigation between the three main views.
- Use `st.session_state` to share the selected customer between tabs.
- Cache all data loads with `@st.cache_data` — reloading `transactions.csv` on every rerender will be slow.
- Use `sqlite3` (stdlib) for persistence — no ORM needed.
- Do not create a `pages/` directory — keep everything in `app.py`.

## Customer types

There are **four** customer types in the data: `personal` (864), `corporate` (100), `sole_trader` (147), `SME` (89). The UI needs a badge for all four.

- `sole_trader` has both `declared_annual_income` and `declared_annual_turnover` populated.
- `SME` (Small/Medium Enterprise) behaves like `corporate` for null fields but is its own cohort.
- For cohort comparisons, each type is its own cohort. Never merge types.
- Anywhere the skill previously said "personal/corporate", apply the same logic to `sole_trader` and `SME`.

## Design system

The app uses a **white and dark blue** palette. Blue signals safety; red signals risk. Sleek, minimal, round corners throughout.

### Color palette

| Role | Hex | Used for |
|---|---|---|
| Navy (primary) | `#0d2137` | Page text, headers, sidebar background |
| Mid blue | `#1565c0` | Safe badges, primary buttons, links |
| Light blue tint | `#e8f1fb` | Low-risk row highlight, card backgrounds |
| White | `#ffffff` | Page background, card surfaces |
| Off-white | `#f5f8fc` | Secondary background (metric areas) |
| Amber | `#e65100` | Elevated-risk badges |
| Red | `#c62828` | High-risk badges, alert banners |
| Light red tint | `#ffebee` | High-risk row highlight |
| Border | `#dde3ed` | Card outlines, dividers |
| Muted text | `#546e8a` | Secondary labels, timestamps |

### Streamlit theme config

Place in `.streamlit/config.toml` in the project root:
```toml
[theme]
primaryColor     = "#1565c0"
backgroundColor  = "#ffffff"
secondaryBackgroundColor = "#f5f8fc"
textColor        = "#0d2137"
font             = "sans serif"
```

### Round-corner card pattern

Streamlit widgets can't be placed inside HTML elements, but wrapping divs with a CSS class applied before/after works for visual grouping:

```python
# Call once at app startup to inject styles
def inject_styles():
    st.markdown("""
    <style>
    .card {
        background: #ffffff;
        border: 1px solid #dde3ed;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .card-blue {
        background: #e8f1fb;
        border: 1px solid #1565c0;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    </style>
    """, unsafe_allow_html=True)
```

Use `st.markdown('<div class="card">', unsafe_allow_html=True)` before a section and `st.markdown('</div>', unsafe_allow_html=True)` after it. Keep divs shallow — nesting them deeply breaks Streamlit's layout engine.

### Progressive disclosure

Use `st.expander()` for optional detail. Default: collapsed. Label should say what's inside, not "More info":

```python
with st.expander("Full transaction breakdown (30 rows)"):
    st.dataframe(transactions_df)

with st.expander("Raw SHAP values"):
    st.dataframe(shap_df)
```

Every section that has a "summary view" and a "detail view" should follow this pattern — show the summary by default, put the detail behind an expander. This keeps the page clean for a panel scan while letting the presenter drill down on demand.

## Risk score color thresholds

Use these bands consistently across the queue and investigation view. **Blue = safe, red = risk** — matches the overall design system.

| Band | Threshold | Background | Text |
|---|---|---|---|
| High risk | score ≥ 0.6 | `#c62828` | white |
| Elevated | 0.3 ≤ score < 0.6 | `#e65100` | white |
| Low / Safe | score < 0.3 | `#1565c0` | white |

These are display thresholds only — no action is implied by the color. Update this table and the badge helper together if breakpoints change.

```python
def score_badge(score: float) -> str:
    color = "#c62828" if score >= 0.6 else "#e65100" if score >= 0.3 else "#1565c0"
    return (
        f'<span style="background:{color};color:white;'
        f'padding:3px 10px;border-radius:20px;font-weight:600;font-size:0.9em">'
        f'{score:.2f}</span>'
    )
# render with st.markdown(score_badge(s), unsafe_allow_html=True)
```

`border-radius:20px` gives a pill shape consistent with the round-corner design language.

## Feature display names

Never show raw column names in the UI. Map to analyst-readable labels using this table:

| Raw name | Display label | Unit |
|---|---|---|
| `pct_cash_transactions` | Cash transaction rate | % |
| `pct_international_transactions` | International transaction rate | % |
| `avg_monthly_volume` | Avg. monthly volume | DKK |
| `avg_monthly_transaction_count` | Avg. monthly transaction count | count |
| `max_single_transaction_6m` | Largest single transaction (6m) | DKK |
| `num_unique_counterparties_6m` | Unique counterparties (6m) | count |
| `transaction_time_entropy` | Transaction timing irregularity | score |
| `geographic_spread_score` | Geographic spread | score |
| `dormancy_periods_count` | Dormancy periods | count |
| `kyc_risk_rating` | KYC risk rating | low/medium/high |
| `pep_status` | PEP status | yes/no |
| `sanctions_screening_flag` | Sanctions flag | yes/no |

Add rows as new features are engineered by the modeling pipeline. If a feature name from `prediction_drivers.csv` doesn't appear in this table, show a warning label (e.g. `[unknown: raw_name]`) rather than silently displaying the raw name or crashing.

## Cohort baselines

Cohort = `customer_type`. Compute once at app startup, cache, and reuse for all "vs. cohort average" comparisons.

```python
@st.cache_data
def load_cohort_baselines(baselines_path: str, customers_path: str) -> pd.DataFrame:
    baselines = pd.read_csv(baselines_path)
    customer_types = pd.read_csv(customers_path)[["customer_id", "customer_type"]]
    merged = baselines.merge(customer_types, on="customer_id")
    return merged.groupby("customer_type").mean(numeric_only=True)
```

The returned DataFrame is indexed by `customer_type` (`personal`, `corporate`, `sole_trader`, `SME`). Look up a customer's cohort by their `customer_type` value — never compare across cohorts.

## Persistence schema

Store investigation state in SQLite. Database file: `workbench_state.db` in the project root — confirm location with the user once, then use consistently.

```sql
CREATE TABLE IF NOT EXISTS investigation_status (
    customer_id  TEXT PRIMARY KEY,
    status       TEXT CHECK(status IN ('new','under_review','cleared','escalated')) DEFAULT 'new',
    analyst_note TEXT DEFAULT '',
    updated_at   TEXT DEFAULT (datetime('now'))
);
```

On app startup, run `CREATE TABLE IF NOT EXISTS` — this is safe to call every time. Default status for customers absent from the table is `new`. Use `INSERT OR REPLACE` to upsert. Never delete rows.

## Navigation pattern

The entire app lives in `app.py`. Top-level structure:

```python
tab_queue, tab_investigation, tab_directory = st.tabs([
    "Alert Queue", "Investigation", "Customer Directory"
])
```

**Moving from queue to investigation**: `st.tabs()` cannot be switched programmatically — the user clicks the tab manually. Make this friction-free during the demo by showing a clear prompt after selecting a customer:

```python
# Inside tab_queue, on the "Investigate" button:
if st.button("Investigate", key=f"inv_{customer_id}"):
    st.session_state["selected_customer_id"] = customer_id
    st.success(f"Customer {customer_id} selected — click the Investigation tab above.")
```

**Inside the investigation tab**, always guard against no selection:

```python
with tab_investigation:
    customer_id = st.session_state.get("selected_customer_id")
    if not customer_id:
        st.info("Select a customer from the Alert Queue to begin an investigation.")
        st.stop()
    # ... render investigation view
```

No `st.switch_page`, no `pages/` directory, no back buttons — the tab bar is the navigation.

## Empty states

Handle these explicitly — they are the states most likely to occur during demo setup:

| Situation | What to show |
|---|---|
| `predictions.csv` not found | Red banner: "Predictions not found — run the modeling pipeline first." Do not let it fall through to a stack trace. |
| `prediction_drivers.csv` missing | "Driver data unavailable — showing score only" in the investigation view. Don't crash. |
| Alert queue is empty (all cleared/escalated) | "No unreviewed customers." + a toggle to show all statuses. |
| Customer has no prior alerts | "No prior alerts" in the Historical Alerts tab. Not an empty table, not an error. |
| Customer has no transactions in the sample | "No transactions in sample window" in the Transactions tab. |
| Feature name not in display table | Warning label `[unknown: raw_name]` — visible enough to catch during a demo run-through. |
| `features_h1_2024.parquet` missing | Show cohort comparison only in "Why flagged". Don't crash; note "H1 baseline unavailable" per driver row. |

## Design principles

- **The analyst is not a data scientist.** Explanations in plain language. No raw SHAP plots without translation, no model jargon in the UI.
- **One customer per page** for the investigation view, not a dashboard-of-dashboards. The investigation view is the heart of the demo.
- **Show the evidence, not just the score.** A risk score of 0.87 means nothing without "here's why" — model transparency is the whole regulatory point.
- **Make it skimmable.** An analyst triaging a queue doesn't read paragraphs. Tables, badges, short chips.
- **Progressive disclosure.** Every section shows a summary by default. Detail lives behind an `st.expander`. The panel should never feel overwhelmed by data on first look.
- **Avoid dark patterns.** Don't pre-select "escalate" or hide the "clear" action. The UI should be neutral on outcome.

## What to put in the alert queue row

The panel will scan this in seconds. Columns:
- Customer ID + type badge (`personal` / `corporate` / `sole_trader` / `SME`)
- Risk score (number + color band per thresholds above)
- 2–3 short driver chips (e.g. "High cash rate", "FATF-grey counterparty", "PEP") — from `prediction_drivers.csv`, labels from the display name table
- Country (`residency_country`)
- Status badge

Don't put 12 columns. Don't put the full SHAP breakdown. That's the next click.

## What to put in the investigation view

Three sections, top to bottom:

**1. Header** — KYC summary: customer ID, type, country, registration date, occupation/industry. Status pills for PEP, sanctions flag, KYC risk rating, high-risk country (look up via `country_risk.csv`).

**2. Why flagged** — top contributing features in plain language. Show *two* comparisons per driver:
- **H1 → H2 self-deviation**: H1 (Jan–Jun 2024) value from `features_h1_2024.parquet`, H2 (Jul–Dec 2024) value from `baselines.csv`. Format: "[Display label]: [H1 value] → [H2 value]". This is the behavioral change signal.
- **vs. cohort average**: H2 value vs. cohort mean from the precomputed cohort baselines. Format: "cohort avg: [cohort value]"

**Important**: `prediction_drivers.csv` tells you *which* features drove the prediction and their SHAP values. It does **not** carry the raw H1/H2 absolute values — look those up directly from `features_h1_2024.parquet` and `baselines.csv` by customer_id + feature_name. For deviation-ratio features (e.g. `cash_rate_deviation_h1_h2`), display the underlying H1 and H2 absolute values, not the ratio itself.

If a driver feature has no H1 entry (e.g. a feature only computable from baselines, not from transactions), show cohort comparison only and note the absence of a personal H1 baseline.

**3. Evidence tabs** — nested `st.tabs()` *within* the investigation tab, not top-level:

- **Accounts** — show these columns from `accounts.csv` for the selected customer:
  `account_id`, `account_type`, `opening_date`, `currency`, `avg_monthly_balance_6m`, `avg_monthly_inflow_6m`, `avg_monthly_outflow_6m`

- **Recent Transactions** — show 5–8 highest-`|amount|` rows by default. Put the full 30-row sample behind `st.expander("Show all sampled transactions")`. Columns: `timestamp`, `amount`, `currency`, `transaction_type`, `channel`, `counterparty_bank_country`.

- **Historical Alerts** — show count and most recent alert by default. Full list behind `st.expander("Show all alerts")`. Columns: `alert_date`, `trigger_rule`, `analyst_decision`, `investigation_time_minutes`.

## Customer directory

A searchable table of all customers — not just flagged ones. Useful for:
- Analysts who want to look up a specific customer proactively
- Showing the panel that the tool covers the full customer base, not only the model's top-N

**What to show per row**: `customer_id`, `customer_type` badge, `residency_country`, `kyc_risk_rating`, `pep_status`, `sanctions_screening_flag`, and risk score from `all_predictions.csv` (available for all 1,200 customers).

**Filters**: `customer_type`, `kyc_risk_rating`, `pep_status`, `residency_country`. A free-text search on `customer_id` is enough — don't build a full search engine.

**Navigation**: clicking a row sets `st.session_state["selected_customer_id"]` and shows the same `st.success()` prompt as the queue — user then clicks the Investigation tab.

**Location**: the third tab in `app.py` (`tab_directory`). Cache the full customer + predictions join with `@st.cache_data`.

This view is lower priority than the queue and investigation view. Build it after those two are working. If time is short, cut it — it is polish, not demo-critical.

## Demo discipline

- **Pick one flagged customer in advance** to walk through. Rehearse the click path end-to-end.
- **Have a backup screenshot deck** in case the demo environment fails.
- **Time it.** A two-minute walkthrough beats a ten-minute one.
- **Run through empty states before the demo** — confirm predictions and driver files are present, `workbench_state.db` starts clean or has known state.

## How to push back

- If the user wants to add a feature that's not on the demo path, ask whether it survives a 5-minute demo cut. If not, deprioritize.
- If the user wants to show raw model output (SHAP plots, probability tables) without translation, push for the analyst-language version.
- If the user is building a third dashboard before the investigation view works, redirect — the investigation view is the demo.
- If predictions or driver data don't exist yet, don't generate fake data to "make the UI work" — ask how the data will arrive.

## What "done" looks like

A working Streamlit app where the user can: open the queue, click a high-scored customer, see why they were flagged in plain language with cohort comparisons, see their accounts and a transaction sample, mark them as escalated or cleared, add a note, and have that status persist across a page refresh. Everything else is polish.
