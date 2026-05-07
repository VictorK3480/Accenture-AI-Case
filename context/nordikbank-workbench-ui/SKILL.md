---
name: nordikbank-workbench-ui
description: Use when the user is designing or building the analyst workbench UI for the NordikBank AML case — the web app that compliance analysts would use to review flagged customers. Triggers on "workbench", "dashboard", "UI", "frontend", "alert queue", "investigation view", "customer drill-down", "score explanation", "demo", or any reference to the third deliverable (the analyst-facing application). Do NOT use for model training (that's the modeling skill) or raw data analysis (that's the EDA skill).
---

# NordikBank AML — Analyst Workbench UI

## Business context

The third deliverable for the NordikBank case is a **web-based analyst workbench** — the tool that compliance analysts would use day-to-day to review the model's flagged customers. This is what gets demoed live to the panel. The brief states explicitly that a live demo of the workbench is worth more than slides of methodology.

The audience for the demo is mixed technical/business. The workbench has to make sense to a compliance analyst, not just a data scientist.

## What the workbench must do

Three required tabs and a modal for customer detail. Everything else is optional polish.

### Tab 1: Alert Queue
Displays **only pending customers** in a prioritized table, ranked by risk score (high to medium). 

**Key:** When an analyst makes a final decision (Cleared or Escalated), the customer is **removed from this queue** and the decision is recorded in the database. The customer then appears in the Customer Database for future reference.

**Left sidebar (alert summary box):**
- Count of **New** alerts (white background)
- Count of **Under Review** (grey background)
- Count of **Cleared** (green background)
- Count of **Escalated** (red background)
- These counts are **global totals** across all statuses. They show the analyst an at-a-glance summary of the entire workload.

**Main content (customer list):**
- Use `st.data_editor` with one row per customer with status = 'new' or 'under_review', sorted descending by risk score
- Columns:
    - Customer name + `residency_country` (smaller, secondary text)
    - `customer_type` (smaller, secondary text below country)
    - Risk score (number + color band: red ≥ 0.6, amber 0.3–0.6, blue < 0.3). Risk color determined by score alone.
    - **Risk flags column**: top 3 risk flags that apply to this customer (colored chips: red for FATF/sanctions/PEP, amber for elevated behavioral signals e.g. high cash ratio, unusual timing). Show only flags that apply; empty if none.
    - "Investigate" button or row selection checkbox (on click/select, opens detail modal and sets status to 'under_review')

### Tab 2: Decision Log
Full chronological record of all analyst decisions (Clear and Escalate actions only — New and Under Review investigations are not logged here until a final decision is made).

**Main content (decision list):**
- Table sorted by decision date (most recent first)
- Each row shows:
  - Customer name + `residency_country` (smaller, secondary text)
  - Decision (status: "Cleared" or "Escalated") with corresponding color
  - Analyst name
  - Decision date/time
  - Click to open detail modal (shows customer context, transactions, analyst reason/note)

### Tab 3: Customer Database
A comprehensive searchable/filterable table of all customers in the dataset — both pending and those with final decisions.

**Purpose:**
- Analysts look up any customer by ID or profile
- Show the full workbench covers the entire customer base

**Filters and Search:**
- Free-text search on `customer_id` or customer name
- Multiselect filters: `customer_type`, `kyc_risk_rating`, `pep_status`, `residency_country`
- Optional: risk score range slider

**Columns per row:**
- Customer name, `customer_type` badge, `residency_country`
- `kyc_risk_rating`, `pep_status`, `sanctions_screening_flag`
- Risk score (from `all_predictions.csv`)
- Current status (New / Under Review / Cleared / Escalated) displayed as badge

**Navigation**: Clicking a row opens the detail modal showing:
- Full transaction history (with highlighted risk drivers)
- Risk profile and reasoning
- **Complete decision history**: all previous Clear and Escalate actions with analyst name, timestamp, and reason
- If customer is currently pending (New/Under Review), the action buttons (Clear/Escalate) remain available
- If customer is already cleared or escalated, show read-only history view

### Modal: Customer Detail & Investigation
Opens when analyst clicks "Status" on any customer. Contains multiple sections, use progressive disclosure (`st.expander`) to avoid overwhelming display on first load. Any example format below is illustrative; adjust labels, fields, and wording to the data actually available in the app:

**1. Header section (always visible):**
- Customer name, type, country, risk score (with color band)
- Risk reason (plain language summary of why flagged)
- `PEP status`, `kyc_risk_rating`, `sanctions_screening_flag`
- **KYC indicator**: Use the actual `kyc_risk_rating` value from `customers.csv` as the customer’s KYC risk signal. Display it as a badge or chip with the same low/medium/high visual language used elsewhere.
- Include `sanctions_screening_flag` prominently in the profile header so analysts can see it without opening any expander.

**2. Why Flagged - Cohort Context section (expander: "Risk Drivers & Peer Comparison"):**
Show the top 3 drivers from `prediction_drivers.csv` with cohort baseline comparison and H1→H2 trend analysis:
- Feature name (display label, not raw), current value, cohort median/mean
- Arrow or badge indicating whether this customer is above/below peer average
- If H1 data available: H1 value and H1→H2 change direction (↑ increased, ↓ decreased, → stable)
- Plain-language summary: e.g., "Cash transaction rate is 3x the median for personal customers (15% vs. 5%)".

**Purpose:** Analysts should immediately see the strongest 2-3 deviations from peer behavior and from prior periods. Features explain *why* the risk score is what it is, not just that it is high.

**3. TMS Alert History section (expander: "Legacy System Alignment"):**
Show recent TMS alerts from `alert_history.csv`, sorted by date descending:

Render the actual trigger names, decisions, and timings present in the data. Keep the section compact: recent alerts first, then a short alignment note stating whether the model and TMS agree or diverge.

**Purpose:** Analysts see if the model is agreeing with or diverging from legacy system; divergence is a signal to dig deeper.

**4. Transaction Velocity & Temporal Patterns section (expander: "Transaction Patterns & Anomalies"):**
Add high-level metrics before the raw transaction list:

Compute the same kinds of summaries from the available transaction fields, but do not force fixed labels or example values.

**Purpose:** Pattern analysis; analysts see "dormant → sudden spike, off-hours, large sums" = classic money laundering profile.

**5. Transaction History section (enhanced with Counterparty Risk):**
Full transaction list, columns: timestamp | amount | counterparty | country | type | channel | risk flags

Flags per row (colored badges):
- ⛔ = FATF non-cooperative territory or EU sanctions list; red background
- ⚠️ = FATF grey list or elevated risk; amber background
- ✓ = Safe/low-risk jurisdiction; green text
- ⭐ NEW = First-time counterparty (higher risk signal)
- (off-hours) = Transaction outside 08:00-18:00 business hours

Sort by amount desc (default); allow toggle to sort by risk flag or timestamp. Do not attempt to map transactions to top-3 drivers—the connection is implicit (e.g., if "high cash ratio" is a driver, see the cash transaction flags below).

**6. Previous investigation history (expander: "Investigation History"):**
- Show all rows from `investigation_history` for this customer, sorted by `changed_at` descending
- For each decision (Clear or Escalate), display:
  - Date and time (when decision was made)
  - Analyst name (who made the call)
  - Decision badge (Cleared 🟢 or Escalated 🔴)
  - Reason / note (analyst's investigation conclusion or reasoning)
- This allows any analyst to see what colleagues found in prior investigations

**Action buttons (at bottom):**
- **If customer is pending** (status = 'new' or 'under_review'):
  - "Clear" button → confirmation modal appears asking for reason/note
  - "Escalate" button → confirmation modal appears asking for reason/note
  - Both require non-empty reason before allowing action
- **If customer already has final decision** (status = 'cleared' or 'escalated'):
  - No action buttons; read-only view only
    - Status is immutable; do not provide a re-open action in the UI

**Confirmation modals:**
- On "Clear": "Mark customer as cleared? This closes the investigation. Reason: [text input]"
- On "Escalate": "Formally escalate to compliance? This records a referral. Reason: [text input]"
- Persist action to both `investigation_status` and `investigation_history` tables with timestamp and analyst name
- On save, customer disappears from Alert Queue (since it now has a final status)

Notes on colours and accessibility: Use High (red `#c62828`) / Medium (amber `#e65100`) / Low (blue `#1565c0`) mapping. Never rely on colour alone — always pair with text label. Maintain contrast for accessibility.

## Data the UI needs at runtime

The workbench is downstream of the modeling pipeline. It needs:
- **Predictions**: Load from `all_predictions.csv` (1,200 rows, all customers across all splits — produced by the modeling skill). Do **not** use `predictions.csv` for the UI; that file has only the 500 test-split rows needed for submission. `prediction_drivers.csv` provides top-3 drivers per customer. If these files don't exist when starting UI work, ask the user how predictions will be supplied — don't fabricate them.
- **Backend model artifacts**: the model integrated into the UI will be provided from the `context/nordikbank-modeling/` folder. The JSON metadata and PKL artifact(s) share the basename `nordikbank_model` (for example, `nordikbank_model.json` and `nordikbank_model.pkl`). Treat these as read-only inputs; do not assume a specific internal schema beyond what the JSON describes.
- **Customer data**: the case CSVs (`customers.csv`, `accounts.csv`, `transactions.csv`, `alert_history.csv`, `country_risk.csv`, `baselines.csv`). Load from wherever the user has placed them.
- **Cohort baselines** for "vs. cohort average" explanations: computed at app startup from `baselines.csv`, grouped by `customer_type`. See the Cohort Baselines section.
- **H1 features** (`features_h1_2024.parquet` or similar): Jan–Jun 2024 per-customer features, same schema as `baselines.csv`. Needed to display the H1→H2 self-deviation comparison. Produced by the modeling pipeline.
- **TMS alert history** (`alert_history.csv`): per-customer transaction monitoring system alerts, trigger rules, and analyst decisions (escalated, SAR_filed, cleared). Used to compare model predictions against legacy TMS flags.
- **Country risk data** (`country_risk.csv`): country-level FATF, EU sanctions, and high-risk jurisdiction flags. Overlay on counterparty countries in transactions.

If any of these are missing when implementing a feature that needs them, stop and confirm with the user — don't invent placeholder data that might survive into a demo.

## Stack

**Streamlit.** Single `app.py` file, no `pages/` directory. Three tabs live in one file. Use a single shared customer investigation detail view; the exact rendering approach is implementation-dependent. No JS required.

Conventions for this app:
- `st.set_page_config(layout="wide")` — the alert queue needs horizontal space.
- Use `st.tabs()` for top-level navigation (Alert Queue, Decision Log, Customer Database).
- Use `st.session_state` to manage modal state: `st.session_state["show_modal"]` and `st.session_state["selected_customer_id"]`.
- Cache all data loads with `@st.cache_data` — reloading `transactions.csv` on every rerender will be slow.
- Use `sqlite3` (stdlib) for persistence — no ORM needed.
- Do not create a `pages/` directory — keep everything in `app.py`.
- For the detail view: keep the analyst on the same page and avoid forcing navigation away from the queue when opening a customer record.

## Customer types

There are **four** customer types in the data: `personal`, `corporate`, `sole_trader`, and `SME`. The UI needs a badge for all four.

- `sole_trader` may have both `declared_annual_income` and `declared_annual_turnover` populated.
- `SME` (Small/Medium Enterprise) may behave like `corporate` for null fields but is its own cohort for baseline comparisons.
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

### Full CSS treatment (Reference Guidance)

**Optional reference for styling.** Call `inject_styles()` once as the very first line inside `app.py` after `st.set_page_config` if you want to match the design system exactly. This is the complete style layer — chrome removal, typography, sidebar, tabs, buttons, cards, inputs, queue table, scrollbar.

```python
def inject_styles():
    st.markdown("""
    <style>
    /* ── 1. Strip Streamlit chrome ── */
    #MainMenu, header, footer, .stDeployButton { visibility: hidden; height: 0; }

    /* ── 2. Typography and page base ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, .stApp {
        font-family: 'Inter', sans-serif;
        background-color: #ffffff;
        color: #0d2137;
    }

    /* ── 3. Sidebar ── */
    [data-testid="stSidebar"] {
        background-color: #0d2137;
        border-right: none;
        padding-top: 0;
    }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stRadio label { color: #a8bdd4 !important; }
    [data-testid="stSidebar"] hr { border-color: #1e3a52 !important; }

    /* ── 4. Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #f5f8fc;
        border-radius: 12px;
        padding: 4px;
        gap: 4px;
        border-bottom: none;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 24px;
        font-weight: 500;
        font-size: 0.9rem;
        color: #546e8a;
        background-color: transparent;
        border: none;
        transition: all 0.15s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff !important;
        color: #0d2137 !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 4px rgba(13,33,55,0.12);
    }
    .stTabs [data-baseweb="tab-highlight"] { display: none; }

    /* ── 5. Buttons ── */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
        font-size: 0.875rem;
        border: 1.5px solid #1565c0;
        color: #1565c0;
        background-color: #ffffff;
        transition: all 0.15s ease;
        padding: 6px 18px;
    }
    .stButton > button:hover {
        background-color: #1565c0;
        color: #ffffff;
        box-shadow: 0 2px 8px rgba(21,101,192,0.25);
        transform: translateY(-1px);
    }
    .stButton > button[kind="primary"] {
        background-color: #1565c0;
        color: #ffffff;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #0d47a1;
        box-shadow: 0 2px 10px rgba(21,101,192,0.35);
    }

    /* ── 6. Cards ── */
    .card {
        background: #ffffff;
        border: 1px solid #dde3ed;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(13,33,55,0.06);
    }
    .card-navy {
        background: #0d2137;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
        color: #ffffff;
    }
    .card-blue {
        background: #e8f1fb;
        border: 1px solid #1565c0;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
    }

    /* ── 7. Metrics ── */
    [data-testid="stMetricValue"] {
        font-size: 1.75rem;
        font-weight: 700;
        color: #0d2137;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem;
        font-weight: 600;
        color: #546e8a;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ── 8. Expander ── */
    [data-testid="stExpander"] {
        border: 1px solid #dde3ed !important;
        border-radius: 10px !important;
        margin-bottom: 8px;
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        font-weight: 500;
        color: #0d2137;
        padding: 12px 16px;
    }
    [data-testid="stExpander"] summary:hover { background-color: #f5f8fc; }

    /* ── 9. Inputs ── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border-radius: 8px;
        border: 1.5px solid #dde3ed;
        font-family: 'Inter', sans-serif;
        color: #0d2137;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #1565c0;
        box-shadow: 0 0 0 3px rgba(21,101,192,0.12);
    }
    .stSelectbox > div > div,
    .stMultiSelect > div > div {
        border-radius: 8px;
        border: 1.5px solid #dde3ed;
    }

    /* ── 10. Alert queue rows ── */
    /* Used with the queue_row_html() helper — replaces st.dataframe */
    .queue-table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
    .queue-row {
        background: #ffffff;
        transition: box-shadow 0.15s ease, transform 0.1s ease;
        cursor: pointer;
    }
    .queue-row:hover {
        box-shadow: 0 3px 12px rgba(13,33,55,0.10);
        transform: translateY(-1px);
    }
    .queue-row td {
        padding: 14px 16px;
        border-top: 1px solid #f0f4f8;
        border-bottom: 1px solid #f0f4f8;
        font-size: 0.9rem;
    }
    .queue-row td:first-child {
        border-left: 1px solid #f0f4f8;
        border-radius: 10px 0 0 10px;
        padding-left: 8px;
    }
    .queue-row td:last-child {
        border-right: 1px solid #f0f4f8;
        border-radius: 0 10px 10px 0;
    }
    .risk-bar-high     { border-left: 4px solid #c62828 !important; }
    .risk-bar-elevated { border-left: 4px solid #e65100 !important; }
    .risk-bar-low      { border-left: 4px solid #1565c0 !important; }

    /* ── 11. Dividers and spacing ── */
    hr { border: none; border-top: 1px solid #dde3ed; margin: 20px 0; }
    h1 { font-size: 1.5rem; font-weight: 700; color: #0d2137; }
    h2 { font-size: 1.15rem; font-weight: 600; color: #0d2137; }
    h3 { font-size: 0.95rem; font-weight: 600; color: #546e8a; text-transform: uppercase; letter-spacing: 0.05em; }

    /* ── 12. Scrollbar ── */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #f5f8fc; }
    ::-webkit-scrollbar-thumb { background: #dde3ed; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #546e8a; }
    </style>
    """, unsafe_allow_html=True)
```

### Sidebar branding

Call once per session to render the NordikBank header inside the dark navy sidebar:

```python
def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style="padding: 24px 16px 16px; border-bottom: 1px solid #1e3a52; margin-bottom: 16px;">
            <div style="font-size:0.7rem;font-weight:600;letter-spacing:0.12em;color:#a8bdd4;text-transform:uppercase">
                NordikBank
            </div>
            <div style="font-size:1.1rem;font-weight:700;color:#ffffff;margin-top:2px;">
                AML Workbench
            </div>
        </div>
        """, unsafe_allow_html=True)

        analyst = st.text_input("Analyst name", key="analyst_name",
                                placeholder="Your name")
        st.markdown("---")
        st.caption("Session status")
        # optional: show counts of new / under review / escalated from SQLite
```

### Custom queue table

This HTML helper is reference-only styling guidance. The authoritative queue implementation should use `st.data_editor`; keep this snippet only if you want to understand the older custom-table approach:

```python
# Historical reference only: the queue should be implemented with st.data_editor.
# Do not use the HTML table helper below as the authoritative rendering path.
```

Use `st.data_editor` for the queue. Add a checkbox column for row selection, or use an "Investigate" button column that triggers the modal on click. This is the authoritative queue implementation.

### Card usage

Streamlit widgets rendered between opening and closing div tags pick up the card styling:

```python
st.markdown('<div class="card">', unsafe_allow_html=True)
st.metric("Avg. monthly volume", fmt_dkk(customer["avg_monthly_volume"]),
          help="Average total transaction value per month over the measurement period")
st.markdown('</div>', unsafe_allow_html=True)
```

Keep divs to one level of nesting — deeper nesting breaks Streamlit's layout engine.

### Number and date formatting

Apply consistently everywhere — sloppy formatting on a demo screen breaks analyst trust:

| Data type | Format | Example |
|---|---|---|
| DKK amounts | Thousand-separated, 0dp | `1,234,567 DKK` |
| Percentages | 1 decimal place | `41.3%` |
| Risk scores | 2 decimal places | `0.87` |
| Dates | DD/MM/YYYY | `14/03/2024` |
| Timestamps | DD/MM/YYYY HH:MM | `14/03/2024 09:42` |

```python
def fmt_dkk(v: float) -> str:
    return f"{v:,.0f} DKK"

def fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%" if v <= 1 else f"{v:.1f}%"  # handles both 0.41 and 41.3 inputs

def fmt_date(ts: str) -> str:
    from datetime import datetime
    return datetime.fromisoformat(ts).strftime("%d/%m/%Y")
```

Apply to every table column and metric that shows money, a rate, or a date. Never display raw float values from the CSV.

### Colour accessibility

Blue and red are safer than green/red for colour-blind users (protanopia), but **never rely on colour as the only signal**. Always pair with a text label or icon:

- Risk badges: colour + text ("High risk", "Safe") — not colour alone
- Status badges: colour + text ("Escalated", "Cleared") — not colour alone
- Row highlights: use as secondary reinforcement only, never the primary signal

### Loading states

Data loads are cold on first run even with `@st.cache_data`. Always wrap initial loads in a spinner:

```python
with st.spinner("Loading customer data..."):
    customers = load_customers(DATA_DIR)
    predictions = load_predictions(DATA_DIR)
```

Place spinners at the top of each tab's render function, not at the individual widget level.

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

| Raw name | Display label | Unit | Tooltip (shown on hover) |
|---|---|---|---|
| `pct_cash_transactions` | Cash transaction rate | % | Share of transactions involving cash deposits or withdrawals |
| `pct_international_transactions` | International transaction rate | % | Share of transactions with a counterparty in a foreign country |
| `avg_monthly_volume` | Avg. monthly volume | DKK | Average total transaction value per month over the period |
| `avg_monthly_transaction_count` | Avg. monthly transaction count | count | Average number of transactions per month over the period |
| `max_single_transaction_6m` | Largest single transaction (6m) | DKK | Highest single transaction amount in the measurement window |
| `num_unique_counterparties_6m` | Unique counterparties (6m) | count | Number of distinct counterparties transacted with |
| `transaction_time_entropy` | Transaction timing irregularity | score | How unpredictably spread across hours/days transactions occur — higher means less regular |
| `geographic_spread_score` | Geographic spread | score | Number of distinct countries involved in transactions |
| `dormancy_periods_count` | Dormancy periods | count | Number of periods with no transaction activity |
| `kyc_risk_rating` | KYC risk rating | low/medium/high | Bank's own Know Your Customer risk classification |
| `pep_status` | PEP status | yes/no | Politically Exposed Person — subject to enhanced due diligence |
| `sanctions_screening_flag` | Sanctions flag | yes/no | Customer matched against sanctions screening lists |

Use the Tooltip column as the `help=` parameter on `st.metric()` and as `title=` on HTML-rendered labels. This is the most important accessibility feature for a compliance audience — they will not know what "timing irregularity" means without it.

Add rows as new features are engineered. If a feature name from `prediction_drivers.csv` doesn't appear in this table, show a warning label (`[unknown: raw_name]`) rather than crashing or showing the raw name.

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

Store investigation state and history in SQLite. Database file: `workbench_state.db` in the project root.

```sql
-- Current status per customer
CREATE TABLE IF NOT EXISTS investigation_status (
    customer_id   TEXT PRIMARY KEY,
    status        TEXT CHECK(status IN ('new','under_review','cleared','escalated')) DEFAULT 'new',
    analyst_name  TEXT DEFAULT '',
    analyst_note  TEXT DEFAULT '',
    updated_at    TEXT DEFAULT (datetime('now'))
);

-- History of all status changes (for audit trail)
CREATE TABLE IF NOT EXISTS investigation_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   TEXT NOT NULL,
    previous_status TEXT,
    new_status    TEXT,
    analyst_name  TEXT,
    reason_note   TEXT,
    changed_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (customer_id) REFERENCES investigation_status(customer_id)
);
```

On app startup, run both `CREATE TABLE IF NOT EXISTS` — safe to call every time.

**Current status table:**
- Stores the latest status and reason for each customer
- Updated with `INSERT OR REPLACE` when analyst takes an action

**History table:**
- Appends a row every time status changes
- Allows modal to display "previously cleared by Analyst X on [date] — reason: [note]"
- Enables full audit trail for compliance

**Analyst name and confirmation:**
- Collect analyst name once per session: `st.text_input("Your name", key="analyst_name")` in sidebar or at app start
- Store in `st.session_state`
- When analyst clicks Clear or Escalate, require non-empty reason before allowing action
- Write analyst_name, reason_note, and new status to both tables on save (or skip if status is already finalized)

## Navigation pattern

The entire app lives in `app.py`. Top-level structure:

```python
tab_queue, tab_log, tab_directory = st.tabs([
    "Alert Queue", "Decision Log", "Customer Database"
])
```

### Alert Queue tab
- Render summary box showing counts:
    - **New**: Count of customers with status = 'new'
    - **Under Review**: Count with status = 'under_review'
    - (Do NOT show Cleared/Escalated counts here; those are only in Decision Log)
- Render prioritized customer table using `st.data_editor` (only customers with status = 'new' or 'under_review'), sorted by risk score descending
- On "Investigate" button click or row selection:
    - Set status to 'under_review' in SQLite (immediate update)
    - Set session state to open modal: `st.session_state["show_modal"] = True` and `st.session_state["selected_customer_id"] = customer_id`
    - Update table to reflect new status immediately (must requery)
- When analyst saves a final decision (Clear/Escalate) in the modal, customer disappears from this queue (because status is now finalized)
- Refresh the table and summary counts after action

### Decision Log tab
- Render table of all decisions from `investigation_history` table, sorted by `changed_at` descending
- Columns: customer name, decision (Clear/Escalate), analyst name, date
- On row click, set session state and trigger modal showing context + reason

### Modal rendering
After each table, check session state and render the detail modal if open:
```python
if st.session_state.get("show_modal"):
    cid = st.session_state.get("selected_customer_id")
    render_detail_modal(cid)  # renders header, transactions, history, action buttons
```

The modal stays open until analyst clicks Close or takes an action (Clear/Escalate). On action, refresh table data and close modal.

### Customer Database tab
Same modal interaction pattern — clicking a row opens the detail modal for that customer.

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
| `features_h1_2024.parquet` missing | Show cohort comparison only in "Why flagged". Don't crash; note "H1 baseline unavailable" per driver row. Fall back to H2 only (no trend arrow). |
| `alert_history.csv` missing | Disable "Legacy System Alignment" expander; show message "TMS alert history unavailable." Don't crash. |
| `country_risk.csv` missing | Show transactions without ⛔/⚠️ flags; display "Risk flags unavailable" note. Don't crash. |
| No matching country in country_risk | Use neutral status "⚪ Region not in database" instead of crashing on lookup. |

## Design principles

- **The analyst is not a data scientist.** Explanations in plain language. No raw SHAP plots without translation, no model jargon in the UI.
- **One customer per page** for the investigation view, not a dashboard-of-dashboards. The investigation view is the heart of the demo.
- **Show the evidence, not just the score.** A risk score of 0.87 means nothing without "here's why" — model transparency is the whole regulatory point.
- **Make it skimmable.** An analyst triaging a queue doesn't read paragraphs. Tables, badges, short chips.
- **Progressive disclosure.** Every section shows a summary by default. Detail lives behind an `st.expander`. The panel should never feel overwhelmed by data on first look.
- **Avoid dark patterns.** Don't pre-select "escalate" or hide the "clear" action. The UI should be neutral on outcome.
- **Graceful degradation.** If a data source is missing, don't crash—hide that feature and show a note. The core workflow (Alert Queue → Investigate → Clear/Escalate) must work even if H1 or country_risk data is unavailable.

## What to put in the alert queue row

Columns (scannable in seconds):
- Customer name + country (primary); `customer_type` (secondary, smaller)
- Risk score (number + color band per thresholds above)
- **Risk flags**: top 3 applicable risk flags (colored chips: red for FATF/sanctions/PEP, amber for behavioral signals)
- "Investigate" button or checkbox (opens detail modal and sets status to 'under_review')

Do not put driver features, accounts list, or transactions in the row — that lives in the modal. Keep the table scannable.

### Alert Queue sidebar: Summary box

Above or to the left of the table, render a small box with four metrics:
- **New**: count of customers with status = 'new', white background
- **Under Review**: count with status = 'under_review', grey background
- **Cleared**: count with status = 'cleared', green background
- **Escalated**: count with status = 'escalated', red background

These are clickable or serve as quick reference only — up to UX preference. Recompute on each render by querying the SQLite table.

## Persistence: SQLite Schema

The workbench persists analyst decisions to a local SQLite database. Create these two tables at app startup:

**`investigation_status` table:**
- `customer_id` (TEXT, PRIMARY KEY): unique customer identifier
- `status` (TEXT): one of 'new', 'under_review', 'cleared', 'escalated'. Once set to 'cleared' or 'escalated', status is immutable.
- `analyst_name` (TEXT): name of the analyst who made the final decision (for cleared/escalated). Empty for 'new' or 'under_review'.
- `analyst_note` (TEXT): free-text reason or investigation note for the final decision
- `updated_at` (TIMESTAMP): when this row was last updated
- **Note**: All 1,200 customers are initialized with status='new' on app startup.

**`investigation_history` table (audit trail):**
- `id` (INTEGER, PRIMARY KEY AUTOINCREMENT): unique record ID
- `customer_id` (TEXT, FOREIGN KEY): references `investigation_status.customer_id`
- `previous_status` (TEXT): the status before this change
- `new_status` (TEXT): the status after this change
- `analyst_name` (TEXT): analyst who made the change
- `reason_note` (TEXT): reason or evidence for the change
- `changed_at` (TIMESTAMP): when the change was made

On app startup:
1. Create both tables if they don't exist.
2. Initialize all customers with status='new' (insert or skip if already exists):
    ```sql
    INSERT OR IGNORE INTO investigation_status (customer_id, status) 
    SELECT customer_id, 'new' FROM customers;
    ```
3. All state changes (new → under_review, under_review → cleared/escalated) append a row to `investigation_history` and update `investigation_status`.
4. Never delete rows — the history table is immutable.
5. Once status is set to 'cleared' or 'escalated', it cannot be changed (immutable).

## Customer Database tab

A searchable/filterable table of all customers in the dataset — both pending and those with final decisions.

**Purpose:**
- Analysts look up any customer by ID or profile
- Show the full workbench covers the entire customer base

**What to show per row**: `customer_id`, `customer_type` badge, `residency_country`, `kyc_risk_rating`, `pep_status`, `sanctions_screening_flag`, and risk score from `all_predictions.csv`.

**Filters/Search**: 
- Free-text search on `customer_id`
- Multiselect filter by `customer_type`, `kyc_risk_rating`, `pep_status`
- Optional: risk score range slider

**Navigation**: Clicking a row opens the same detail modal as Alert Queue. Same workflow: review evidence, Clear or Escalate.

**Location**: The third tab in `app.py` (`tab_directory`). Cache the full customer + predictions join with `@st.cache_data`.
