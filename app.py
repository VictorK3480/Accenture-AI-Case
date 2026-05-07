"""NordikBank AML Workbench — Streamlit app.

Three tabs (Alert Queue / Decision Log / Customer Database) plus a shared
investigation modal opened from any of them. Status workflow:

    new  ──Investigate──▶  under_review  ──Clear──▶ cleared (terminal)
                                          ──Escalate──▶ escalated (terminal)

Data sources, risk-flag rules, and persistence are described in
`context/nordikbank-workbench-ui/SKILL.md`.
"""

import sqlite3
import hashlib
import random
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AML Workbench — NordikBank",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ────────────────────────────────────────────────────────────────
DATA_DIR  = Path("data")

# Model artifacts live next to the modeling notebook so it stays the single
# source of truth — re-running the notebook refreshes the workbench.
MODEL_DIR        = Path("context/nordikbank-modeling")
PREDICTIONS_PATH = MODEL_DIR / "all_predictions.csv"
DRIVERS_PATH     = MODEL_DIR / "prediction_drivers.csv"
H1_PATH          = MODEL_DIR / "features_h1_2024.parquet"

DB_PATH = "workbench_state.db"

# Display-only thresholds for risk colour bands.
# Low: < 0.10 (gray), Medium: 0.10–0.50 (amber), High: ≥ 0.50 (red).
RISK_HIGH = 0.50
RISK_MED  = 0.10

# Seeding thresholds. Tuned to this model's compressed score distribution
# (most negatives 0.24–0.29, positives 0.37–0.65) so the seeded demo state
# spreads across all three risk bands instead of clustering at the top.
SEED_HIGH = 0.40   # >= here: high-risk seeded customer (random verdict)
SEED_MED  = 0.30   # >= here and < SEED_HIGH: medium-risk

# Synthetic analyst pool + reason strings used when seeding the historical
# decision log so the demo state looks like a realistic audit trail.
SEED_ANALYSTS = [
    "A. Pedersen", "M. Hansen", "S. Sørensen", "L. Berg",
    "K. Holm",     "T. Lund",   "C. Nielsen",  "P. Mortensen",
]
SEED_REASONS_CLEARED = [
    "Source of funds verified — ongoing relationship",
    "False positive — pattern explained by business model",
    "Customer interview clarified activity",
    "Documentation reviewed and accepted",
    "Behavioural pattern within KYC profile",
    "Cohort-typical activity for industry",
    "Periodic review — no further action required",
]
SEED_REASONS_ESCALATED = [
    "Multiple structuring indicators — referred to FIU",
    "Sanctions overlap — referred to compliance",
    "Source of funds inconsistent with declared profile",
    "Counterparty risk concentration",
    "Repeated dormant→active pattern",
    "PEP-linked exposure exceeded threshold",
    "Layering pattern across multiple counterparties",
]


# ── Feature display labels (raw -> human-readable + unit + tooltip) ─────────
FEATURE_LABELS = {
    # Behavioural baselines (Jul–Dec 2024)
    "pct_cash_transactions": (
        "Cash transaction rate", "%",
        "Share of transactions involving cash deposits or withdrawals"),
    "pct_international_transactions": (
        "International transaction rate", "%",
        "Share of transactions with a counterparty in a foreign country"),
    "avg_monthly_volume": (
        "Avg. monthly volume", "DKK",
        "Average total transaction value per month over the period"),
    "avg_monthly_transaction_count": (
        "Avg. monthly transaction count", "count",
        "Average number of transactions per month over the period"),
    "max_single_transaction_6m": (
        "Largest single transaction (6m)", "DKK",
        "Highest single transaction amount in the measurement window"),
    "num_unique_counterparties_6m": (
        "Unique counterparties (6m)", "count",
        "Number of distinct counterparties transacted with"),
    "transaction_time_entropy": (
        "Transaction timing irregularity", "score",
        "How unpredictably spread across hours/days transactions occur — higher means less regular"),
    "geographic_spread_score": (
        "Geographic spread", "score",
        "Number of distinct countries involved in transactions"),
    "dormancy_periods_count": (
        "Dormancy periods", "count",
        "Number of periods with no transaction activity"),

    # Counterparty / network features
    "num_unique_counterparties": (
        "Unique counterparties", "count",
        "Total distinct counterparties this customer transacted with over the year"),
    "top_counterparty_share": (
        "Top-counterparty concentration", "%",
        "Share of total transactions going to a single counterparty"),
    "one_time_counterparty_count": (
        "One-time counterparties", "count",
        "Counterparties seen exactly once — a layering signal"),

    # Cash & volume
    "cash_transaction_count": (
        "Cash transactions", "count",
        "Number of cash deposits or withdrawals over the period"),
    "cash_volume": (
        "Cash volume", "DKK",
        "Total monetary value moved as cash"),
    "total_transactions": (
        "Total transactions", "count",
        "All approved transactions for this customer over the year"),
    "total_volume": (
        "Total volume", "DKK",
        "Total monetary value moved across all transactions"),
    "max_transaction_amount": (
        "Max transaction amount", "DKK",
        "Largest single approved transaction"),

    # International & country-risk
    "num_international_transactions": (
        "International transactions", "count",
        "Number of approved transactions with a foreign counterparty bank"),
    "num_unique_countries": (
        "Unique counterparty countries", "count",
        "Distinct countries appearing as counterparty bank country"),
    "avg_corruption_index": (
        "Avg. counterparty corruption index", "score",
        "Mean Transparency International corruption score across counterparty countries — higher is more corrupt"),

    # Declined-transaction features
    "decline_rate": (
        "Decline rate", "%",
        "Share of attempted transactions that were declined — repeated declines can signal structuring"),
    "declined_count": (
        "Declined transactions", "count",
        "Number of declined transactions over the period"),
    "declined_volume": (
        "Declined volume", "DKK",
        "Total monetary value of declined transaction attempts"),

    # Account-level
    "avg_inflow": (
        "Avg. inflow per account", "DKK",
        "Average monthly inflow averaged across this customer's accounts"),
    "avg_outflow": (
        "Avg. outflow per account", "DKK",
        "Average monthly outflow averaged across this customer's accounts"),

    # Self-deviation (H1 → H2 2024)
    "volume_deviation_ratio": (
        "Volume change H1→H2", "ratio",
        "(H2 − H1) / H1 of monthly transaction volume"),
    "count_deviation_ratio": (
        "Activity change H1→H2", "ratio",
        "(H2 − H1) / H1 of monthly transaction count"),
    "volume_change_ratio": (
        "Volume change", "ratio",
        "Month-over-month change in transaction volume within the scoring window"),

    # Static KYC
    "kyc_risk_rating": (
        "Risk rating", "low/medium/high",
        "Bank's own customer risk classification"),
    "pep_status": (
        "PEP status", "yes/no",
        "Politically Exposed Person — subject to enhanced due diligence"),
    "sanctions_screening_flag": (
        "Sanctions flag", "yes/no",
        "Customer matched against sanctions screening lists"),
}


# ── Visual tokens ────────────────────────────────────────────────────────────

# Sidebar status cards — neutral dark background, colored numbers only.
STATUS_CARD = {
    "new":          {"bg": "#1e3a52", "fg": "#ffffff", "num_color": "#ffffff",  "label": "New"},
    "under_review": {"bg": "#1e3a52", "fg": "#ffffff", "num_color": "#f9a825",  "label": "Under Review"},
    "cleared":      {"bg": "#1e3a52", "fg": "#ffffff", "num_color": "#2e7d32",  "label": "Cleared"},
    "escalated":    {"bg": "#1e3a52", "fg": "#ffffff", "num_color": "#c62828",  "label": "Escalated"},
}


# ── Style injection ──────────────────────────────────────────────────────────
def inject_styles():
    st.markdown("""
    <style>
    /* ── 1. Strip Streamlit chrome ── */
    #MainMenu, header, footer, .stDeployButton { visibility: hidden; height: 0; }

    /* Pull the main content up to the very top of the viewport so the tabs
       are the first visible element. */
    .main .block-container,
    [data-testid="stMainBlockContainer"],
    [data-testid="block-container"] {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        max-width: 100% !important;
    }

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
    }
    /* Hide the Streamlit-shipped collapse-button bar that pushes content
       down. Without it removed, the brand row sits well below the tabs. */
    [data-testid="stSidebar"] [data-testid="stSidebarHeader"],
    [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebar"] [data-testid="stSidebarNav"],
    [data-testid="stSidebar"] [data-testid="stSidebarNavSeparator"],
    [data-testid="stSidebar"] > header,
    [data-testid="stSidebar"] > div > header,
    [data-testid="stSidebar"] > div:first-child > header {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    /* Strip every container's top padding so the brand has nothing above it. */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebar"] > div:first-child,
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    [data-testid="stSidebar"] section,
    [data-testid="stSidebar"] section[tabindex="-1"],
    [data-testid="stSidebar"] section[tabindex="-1"] > div,
    [data-testid="stSidebar"] section[tabindex="-1"] > div > div:first-child,
    [data-testid="stSidebar"] .block-container {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    [data-testid="stSidebar"] .block-container,
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {
        padding-bottom: 1rem !important;
    }
    /* Brand row gets the same 1rem top padding as the main area, so it
       sits at the same vertical position as the tab bar. */
    .sidebar-brand {
        margin: 0 !important;
        padding: 1rem 16px 14px !important;
        border-bottom: 1px solid #1e3a52;
        margin-bottom: 12px !important;
    }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
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
    .card-blue {
        background: #e8f1fb;
        border: 1px solid #1565c0;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
    }

    /* ── 7. Metrics ── */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 700;
        color: #0d2137;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.7rem;
        font-weight: 600;
        color: #546e8a;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ── 8. Expanders ── */
    [data-testid="stExpander"] {
        border: 1px solid #dde3ed !important;
        border-radius: 10px !important;
        margin-bottom: 8px;
        overflow: hidden;
    }
    [data-testid="stExpander"] summary {
        font-weight: 600;
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

    /* ── 10. Status summary cards (sidebar) ── */
    .status-card {
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 6px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .status-card .label {
        font-size: 0.66rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 700;
        opacity: 0.78;
    }
    .status-card .value {
        font-size: 1.4rem;
        font-weight: 800;
        line-height: 1.1;
        margin-top: 2px;
    }

    /* ── 11. Section headers ── */
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        color: #546e8a;
        text-transform: uppercase;
        margin-bottom: 10px;
        margin-top: 24px;
    }

    /* ── 12. Risk flag chips ── */
    .flag-chip {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.74rem;
        font-weight: 600;
        margin-right: 4px;
        margin-bottom: 2px;
        border: 1px solid currentColor;
    }
    .flag-red    { color: #c62828; background: #ffebee; }
    .flag-amber  { color: #b78a00; background: #fff8e1; }   /* yellow */
    .flag-green  { color: #2e7d32; background: #e8f5e9; }
    .flag-blue   { color: #1565c0; background: #e8f1fb; }   /* neutral fallback */

    /* ── 13. Investigation modal — dialog frame & section labels ── */
    [data-testid="stDialog"] [data-testid="stMarkdownContainer"] h3 {
        font-size: 0.95rem;
        color: #546e8a;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 700;
    }

    /* ── 14. Driver rows in modal — traffic-light palette ── */
    .driver-row {
        background: #e8f5e9;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 8px;
        border-left: 3px solid #2e7d32;
    }
    .driver-row.driver-high     { border-left-color: #c62828; background: #ffebee; }
    .driver-row.driver-elevated { border-left-color: #f9a825; background: #fff8e1; }

    /* ── 15. KYC pill strip in modal header ── */
    .pill {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 6px;
        margin-bottom: 4px;
    }

    /* ── 16. Scrollbar ── */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #f5f8fc; }
    ::-webkit-scrollbar-thumb { background: #dde3ed; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #546e8a; }

    /* ── 17. Headings ── */
    hr { border: none; border-top: 1px solid #dde3ed; margin: 20px 0; }
    h1 { font-size: 1.5rem; font-weight: 700; color: #0d2137; }
    h2 { font-size: 1.15rem; font-weight: 600; color: #0d2137; }
    h3 { font-size: 0.95rem; font-weight: 600; color: #0d2137; }
    </style>
    """, unsafe_allow_html=True)


# ── Format helpers ───────────────────────────────────────────────────────────
def fmt_dkk(v):
    try:
        return f"{float(v):,.0f} DKK"
    except (TypeError, ValueError):
        return "— DKK"

def fmt_pct(v):
    try:
        fv = float(v)
        return f"{fv * 100:.1f}%" if fv <= 1 else f"{fv:.1f}%"
    except (TypeError, ValueError):
        return "—"

def fmt_date(ts):
    if pd.isna(ts) or ts == "" or ts is None:
        return "—"
    try:
        return pd.to_datetime(ts).strftime("%d/%m/%Y")
    except Exception:
        return str(ts)

def fmt_ts(ts):
    if pd.isna(ts) or ts == "" or ts is None:
        return "—"
    try:
        return pd.to_datetime(ts).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(ts)

def fmt_feature_value(feature, value):
    if feature not in FEATURE_LABELS:
        return str(value)
    _, unit, _ = FEATURE_LABELS[feature]
    try:
        fv = float(value)
        if unit == "DKK":
            return fmt_dkk(fv)
        elif unit == "%":
            return fmt_pct(fv)
        elif unit in ("score", "count", "ratio"):
            return f"{fv:.2f}"
        else:
            return str(value)
    except (TypeError, ValueError):
        return str(value)


# ── Badge / band helpers ─────────────────────────────────────────────────────
def risk_band(score):
    if score is None or pd.isna(score):
        return "low"
    return "high" if score >= RISK_HIGH else "elevated" if score >= RISK_MED else "low"

def score_badge(score):
    """Pill-shaped badge for risk score. Traffic-light: gray/amber/red."""
    if score is None or pd.isna(score):
        return '<span style="color:#aaa">—</span>'
    if score >= RISK_HIGH:
        color, label = "#c62828", "High risk"
    elif score >= RISK_MED:
        color, label = "#f9a825", "Medium risk"
    else:
        color, label = "#888888", "Low risk"
    return (f'<span style="background:{color};color:white;'
            f'padding:3px 10px;border-radius:20px;font-weight:600;'
            f'font-size:0.85em">{label}</span>')

def type_badge(ctype):
    return (f'<span style="background:#f1f1f1;color:#546e8a;'
            f'padding:2px 9px;border-radius:20px;font-size:0.72em;'
            f'font-weight:600">{ctype}</span>')

def status_badge(status):
    cfg = STATUS_CARD.get(status, {"bg": "#f5f8fc", "fg": "#546e8a", "label": status})
    return (f'<span style="background:{cfg["bg"]};color:{cfg["fg"]};'
            f'padding:3px 10px;border-radius:20px;font-size:0.78em;'
            f'font-weight:600;border:1px solid {cfg["fg"]}30">{cfg["label"]}</span>')

def get_feature_label(raw):
    if raw in FEATURE_LABELS:
        return FEATURE_LABELS[raw][0]
    return f"[unknown: {raw}]"


# ── Synthetic customer name ──────────────────────────────────────────────────
# customers.csv has no name column. We synthesize a deterministic display name
# from customer_id so the same customer always shows the same name.
_FIRST_NAMES = [
    "Anders", "Mette", "Lars", "Anne", "Peter", "Birgit", "Søren", "Kirsten",
    "Henrik", "Hanne", "Jens", "Lone", "Michael", "Pia", "Niels", "Ulla",
    "Morten", "Susanne", "Christian", "Inger", "Thomas", "Tine", "Jakob",
    "Karin", "Mads", "Charlotte", "Rasmus", "Marianne", "Kasper", "Helle",
    "Frederik", "Camilla", "Magnus", "Astrid", "Erik", "Solveig", "Olav",
    "Ingrid", "Mikkel", "Bodil", "Bjørn", "Sigrid", "Holger", "Merete",
]
_LAST_NAMES = [
    "Pedersen", "Hansen", "Nielsen", "Jensen", "Andersen", "Larsen",
    "Sørensen", "Christensen", "Rasmussen", "Olsen", "Thomsen",
    "Mortensen", "Jørgensen", "Lund", "Madsen", "Berg", "Holm", "Bach",
    "Vestergaard", "Østergaard", "Nørgaard", "Lindberg", "Schmidt",
    "Friis", "Bruun", "Eriksen", "Krogh", "Skov", "Bang", "Mogensen",
]
_CORP_BASES = [
    "Nord", "Aurora", "Atlas", "Vega", "Borealis", "Helio", "Saga",
    "Fjord", "Kronborg", "Aalborg", "Skagen", "Bergen", "Helsinki",
    "Stockholm", "Hanseatic", "Baltic", "Aegis", "Polaris", "Lumen",
    "Fenris", "Valkyr", "Harbor", "Zenith", "Crest", "Meridian",
    "Pinnacle", "Summit", "Catalyst", "Quanta", "Continuum", "Integra",
]
_CORP_SUFFIX = ["A/S", "ApS", "AB", "AS", "OY"]


def _hash_id(customer_id):
    return int(hashlib.md5(customer_id.encode("utf-8")).hexdigest(), 16)

def synthesize_name(customer_id, customer_type=None):
    """Deterministic display name. Personal/sole_trader -> person; else company."""
    if not customer_id:
        return "Unknown"
    h = _hash_id(customer_id)
    if customer_type in ("personal", "sole_trader"):
        first = _FIRST_NAMES[h % len(_FIRST_NAMES)]
        last  = _LAST_NAMES[(h // 7) % len(_LAST_NAMES)]
        return f"{first} {last}"
    elif customer_type in ("corporate", "SME"):
        base   = _CORP_BASES[h % len(_CORP_BASES)]
        word2  = _CORP_BASES[(h // 11) % len(_CORP_BASES)]
        suffix = _CORP_SUFFIX[(h // 13) % len(_CORP_SUFFIX)]
        return f"{base} {word2} {suffix}"
    # fallback
    return customer_id


# ── Data loaders (cached) ────────────────────────────────────────────────────
@st.cache_data
def load_customers():
    df = pd.read_csv(DATA_DIR / "customers.csv", dtype={"customer_id": str})
    df["display_name"] = [synthesize_name(c, t)
                          for c, t in zip(df["customer_id"], df["customer_type"])]
    return df

@st.cache_data
def load_accounts():
    return pd.read_csv(DATA_DIR / "accounts.csv",
                       dtype={"customer_id": str, "account_id": str})

@st.cache_data
def load_transactions():
    return pd.read_csv(DATA_DIR / "transactions.csv",
                       dtype={"customer_id": str, "transaction_id": str},
                       parse_dates=["timestamp"])

@st.cache_data
def load_alert_history():
    return pd.read_csv(DATA_DIR / "alert_history.csv", dtype={"customer_id": str})

@st.cache_data
def load_baselines():
    return pd.read_csv(DATA_DIR / "baselines.csv", dtype={"customer_id": str})

@st.cache_data
def load_country_risk():
    return pd.read_csv(DATA_DIR / "country_risk.csv")

@st.cache_data
def load_predictions():
    if not PREDICTIONS_PATH.exists():
        return None
    return pd.read_csv(PREDICTIONS_PATH, dtype={"customer_id": str})

@st.cache_data
def load_drivers():
    if not DRIVERS_PATH.exists():
        return None
    return pd.read_csv(DRIVERS_PATH, dtype={"customer_id": str})

@st.cache_data
def load_h1_features():
    if not H1_PATH.exists():
        return None
    return pd.read_parquet(H1_PATH)

@st.cache_data
def load_cohort_baselines():
    """Mean of each baseline column grouped by customer_type."""
    bl = load_baselines()
    cust = load_customers()[["customer_id", "customer_type"]]
    merged = bl.merge(cust, on="customer_id")
    return merged.groupby("customer_type").mean(numeric_only=True)


# ── Country risk lookup ──────────────────────────────────────────────────────
@st.cache_data
def country_risk_dict():
    """Precompute a {country_code: (status, label)} dict for O(1) lookups."""
    cr = load_country_risk()
    out = {}
    for _, row in cr.iterrows():
        cc = row.get("country_code")
        if pd.isna(cc):
            continue
        fatf = str(row.get("fatf_status", "")).lower()
        eu = bool(row.get("eu_high_risk_list", False))
        if "non" in fatf or "blacklist" in fatf or eu:
            out[cc] = ("red", f"FATF: {row.get('fatf_status', '')}")
        elif "grey" in fatf or "monitor" in fatf:
            out[cc] = ("amber", "FATF grey list")
        else:
            out[cc] = ("green", "Compliant jurisdiction")
    return out


def country_risk_status(country_code):
    """Returns ('red'|'amber'|'green'|None, label) for a counterparty country."""
    if pd.isna(country_code) or not country_code:
        return None, ""
    return country_risk_dict().get(country_code, (None, ""))


@st.cache_data
def transactions_by_customer():
    """Pre-group transactions.csv by customer_id so the modal can fetch a
    customer's transactions in O(1) instead of scanning all 77k rows."""
    df = load_transactions()
    return {cid: g for cid, g in df.groupby("customer_id", sort=False)}


@st.cache_data
def baselines_indexed():
    """Baselines.csv keyed by customer_id for O(1) row lookup."""
    return load_baselines().set_index("customer_id")


# ── Risk flags (top 3 chips per customer) ───────────────────────────────────
def _truthy(v):
    return str(v).lower() in ("true", "1", "yes")

def compute_risk_flags(customer_row, baseline_row=None, cohort_row=None, max_flags=3):
    """Return up to ``max_flags`` (color, short_label) tuples for queue chips.

    Precedence: hard flags first (red), then behavioural deviations (amber).
    """
    flags = []

    # 1. Sanctions match
    if _truthy(customer_row.get("sanctions_screening_flag")):
        flags.append(("red", "Sanctions"))
    # 2. PEP
    if _truthy(customer_row.get("pep_status")):
        flags.append(("red", "PEP"))
    # 3. FATF non-cooperative residency
    cr_status, _ = country_risk_status(customer_row.get("residency_country"))
    if cr_status == "red":
        flags.append(("red", "FATF jurisdiction"))
    elif cr_status == "amber":
        flags.append(("amber", "Grey jurisdiction"))
    # 4. KYC=high
    if str(customer_row.get("kyc_risk_rating", "")).lower() == "high":
        flags.append(("red", "KYC: high"))

    # Behavioural deviations vs cohort (amber)
    if baseline_row is not None and cohort_row is not None:
        cash = baseline_row.get("pct_cash_transactions")
        cohort_cash = cohort_row.get("pct_cash_transactions") if cohort_row is not None else None
        if (cash is not None and cohort_cash is not None
                and cohort_cash > 0
                and cash > cohort_cash * 1.5):
            flags.append(("amber", "High cash rate"))

        intl = baseline_row.get("pct_international_transactions")
        cohort_intl = cohort_row.get("pct_international_transactions") if cohort_row is not None else None
        if (intl is not None and cohort_intl is not None
                and cohort_intl > 0
                and intl > cohort_intl * 1.5):
            flags.append(("amber", "Heavy international"))

        ent = baseline_row.get("transaction_time_entropy")
        cohort_ent = cohort_row.get("transaction_time_entropy") if cohort_row is not None else None
        if (ent is not None and cohort_ent is not None
                and cohort_ent > 0
                and ent > cohort_ent * 1.3):
            flags.append(("amber", "Unusual timing"))

        # Spike in volume (against the customer's own H1, if available)
        # We can't compute that here without H1 features; placeholder.

    # Trim to max_flags
    return flags[:max_flags]


def render_flags_html(flags):
    """Convert flag tuples into a row of HTML chips."""
    if not flags:
        return '<span style="color:#aaa;font-size:0.78rem">—</span>'
    chunks = []
    for color, label in flags:
        cls = {"red": "flag-red", "amber": "flag-amber"}.get(color, "flag-blue")
        chunks.append(f'<span class="flag-chip {cls}">{label}</span>')
    return "".join(chunks)


# ── SQLite persistence ───────────────────────────────────────────────────────
def _seed_initial_state(cur):
    """First-run seeding for a realistic demo state.

    Active queue (status='new'): a MIX of high and medium risk:
        * Top 25 customers by score (the strongest model alerts)
        * 25 randomly chosen from the medium band (so the queue isn't all red)

    Decision log: every other customer gets a pre-loaded historical decision:
        * High-risk seeded (>= SEED_HIGH): random verdict ~60% escalated
          (these are the kind of cases analysts genuinely investigate);
          analyst name drawn from SEED_ANALYSTS; reason text from the
          appropriate SEED_REASONS_* pool.
        * Medium-risk seeded (>= SEED_MED): random verdict ~15% escalated
          (mostly false positives in this band).
        * Low-risk seeded: cleared with the standard "Auto-cleared (low risk)"
          reason and analyst "System (auto)".

    All randomness is seeded with Random(42) so the demo state is
    reproducible across re-launches.
    """
    customers_path = DATA_DIR / "customers.csv"
    if not customers_path.exists():
        return
    customers = pd.read_csv(customers_path, dtype={"customer_id": str})

    if not PREDICTIONS_PATH.exists():
        # Fallback: no predictions available, seed all as 'new'
        cur.executemany(
            "INSERT OR IGNORE INTO investigation_status (customer_id, status) "
            "VALUES (?, 'new')",
            [(cid,) for cid in customers["customer_id"]],
        )
        return

    preds = pd.read_csv(PREDICTIONS_PATH, dtype={"customer_id": str})
    merged = customers[["customer_id"]].merge(preds, on="customer_id", how="left")
    merged["predicted_probability"] = merged["predicted_probability"].fillna(0)
    merged = merged.sort_values(
        "predicted_probability", ascending=False, kind="stable")

    # Risk bands (using seeding thresholds, not display thresholds)
    high_band   = merged[merged["predicted_probability"] >= SEED_HIGH]
    medium_band = merged[(merged["predicted_probability"] >= SEED_MED) &
                         (merged["predicted_probability"] <  SEED_HIGH)]

    # Active queue: top 25 from high + 25 random from medium
    n_high   = min(25, len(high_band))
    n_medium = min(25, len(medium_band))
    queue_high   = high_band.head(n_high)
    queue_medium = (medium_band.sample(n_medium, random_state=42)
                    if n_medium > 0 else medium_band.iloc[:0])
    queue_ids = set(queue_high["customer_id"]) | set(queue_medium["customer_id"])

    cur.executemany(
        "INSERT OR IGNORE INTO investigation_status (customer_id, status) "
        "VALUES (?, 'new')",
        [(cid,) for cid in queue_ids],
    )

    # Everyone else → seeded into the decision log with realistic verdicts.
    rng = random.Random(42)
    base_now = datetime.now()
    six_months_seconds = 180 * 86400
    rest = merged[~merged["customer_id"].isin(queue_ids)]

    status_rows  = []
    history_rows = []
    for _, row in rest.iterrows():
        cid   = row["customer_id"]
        score = float(row["predicted_probability"])
        ts = (base_now - timedelta(seconds=rng.randint(0, six_months_seconds))
              ).strftime("%Y-%m-%d %H:%M:%S")

        if score >= SEED_HIGH:
            # High-risk: ~60% escalated, ~40% cleared. These look like real
            # investigations, with human analyst names and diverse reasons.
            if rng.random() < 0.60:
                new_st = "escalated"
                reason = rng.choice(SEED_REASONS_ESCALATED)
            else:
                new_st = "cleared"
                reason = rng.choice(SEED_REASONS_CLEARED)
            analyst = rng.choice(SEED_ANALYSTS)
        elif score >= SEED_MED:
            # Medium-risk: mostly cleared (~85%), occasional escalation (~15%).
            if rng.random() < 0.15:
                new_st = "escalated"
                reason = rng.choice(SEED_REASONS_ESCALATED)
            else:
                new_st = "cleared"
                reason = rng.choice(SEED_REASONS_CLEARED)
            analyst = rng.choice(SEED_ANALYSTS)
        else:
            # Low-risk: auto-cleared at onboarding screen. System reason.
            new_st  = "cleared"
            reason  = "Auto-cleared during onboarding screen (low risk)"
            analyst = "System (auto)"

        status_rows.append((cid, new_st, analyst, reason, ts))
        history_rows.append((cid, "new", new_st, analyst, reason, ts))

    cur.executemany(
        "INSERT OR REPLACE INTO investigation_status "
        "(customer_id, status, analyst_name, analyst_note, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        status_rows,
    )
    cur.executemany(
        "INSERT INTO investigation_history "
        "(customer_id, previous_status, new_status, analyst_name, "
        "reason_note, changed_at) VALUES (?, ?, ?, ?, ?, ?)",
        history_rows,
    )


def init_db():
    """Create both tables. If the audit table is missing (old schema or fresh
    DB), wipe everything and re-seed via _seed_initial_state."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='investigation_history'")
    has_history = cur.fetchone() is not None

    if not has_history:
        cur.execute("DROP TABLE IF EXISTS investigation_status")
        cur.execute("DROP TABLE IF EXISTS investigation_history")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS investigation_status (
            customer_id   TEXT PRIMARY KEY,
            status        TEXT CHECK(status IN ('new','under_review','cleared','escalated'))
                          DEFAULT 'new',
            analyst_name  TEXT DEFAULT '',
            analyst_note  TEXT DEFAULT '',
            updated_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS investigation_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id     TEXT NOT NULL,
            previous_status TEXT,
            new_status      TEXT,
            analyst_name    TEXT,
            reason_note     TEXT,
            changed_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    if not has_history:
        _seed_initial_state(cur)

    con.commit()
    con.close()


def get_status(customer_id):
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT status, analyst_name, analyst_note, updated_at "
        "FROM investigation_status WHERE customer_id=?",
        (customer_id,),
    ).fetchone()
    con.close()
    if row:
        return {"status": row[0], "analyst_name": row[1] or "",
                "analyst_note": row[2] or "", "updated_at": row[3] or ""}
    return {"status": "new", "analyst_name": "", "analyst_note": "", "updated_at": ""}


def transition_status(customer_id, new_status, analyst_name="", reason=""):
    """Update investigation_status and append a row to investigation_history.

    Refuses to change a customer that is already 'cleared' or 'escalated'.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT status FROM investigation_status WHERE customer_id=?",
        (customer_id,),
    )
    row = cur.fetchone()
    previous = row[0] if row else "new"

    if previous in ("cleared", "escalated"):
        con.close()
        return False  # immutable

    if previous == new_status:
        con.close()
        return False  # no-op

    cur.execute(
        "INSERT OR REPLACE INTO investigation_status "
        "(customer_id, status, analyst_name, analyst_note, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (customer_id, new_status, analyst_name or "", reason or ""),
    )
    cur.execute(
        "INSERT INTO investigation_history "
        "(customer_id, previous_status, new_status, analyst_name, reason_note) "
        "VALUES (?, ?, ?, ?, ?)",
        (customer_id, previous, new_status, analyst_name or "", reason or ""),
    )
    con.commit()
    con.close()
    return True


def get_all_statuses():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT customer_id, status FROM investigation_status"
    ).fetchall()
    con.close()
    return {r[0]: r[1] for r in rows}


def get_status_counts():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT status, COUNT(*) FROM investigation_status GROUP BY status"
    ).fetchall()
    con.close()
    counts = {"new": 0, "under_review": 0, "cleared": 0, "escalated": 0}
    for status, n in rows:
        counts[status] = n
    return counts


def get_history(customer_id=None, finalized_only=False):
    """Returns history rows; optionally filtered to a customer or to final
    decisions only (cleared/escalated)."""
    con = sqlite3.connect(DB_PATH)
    sql = ("SELECT id, customer_id, previous_status, new_status, "
           "analyst_name, reason_note, changed_at FROM investigation_history")
    params = []
    where = []
    if customer_id is not None:
        where.append("customer_id = ?")
        params.append(customer_id)
    if finalized_only:
        where.append("new_status IN ('cleared','escalated')")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY changed_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    cols = ["id", "customer_id", "previous_status", "new_status",
            "analyst_name", "reason_note", "changed_at"]
    return pd.DataFrame(rows, columns=cols)


# ── Modal: Investigation detail ─────────────────────────────────────────────
def open_investigation(customer_id):
    """Set state to open the investigation modal. Auto-transitions a 'new'
    customer to 'under_review' so the queue reflects the analyst's attention."""
    rec = get_status(customer_id)
    if rec["status"] == "new":
        transition_status(customer_id, "under_review",
                          analyst_name="", reason="Opened for review")
    st.session_state["modal_customer_id"] = customer_id
    st.session_state["modal_open"] = True


def close_investigation():
    st.session_state["modal_open"] = False
    st.session_state["modal_customer_id"] = None


@st.dialog("Customer investigation", width="large")
def render_investigation_dialog(customer_id):
    """Six-section detail view per SKILL.md, plus action area at the bottom."""
    customers     = load_customers()
    predictions   = load_predictions()
    drivers       = load_drivers()
    baselines     = load_baselines()
    h1_features   = load_h1_features()
    accounts_df   = load_accounts()
    txn_df        = load_transactions()
    alert_df      = load_alert_history()
    country_risk  = load_country_risk()
    cohort_bl     = load_cohort_baselines()

    cust_row = customers[customers["customer_id"] == customer_id]
    if cust_row.empty:
        st.error(f"Customer {customer_id} not found.")
        return
    cust = cust_row.iloc[0]

    # Score
    score = None
    if predictions is not None:
        pr = predictions[predictions["customer_id"] == customer_id]
        if not pr.empty:
            score = float(pr.iloc[0]["predicted_probability"])

    # Status
    rec = get_status(customer_id)
    db_status = rec["status"]
    is_pending = db_status in ("new", "under_review")

    # ── Section 1: header (always visible) ────────────────────────────────────
    # Traffic-light palette: green / yellow / red.
    band_color = ("#c62828" if (score or 0) >= RISK_HIGH
                  else "#f9a825" if (score or 0) >= RISK_MED
                  else "#2e7d32")

    cust_type     = cust.get("customer_type", "—")
    country       = cust.get("residency_country", "")
    name          = cust.get("display_name", customer_id)
    pep           = _truthy(cust.get("pep_status"))
    sanctions     = _truthy(cust.get("sanctions_screening_flag"))
    kyc_rating    = cust.get("kyc_risk_rating", "—")

    cr_status, cr_label = country_risk_status(country)

    # Header card
    st.markdown(f"""
    <div class="card" style="border-left:4px solid {band_color};margin-top:0">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div>
                <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.1em;
                            color:#546e8a;text-transform:uppercase;margin-bottom:4px">
                    Customer profile
                </div>
                <div style="font-size:1.35rem;font-weight:700;color:#0d2137">{name}</div>
                <div style="margin-top:6px">
                    {type_badge(cust_type)}
                    &nbsp;<span style="font-size:0.85rem;color:#546e8a">
                    {customer_id} · {country} · Registered {fmt_date(cust.get("registration_date",""))}
                    </span>
                </div>
            </div>
            <div style="text-align:right">
                <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.1em;
                            color:#546e8a;text-transform:uppercase;margin-bottom:4px">
                    Risk score
                </div>
                {'<div style="font-size:1.9rem;font-weight:800;color:' + band_color + '">'
                 + f"{score:.2f}" + '</div>' if score is not None
                 else '<div style="font-size:1rem;color:#546e8a">Not scored</div>'}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # KYC + status pills
    pills = []
    kyc_color = {"low": "#2e7d32", "medium": "#f57f17",
                 "high": "#c62828"}.get(str(kyc_rating).lower(), "#546e8a")
    pills.append(
        f'<span class="pill" style="background:{kyc_color}20;color:{kyc_color};'
        f'border:1px solid {kyc_color}40">KYC: {kyc_rating}</span>')
    if pep:
        pills.append('<span class="pill" style="background:#c6282820;color:#c62828;'
                     'border:1px solid #c6282840">PEP</span>')
    if sanctions:
        pills.append('<span class="pill" style="background:#c6282820;color:#c62828;'
                     'border:1px solid #c6282840">Sanctions match</span>')
    if cr_status == "red":
        pills.append(f'<span class="pill" style="background:#c6282820;color:#c62828;'
                     f'border:1px solid #c6282840">{cr_label} ({country})</span>')
    elif cr_status == "amber":
        pills.append(f'<span class="pill" style="background:#e6510020;color:#e65100;'
                     f'border:1px solid #e6510040">{cr_label} ({country})</span>')

    occ = cust.get("occupation_category", "")
    industry = cust.get("industry_code", "")
    if occ and not pd.isna(occ):
        pills.append(f'<span class="pill" style="background:#e8f1fb;color:#1565c0;'
                     f'border:1px solid #1565c020">{occ}</span>')
    elif industry and not pd.isna(industry):
        pills.append(f'<span class="pill" style="background:#e8f1fb;color:#1565c0;'
                     f'border:1px solid #1565c020">Industry: {industry}</span>')
    st.markdown("".join(pills), unsafe_allow_html=True)

    # Plain-language risk reason
    cust_baseline = baselines[baselines["customer_id"] == customer_id]
    baseline_row = cust_baseline.iloc[0] if not cust_baseline.empty else None
    cohort_row = cohort_bl.loc[cust_type] if cust_type in cohort_bl.index else None
    flags = compute_risk_flags(cust, baseline_row, cohort_row, max_flags=5)
    if flags:
        reason_lines = [lbl for _, lbl in flags]
        st.markdown(
            f'<div class="card-blue" style="font-size:0.9rem;margin-top:8px">'
            f'<strong>Why flagged:</strong> {", ".join(reason_lines)}.</div>',
            unsafe_allow_html=True,
        )

    # Current decision badge
    st.markdown(
        f'<div style="margin-top:8px;font-size:0.85rem;color:#546e8a">'
        f'Status: {status_badge(db_status)}'
        f'{(" · last updated " + rec["updated_at"][:16]) if rec["updated_at"] else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Contact Details ───────────────────────────────────────────────────────
    with st.expander("Contact Details", expanded=False):
        contact_key = f"contact_{customer_id}"
        default_contact = st.session_state.get(contact_key, {
            "name":  name,
            "person": "",
            "role":   "",
            "email":  f"{customer_id.lower()}@nordikbank.dk",
        })
        cd1, cd2 = st.columns(2)
        cd_name   = cd1.text_input("Customer Name",  value=default_contact["name"],  key=f"cd_name_{customer_id}")
        cd_person = cd2.text_input("Contact Person", value=default_contact["person"], key=f"cd_person_{customer_id}")
        cd_role   = cd1.text_input("Contact Role",   value=default_contact["role"],  key=f"cd_role_{customer_id}")
        cd_email  = cd2.text_input("Email",          value=default_contact["email"], key=f"cd_email_{customer_id}")
        if st.button("Save Contact Details", key=f"cd_save_{customer_id}"):
            st.session_state[contact_key] = {
                "name": cd_name, "person": cd_person,
                "role": cd_role, "email": cd_email,
            }
            st.success("Contact details saved.")

    # ── Section 2: Risk drivers & peer comparison ────────────────────────────
    with st.expander("Risk Drivers & Peer Comparison", expanded=True):
        if drivers is None:
            st.info("Driver data unavailable — run the modeling pipeline to generate "
                    "`prediction_drivers.csv`.")
        else:
            d_rows = drivers[drivers["customer_id"] == customer_id]
            if d_rows.empty:
                st.info(f"No driver data for {customer_id}.")
            else:
                for _, dr in d_rows.iterrows():
                    feat     = dr.get("feature_name", "")
                    shap_val = dr.get("shap_value", dr.get("importance", 0))
                    label, unit, tooltip = FEATURE_LABELS.get(
                        feat, (f"[unknown: {feat}]", "", "No description"))
                    try:
                        shap_f = float(shap_val)
                    except (TypeError, ValueError):
                        shap_f = 0.0
                    driver_class = ("driver-high" if shap_f > 0.10
                                    else "driver-elevated" if shap_f > 0.03
                                    else "")

                    # H2 (baselines.csv)
                    h2_val = None
                    if (baseline_row is not None) and (feat in baseline_row.index):
                        try:
                            h2_val = float(baseline_row[feat])
                        except (TypeError, ValueError):
                            pass
                    # H1
                    h1_val = None
                    if h1_features is not None:
                        h1_row = h1_features[h1_features["customer_id"] == customer_id]
                        if not h1_row.empty and feat in h1_row.columns:
                            try:
                                h1_val = float(h1_row.iloc[0][feat])
                            except (TypeError, ValueError):
                                pass
                    # Cohort
                    cohort_val = None
                    if (cohort_row is not None) and (feat in cohort_row.index):
                        try:
                            cohort_val = float(cohort_row[feat])
                        except (TypeError, ValueError):
                            pass

                    timeline = ""
                    if h1_val is not None and h2_val is not None:
                        arrow = "↑" if h2_val > h1_val else "↓" if h2_val < h1_val else "→"
                        timeline = (
                            f'<span style="color:#546e8a">H1→H2:</span> '
                            f'<strong>{fmt_feature_value(feat, h1_val)}</strong> {arrow} '
                            f'<strong style="color:{band_color}">'
                            f'{fmt_feature_value(feat, h2_val)}</strong>')
                    elif h2_val is not None:
                        timeline = (
                            f'<span style="color:#546e8a">Current (H2):</span> '
                            f'<strong>{fmt_feature_value(feat, h2_val)}</strong>'
                            f' <span style="font-size:0.78rem;color:#aaa">'
                            f'(H1 baseline unavailable)</span>')
                    else:
                        timeline = ('<span style="color:#aaa;font-size:0.82rem">'
                                    'Value unavailable</span>')

                    cohort_line = ""
                    if cohort_val is not None and h2_val is not None and cohort_val != 0:
                        diff_pct = ((h2_val - cohort_val) / cohort_val * 100)
                        sign = "+" if diff_pct > 0 else ""
                        col = ("#c62828" if diff_pct > 20    # red
                               else "#f9a825" if diff_pct > 0  # yellow
                               else "#2e7d32")                  # green
                        cohort_line = (
                            f'&nbsp;&nbsp;·&nbsp;&nbsp;'
                            f'<span style="color:#546e8a">'
                            f'Cohort avg ({cust_type}):</span> '
                            f'{fmt_feature_value(feat, cohort_val)} '
                            f'<span style="color:{col};font-weight:600">'
                            f'({sign}{diff_pct:.0f}% vs cohort)</span>')

                    st.markdown(f"""
                    <div class="driver-row {driver_class}">
                        <div style="display:flex;justify-content:space-between;
                                    align-items:center;margin-bottom:4px">
                            <span style="font-weight:600;font-size:0.9rem"
                                  title="{tooltip}">{label}</span>
                            <span style="font-size:0.78rem;color:#546e8a">
                                SHAP: {shap_f:+.3f}
                            </span>
                        </div>
                        <div style="font-size:0.85rem">{timeline}{cohort_line}</div>
                    </div>
                    """, unsafe_allow_html=True)

    # Compute the customer's transactions ONCE — sections 4 and 5 share this.
    # transactions_by_customer() is a cached dict so this is O(1).
    cust_txns_full = transactions_by_customer().get(
        customer_id, txn_df.iloc[:0]
    ).copy()
    if not cust_txns_full.empty:
        cust_txns_full["abs_amount"] = cust_txns_full["amount"].abs()
        cust_txns_full["hour"]       = cust_txns_full["timestamp"].dt.hour

    # ── Section 3: Legacy System Alignment (TMS) ─────────────────────────────
    with st.expander("Legacy System Alignment"):
        if alert_df is None or alert_df.empty:
            st.info("TMS alert history unavailable.")
        else:
            cust_alerts = alert_df[alert_df["customer_id"] == customer_id].copy()
            if cust_alerts.empty:
                st.info("No prior TMS alerts for this customer.")
            else:
                cust_alerts = cust_alerts.sort_values("alert_date", ascending=False)

                # Alignment note first (compact summary)
                escalated_n = (cust_alerts["analyst_decision"] == "escalated").sum()
                sar_n       = (cust_alerts["analyst_decision"] == "SAR_filed").sum()
                model_high  = (score or 0) >= RISK_MED
                if (escalated_n + sar_n) > 0 and model_high:
                    st.success("Model agrees with TMS — repeated escalations, "
                               "elevated model risk score.")
                elif (escalated_n + sar_n) > 0 and not model_high:
                    st.warning("Possible divergence — TMS escalated previously, "
                               "model rates this customer low.")
                elif (escalated_n + sar_n) == 0 and model_high:
                    st.info("Model flags risk that TMS did not — review evidence carefully.")
                else:
                    st.info("Both TMS and the model treat this customer as low risk.")

                # Full alert list inline (no nested expander — Streamlit forbids it)
                full_alerts = cust_alerts.copy()
                full_alerts["alert_date"] = full_alerts["alert_date"].apply(fmt_date)
                st.dataframe(
                    full_alerts[["alert_date", "trigger_rule", "analyst_decision",
                                 "investigation_time_minutes"]].rename(columns={
                        "alert_date": "Date", "trigger_rule": "Trigger",
                        "analyst_decision": "Decision",
                        "investigation_time_minutes": "Time (min)"}),
                    use_container_width=True, hide_index=True, height=200)

    # ── Section 4: Transaction patterns & anomalies ──────────────────────────
    with st.expander("Transaction Patterns & Anomalies"):
        if cust_txns_full.empty:
            st.info("No transactions in sample window for this customer.")
        else:
            n_total   = len(cust_txns_full)
            n_offhrs  = ((cust_txns_full["hour"] < 8) |
                         (cust_txns_full["hour"] >= 18)).sum()
            n_decline = (cust_txns_full["status"] == "declined").sum()
            largest   = float(cust_txns_full["abs_amount"].max())
            n_intl    = (cust_txns_full["counterparty_bank_country"].notna()
                         & (cust_txns_full["counterparty_bank_country"] != "DK")).sum()
            n_cash    = cust_txns_full["transaction_type"].isin(
                ("cash_deposit", "cash_withdrawal")).sum()

            m_cols = st.columns(4)
            m_cols[0].metric("Transactions", f"{n_total:,}")
            m_cols[1].metric("Off-hours", f"{n_offhrs:,}",
                             help="Transactions outside 08:00–18:00")
            m_cols[2].metric("Declined", f"{n_decline:,}",
                             help="Repeated declines can indicate structuring")
            m_cols[3].metric("Largest amount", fmt_dkk(largest))

            m_cols = st.columns(3)
            m_cols[0].metric("International", f"{n_intl:,}")
            m_cols[1].metric("Cash", f"{n_cash:,}")
            cohort_n_intl = (cohort_row.get("pct_international_transactions")
                             if cohort_row is not None else None)
            if cohort_n_intl is not None:
                m_cols[2].metric("Intl rate vs cohort",
                                 fmt_pct(n_intl / max(n_total, 1)),
                                 delta=f"cohort avg {fmt_pct(cohort_n_intl)}")

    # ── Section 5: Transaction history with risk flags ───────────────────────
    with st.expander("Transaction History"):
        if cust_txns_full.empty:
            st.info("No transactions in sample window for this customer.")
        else:
            # Identify first-time counterparties (only counted once per cust)
            first_seen = cust_txns_full.sort_values("timestamp").drop_duplicates(
                "counterparty_id")["transaction_id"]
            cust_txns_full["is_new_cp"] = (
                cust_txns_full["transaction_id"].isin(first_seen)
                & cust_txns_full["counterparty_id"].notna())

            def row_flags(row):
                chips = []
                cs, _ = country_risk_status(row.get("counterparty_bank_country"))
                if cs == "red":
                    chips.append('<span class="flag-chip flag-red">⛔</span>')
                elif cs == "amber":
                    chips.append('<span class="flag-chip flag-amber">⚠️</span>')
                elif cs == "green":
                    chips.append('<span class="flag-chip flag-green">✓</span>')
                if row["is_new_cp"]:
                    chips.append('<span class="flag-chip flag-amber">⭐ NEW</span>')
                if row["hour"] < 8 or row["hour"] >= 18:
                    chips.append('<span class="flag-chip flag-amber">off-hours</span>')
                return "".join(chips)

            cust_txns_sorted = cust_txns_full.sort_values("abs_amount", ascending=False)
            top = cust_txns_sorted.head(8).copy()
            top["Date"]    = top["timestamp"].apply(fmt_ts)
            top["Amount"]  = top["amount"].apply(lambda v: f"{v:,.0f}")
            top["Flags"]   = top.apply(row_flags, axis=1)

            head = ("<table class='queue-table'><thead><tr style="
                    "'font-size:0.7rem;color:#546e8a;text-transform:uppercase'>")
            for h in ("Date", "Amount", "CCY", "Type", "Channel", "Country", "Flags"):
                head += f"<th style='padding:6px 8px;text-align:left'>{h}</th>"
            head += "</tr></thead><tbody>"
            body = ""
            for _, r in top.iterrows():
                body += "<tr style='font-size:0.85rem'>"
                for c in ("Date", "Amount", "currency", "transaction_type",
                          "channel", "counterparty_bank_country", "Flags"):
                    val = r.get(c, "")
                    if pd.isna(val):
                        val = "—"
                    body += f"<td style='padding:6px 8px'>{val}</td>"
                body += "</tr>"
            st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)

            # Full transaction list inline (no nested expander)
            st.markdown(f"<p style='font-size:0.78rem;color:#546e8a;"
                        f"margin-top:10px;margin-bottom:4px'>"
                        f"All {len(cust_txns_full):,} transactions:</p>",
                        unsafe_allow_html=True)
            full = cust_txns_sorted.copy()
            full["Date"]   = full["timestamp"].apply(fmt_ts)
            full["Amount"] = full["amount"].apply(lambda v: f"{v:,.0f}")
            st.dataframe(
                full[["Date", "Amount", "currency", "transaction_type",
                      "channel", "counterparty_bank_country"]].rename(columns={
                    "currency": "CCY", "transaction_type": "Type",
                    "channel": "Channel",
                    "counterparty_bank_country": "Country"}),
                use_container_width=True, hide_index=True, height=200)

    # ── Section 6: Investigation history ─────────────────────────────────────
    with st.expander("Investigation History"):
        history = get_history(customer_id=customer_id)
        if history.empty:
            st.info("No prior investigation activity recorded.")
        else:
            for _, h in history.iterrows():
                badge = status_badge(h["new_status"])
                analyst_disp = h["analyst_name"] or "(no name)"
                when_disp = fmt_ts(h["changed_at"])
                reason_html = (
                    f'<div style="margin-top:4px;font-size:0.85rem;color:#0d2137">'
                    f'{h["reason_note"]}</div>'
                    if h["reason_note"] else ""
                )
                st.markdown(
                    f'<div style="padding:8px 12px;border-radius:8px;'
                    f'background:#f5f8fc;margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'font-size:0.85rem">'
                    f'<span><strong>{analyst_disp}</strong> · {when_disp}</span>'
                    f'{badge}</div>'
                    f'{reason_html}'
                    f'</div>',
                    unsafe_allow_html=True)

    # ── Action area ──────────────────────────────────────────────────────────
    st.markdown("---")

    # ── Tabs: Decision / Send Email ───────────────────────────────────────────
    modal_tab1, modal_tab2 = st.tabs(["Decision", "Send Email"])

    with modal_tab2:
        st.markdown("#### Compose Email")
        email_to = st.text_input("To", value=f"{customer_id.lower()}@nordikbank.dk",
                                 key="email_to")
        email_subject = st.text_input("Subject",
                                      value=f"Re: Account Review — {name}",
                                      key="email_subject")
        email_body = st.text_area("Message",
                                  value=f"Dear {name},\n\nWe are writing regarding your account...\n\nKind regards,\nNordikBank Compliance",
                                  height=150, key="email_body")
        ec1, ec2 = st.columns([1, 4])
        with ec1:
            if st.button("Send", key="email_send", type="primary",
                         use_container_width=True):
                st.success(f"Email sent to {email_to}")

    with modal_tab1:
        if not is_pending:
            st.info(f"This customer has a final decision ({db_status}). No further "
                    f"actions are available.")
            if st.button("Close", key="modal_close_btn"):
                close_investigation()
                st.rerun()
            return

        st.markdown('<div class="section-label" style="margin-top:0">'
                    'Decision</div>', unsafe_allow_html=True)
        a_col1, a_col2 = st.columns([1, 2])
        with a_col1:
            analyst = st.text_input(
                "Your Name", value=st.session_state.get("modal_analyst", ""),
                key="modal_analyst_input",
                placeholder="Required to record a decision")
        with a_col2:
            reason = st.text_area(
                "Reason / Note",
                value=st.session_state.get("modal_reason", ""),
                key="modal_reason_input",
                placeholder="Required — what evidence drove this decision?",
                height=80)

        can_act = bool(analyst.strip()) and bool(reason.strip())
        b_col1, b_col2, b_col3 = st.columns([1, 1, 1])

        with b_col1:
            if st.button("Clear ✓", type="primary", key="modal_clear",
                         disabled=not can_act, use_container_width=True):
                transition_status(customer_id, "cleared",
                                  analyst_name=analyst.strip(),
                                  reason=reason.strip())
                st.session_state["modal_analyst"] = analyst.strip()
                st.success(f"Cleared {customer_id}.")
                close_investigation()
                st.rerun()

        with b_col2:
            if st.button("Escalate ⚠", key="modal_escalate",
                         disabled=not can_act, use_container_width=True):
                transition_status(customer_id, "escalated",
                                  analyst_name=analyst.strip(),
                                  reason=reason.strip())
                st.session_state["modal_analyst"] = analyst.strip()
                st.success(f"Escalated {customer_id} for FIU referral.")
                close_investigation()
                st.rerun()

        with b_col3:
            if st.button("Cancel", key="modal_cancel", use_container_width=True):
                close_investigation()
                st.rerun()

        if not can_act:
            st.caption("Both your name and a reason are required to clear or "
                       "escalate this customer.")


# ── Sidebar ──────────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div class="sidebar-brand">
            <div style="font-size:0.7rem;font-weight:600;letter-spacing:0.12em;
                        color:#a8bdd4;text-transform:uppercase">
                NordikBank
            </div>
            <div style="font-size:1.1rem;font-weight:700;color:#ffffff;margin-top:2px">
                AML Workbench
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Four-up status summary box
        counts = get_status_counts()
        order = ["new", "under_review", "cleared", "escalated"]
        st.caption("Alerts overview")
        for status in order:
            cfg = STATUS_CARD[status]
            st.markdown(f"""
            <div class="status-card" style="background:{cfg["bg"]};color:{cfg["fg"]}">
                <div class="label">{cfg["label"]}</div>
                <div class="value" style="color:{cfg["num_color"]}">{counts.get(status, 0):,}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        predictions = load_predictions()
        if predictions is None:
            st.markdown(
                '<span style="color:#ef9a9a;font-size:0.78rem">'
                '⚠ Predictions not loaded</span>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<span style="color:#a8bdd4;font-size:0.78rem">'
                f'✓ {len(predictions):,} customers scored</span>',
                unsafe_allow_html=True)


# ── Tab 1: Alert Queue ──────────────────────────────────────────────────────
# Map (color, label) flag tuples to emoji-prefixed strings for use in
# st.dataframe (which cannot render coloured chips).
def _flags_as_text(flags):
    """Convert [(color, label), ...] -> "🔴 PEP, 🟡 High cash"."""
    if not flags:
        return ""
    em = {"red": "🔴", "amber": "🟡", "green": "🟢"}
    return ", ".join(f"{em.get(c, '·')} {lbl}" for c, lbl in flags)


def render_queue_tab():
    predictions = load_predictions()
    if predictions is None:
        st.error("**Predictions not found** — run the modeling pipeline first.",
                 icon="🚫")
        st.info(f"Expected at `{PREDICTIONS_PATH}`. Re-run `modeling.ipynb` to refresh.")
        return

    customers = load_customers()
    statuses = get_all_statuses()
    pending_ids = {cid for cid, s in statuses.items()
                   if s in ("new", "under_review")}
    if not pending_ids:
        st.info("No pending alerts. All customers have been cleared or escalated.")
        return

    queue = predictions.merge(
        customers[["customer_id", "customer_type", "residency_country", "display_name"]],
        on="customer_id", how="left",
    )
    queue = queue[queue["customer_id"].isin(pending_ids)].copy()
    queue["status"] = queue["customer_id"].map(statuses).fillna("new")

    # ── Sort state ─────────────────────────────────────────────────────────────
    if "queue_sort_col" not in st.session_state:
        st.session_state["queue_sort_col"] = "predicted_probability"
        st.session_state["queue_sort_asc"] = False

    sort_col = st.session_state["queue_sort_col"]
    sort_asc = st.session_state["queue_sort_asc"]

    # Map column names to dataframe columns
    col_map = {
        "Customer":    "display_name",
        "Risk":        "predicted_probability",
        "Date added":  "scored_at",
        "Status":      "status",
    }

    # Assign scored_at before sorting
    queue["scored_at"] = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")
    queue = queue.sort_values(sort_col, ascending=sort_asc)

    st.markdown("### Alert Queue")
    st.markdown(
        f'<p style="color:#546e8a;font-size:0.85rem;margin-bottom:12px">'
        f'<strong>{len(queue):,}</strong> customers pending review · '
        f'<em>Click a column header to sort</em></p>',
        unsafe_allow_html=True,
    )

    # ── Clickable column headers ───────────────────────────────────────────────
    H = [2.8, 1.2, 1.4, 1.4, 0.8]
    h = st.columns(H)
    for i, t in enumerate(("Customer", "Risk", "Date added", "Status", "")):
        if t == "":
            h[i].markdown("", unsafe_allow_html=True)
            continue
        df_col = col_map.get(t, "")
        is_active = (df_col == sort_col)
        arrow = (" ↑" if (is_active and sort_asc) else " ↓" if is_active else "")
        style = ("color:#0d2137;font-weight:800;" if is_active
                 else "color:#546e8a;font-weight:700;")
        if h[i].button(
            f"{t}{arrow}",
            key=f"qh_{t}",
            use_container_width=True,
        ):
            if sort_col == df_col:
                st.session_state["queue_sort_asc"] = not sort_asc
            else:
                st.session_state["queue_sort_col"] = df_col
                st.session_state["queue_sort_asc"] = (t == "Customer")
            st.rerun()

    st.markdown('<hr style="margin:0 0 4px;border-top:1px solid #dde3ed">',
                unsafe_allow_html=True)

    # ── Pagination ─────────────────────────────────────────────────────────────
    PAGE = 50
    total = len(queue)
    if "queue_page" not in st.session_state:
        st.session_state["queue_page"] = 0
    page = st.session_state["queue_page"]
    total_pages = max(1, (total + PAGE - 1) // PAGE)
    page = min(page, total_pages - 1)
    visible = queue.iloc[page * PAGE:(page + 1) * PAGE]

    # ── Rows — card design ─────────────────────────────────────────────────────
    status_options = ["new", "under_review", "cleared", "escalated"]
    status_labels  = ["New", "Under Review", "Complete", "Escalated"]

    for _, row in visible.iterrows():
        cid    = row["customer_id"]
        name   = row.get("display_name", cid)
        score  = row["predicted_probability"]
        status = row.get("status", "new")
        ctry   = row.get("residency_country", "—")
        ctype  = row.get("customer_type", "—")

        st.markdown(
            f'<div style="border:1px solid #dde3ed;border-radius:12px;'
            f'padding:14px 16px;margin-bottom:8px;background:#ffffff;'
            f'box-shadow:0 1px 3px rgba(13,33,55,0.06);">',
            unsafe_allow_html=True,
        )
        c = st.columns([2.8, 1.2, 1.4, 1.6, 0.8])

        c[0].markdown(
            f'<div style="padding:2px 0">'
            f'<div style="font-weight:600;color:#0d2137;font-size:0.95rem">{name}</div>'
            f'<div style="font-size:0.75rem;color:#546e8a;margin-top:2px">'
            f'{cid} · {ctry} · {ctype}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c[1].markdown(
            f'<div style="padding:4px 0">{score_badge(score)}</div>',
            unsafe_allow_html=True,
        )
        c[2].markdown(
            f'<div style="padding:6px 0;font-size:0.83rem;color:#546e8a">'
            f'{row["scored_at"]}</div>',
            unsafe_allow_html=True,
        )
        current_idx = status_options.index(status) if status in status_options else 0
        new_status_label = c[3].selectbox(
            "", status_labels, index=current_idx,
            key=f"status_dd_{cid}", label_visibility="collapsed",
        )
        new_status = status_options[status_labels.index(new_status_label)]
        if new_status != status:
            transition_status(cid, new_status)
            st.rerun()

        if c[4].button("Open →", key=f"open_{cid}", use_container_width=True):
            open_investigation(cid)
            st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # ── Pagination controls ────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    p1, p2, p3 = st.columns([1, 2, 1])
    with p1:
        if st.button("← Previous", key="queue_prev", disabled=(page == 0),
                     use_container_width=True):
            st.session_state["queue_page"] = page - 1
            st.rerun()
    with p2:
        st.markdown(
            f'<div style="text-align:center;padding:8px;font-size:0.85rem;color:#546e8a">'
            f'Page {page + 1} of {total_pages} · {total:,} customers</div>',
            unsafe_allow_html=True,
        )
    with p3:
        if st.button("Next →", key="queue_next", disabled=(page >= total_pages - 1),
                     use_container_width=True):
            st.session_state["queue_page"] = page + 1
            st.rerun()


# ── Tab 2: Decision Log ─────────────────────────────────────────────────────
# Decision symbols used in the table (st.dataframe can't render coloured chips,
# so we prefix with an emoji and let the pill-style status_badge live in the
# modal's read-only header instead).
_DECISION_BADGE = {
    "new":          '<span style="background:#f1f1f1;color:#546e8a;padding:4px 12px;'
                    'border-radius:20px;font-size:0.82em;font-weight:600;'
                    'border:1px solid #54607a40">New</span>',
    "under_review": '<span style="background:#fff8e1;color:#b78a00;padding:4px 12px;'
                    'border-radius:20px;font-size:0.82em;font-weight:600;'
                    'border:1px solid #f9a82540">Under Review</span>',
    "cleared":      '<span style="background:#e8f5e9;color:#2e7d32;padding:4px 12px;'
                    'border-radius:20px;font-size:0.82em;font-weight:600;'
                    'border:1px solid #2e7d3240">Cleared</span>',
    "escalated":    '<span style="background:#ffebee;color:#c62828;padding:4px 12px;'
                    'border-radius:20px;font-size:0.82em;font-weight:600;'
                    'border:1px solid #c6282840">Escalated</span>',
}


def render_decision_log_tab():
    history = get_history(finalized_only=True)
    if history.empty:
        st.info("No decisions recorded yet. Cleared and escalated customers will "
                "appear here.")
        return

    customers = load_customers()
    history = history.merge(
        customers[["customer_id", "customer_type", "residency_country",
                   "display_name"]],
        on="customer_id", how="left",
    )

    f1, f2 = st.columns([2, 1])
    f1.markdown("### Decision Log")
    decision_filter = f2.selectbox(
        "Show", ["All", "Escalated only", "Cleared only"],
        key="log_filter", label_visibility="collapsed")
    if decision_filter == "Escalated only":
        history = history[history["new_status"] == "escalated"]
    elif decision_filter == "Cleared only":
        history = history[history["new_status"] == "cleared"]

    PAGE = 50
    total = len(history)
    if "log_page" not in st.session_state:
        st.session_state["log_page"] = 0
    log_page = st.session_state["log_page"]
    total_pages = max(1, (total + PAGE - 1) // PAGE)
    log_page = min(log_page, total_pages - 1)
    visible = history.iloc[log_page * PAGE:(log_page + 1) * PAGE]

    st.markdown(
        f'<p style="color:#546e8a;font-size:0.85rem;margin-bottom:8px">'
        f'Showing <strong>{len(visible):,}</strong> of <strong>{total:,}</strong> '
        f'decisions (most recent first)</p>',
        unsafe_allow_html=True,
    )

    H = [1.2, 2.4, 1.6, 1.4, 3.5]
    h = st.columns(H)
    for i, t in enumerate(("Status", "Customer", "Analyst", "When", "Reason")):
        h[i].markdown(
            f'<div style="font-size:0.7rem;font-weight:700;'
            f'letter-spacing:0.08em;color:#546e8a;text-transform:uppercase;'
            f'padding:6px 4px">{t}</div>',
            unsafe_allow_html=True,
        )
    st.markdown('<hr style="margin:0 0 6px;border-top:1px solid #dde3ed">',
                unsafe_allow_html=True)

    for _, row in visible.iterrows():
        cid     = row["customer_id"]
        name    = row.get("display_name") or cid
        ctry    = row.get("residency_country") or "—"
        ctype   = row.get("customer_type") or "—"
        dec     = row["new_status"]
        analyst = row["analyst_name"] or "(no name)"
        when    = fmt_ts(row["changed_at"])
        reason  = row.get("reason_note") or ""

        c = st.columns(H)
        # Plain colored badge — no round ball, no button
        c[0].markdown(
            f'<div style="padding:8px 4px">'
            f'{_DECISION_BADGE.get(dec, f"<span>{dec}</span>")}</div>',
            unsafe_allow_html=True,
        )
        c[1].markdown(
            f'<div style="padding:6px 4px">'
            f'<div style="font-weight:600;color:#0d2137">{name}</div>'
            f'<div style="font-size:0.75rem;color:#546e8a">{ctry} · {ctype}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c[2].markdown(
            f'<div style="padding:10px 4px;font-size:0.85rem">{analyst}</div>',
            unsafe_allow_html=True,
        )
        c[3].markdown(
            f'<div style="padding:10px 4px;font-size:0.8rem;color:#546e8a">{when}</div>',
            unsafe_allow_html=True,
        )
        c[4].markdown(
            f'<div style="padding:10px 4px;font-size:0.83rem">{reason}</div>',
            unsafe_allow_html=True,
        )

    # ── Pagination controls ────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    lp1, lp2, lp3 = st.columns([1, 2, 1])
    with lp1:
        if st.button("← Previous", key="log_prev", disabled=(log_page == 0),
                     use_container_width=True):
            st.session_state["log_page"] = log_page - 1
            st.rerun()
    with lp2:
        st.markdown(
            f'<div style="text-align:center;padding:8px;font-size:0.85rem;color:#546e8a">'
            f'Page {log_page + 1} of {total_pages} · {total:,} decisions</div>',
            unsafe_allow_html=True,
        )
    with lp3:
        if st.button("Next →", key="log_next", disabled=(log_page >= total_pages - 1),
                     use_container_width=True):
            st.session_state["log_page"] = log_page + 1
            st.rerun()


# ── Tab 3: Customer Database ────────────────────────────────────────────────
_STATUS_SYMBOL = {
    "new":          "⚪ New",
    "under_review": "🔵 Under Review",
    "cleared":      "🟢 Cleared",
    "escalated":    "🔴 Escalated",
}
_KYC_SYMBOL = {
    "high":   "🔴 high",
    "medium": "🟡 medium",
    "low":    "🟢 low",
}


def render_database_tab():
    customers = load_customers()
    predictions = load_predictions()
    statuses = get_all_statuses()

    if predictions is not None:
        df = customers.merge(
            predictions[["customer_id", "predicted_probability"]],
            on="customer_id", how="left",
        )
    else:
        df = customers.copy()
        df["predicted_probability"] = None

    df["current_status"] = df["customer_id"].map(statuses).fillna("new")

    # Assign risk level label based on score
    def risk_level(score):
        if pd.isna(score):
            return "Low risk"
        return "High risk" if score >= RISK_HIGH else "Medium risk" if score >= RISK_MED else "Low risk"
    df["risk_level"] = df["predicted_probability"].apply(risk_level)

    st.markdown("### Customer Database")

    # ── Filters ────────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4, fc5 = st.columns([2, 1.2, 1.2, 1.2, 1.2])
    search_id = fc1.text_input(
        "Search By ID Or Name", placeholder="CUST_… or any name fragment",
        key="db_search")
    type_f = fc2.multiselect(
        "Customer Type", ["personal", "corporate", "sole_trader", "SME"],
        default=[], key="db_type")
    risk_f = fc3.selectbox(
        "Risk Level", ["All", "High Risk", "Medium Risk", "Low Risk"],
        key="db_risk")
    status_f = fc4.selectbox(
        "Status", ["All", "New", "Under Review", "Cleared", "Escalated"],
        key="db_status")
    pep_f = fc5.selectbox("PEP", ["All", "Yes", "No"], key="db_pep")

    # ── Filter logic ────────────────────────────────────────────────────────────
    mask = pd.Series([True] * len(df), index=df.index)
    if search_id:
        mask &= (df["customer_id"].str.contains(search_id, case=False, na=False)
                 | df["display_name"].str.contains(search_id, case=False, na=False))
    if type_f:
        mask &= df["customer_type"].isin(type_f)
    if risk_f != "All":
        risk_map = {"High Risk": "High risk", "Medium Risk": "Medium risk", "Low Risk": "Low risk"}
        mask &= df["risk_level"] == risk_map.get(risk_f, risk_f)
    if status_f != "All":
        status_map = {"New": "new", "Under Review": "under_review",
                      "Cleared": "cleared", "Escalated": "escalated"}
        mask &= df["current_status"] == status_map.get(status_f, status_f)
    if pep_f == "Yes":
        mask &= df["pep_status"].astype(str).str.lower().isin(("true", "1", "yes"))
    elif pep_f == "No":
        mask &= ~df["pep_status"].astype(str).str.lower().isin(("true", "1", "yes"))

    filtered = df[mask].copy()
    if filtered["predicted_probability"].notna().any():
        filtered = filtered.sort_values("predicted_probability", ascending=False)

    st.markdown(
        f'<p style="color:#546e8a;font-size:0.85rem;margin-bottom:8px">'
        f'<strong>{len(filtered):,}</strong> of <strong>{len(df):,}</strong> '
        f'customers</p>',
        unsafe_allow_html=True,
    )

    if filtered.empty:
        st.info("No customers match the current filters.")
        return

    # ── Pagination ─────────────────────────────────────────────────────────────
    PAGE = 50
    total = len(filtered)
    if "db_page" not in st.session_state:
        st.session_state["db_page"] = 0
    db_page = st.session_state["db_page"]
    total_pages = max(1, (total + PAGE - 1) // PAGE)
    db_page = min(db_page, total_pages - 1)
    visible = filtered.iloc[db_page * PAGE:(db_page + 1) * PAGE]

    # ── Column headers ──────────────────────────────────────────────────────────
    H = [1.0, 2.6, 1.0, 1.6, 1.2]
    h = st.columns(H)
    for i, t in enumerate(("Status", "Customer", "Risk", "Compliance Flags", "Type")):
        h[i].markdown(
            f'<div style="font-size:0.7rem;font-weight:700;'
            f'letter-spacing:0.06em;color:#546e8a;text-transform:uppercase;'
            f'padding:6px 4px">{t}</div>',
            unsafe_allow_html=True,
        )
    st.markdown('<hr style="margin:0 0 8px;border-top:1px solid #dde3ed">',
                unsafe_allow_html=True)

    # ── Rows — card design ─────────────────────────────────────────────────────
    for _, row in visible.iterrows():
        cid    = row["customer_id"]
        name   = row.get("display_name") or cid
        ctry   = row.get("residency_country") or "—"
        score  = row.get("predicted_probability")
        kyc    = str(row.get("kyc_risk_rating", "")).lower()
        pep    = _truthy(row.get("pep_status"))
        sanc   = _truthy(row.get("sanctions_screening_flag"))
        ctype  = row.get("customer_type") or "—"
        status = row.get("current_status", "new")

        # Compliance flags — only medium/high KYC, PEP, sanctions
        flags_html = ""
        if kyc == "high":
            flags_html += '<span class="flag-chip flag-red">Rating: High</span>'
        elif kyc == "medium":
            flags_html += '<span class="flag-chip flag-amber">Rating: Medium</span>'
        if pep:
            flags_html += '<span class="flag-chip flag-red">PEP</span>'
        if sanc:
            flags_html += '<span class="flag-chip flag-red">Sanctions</span>'
        if not flags_html:
            flags_html = '<span style="color:#aaa;font-size:0.78rem">—</span>'

        st.markdown(
            f'<div style="border:1px solid #dde3ed;border-radius:12px;'
            f'padding:14px 16px;margin-bottom:8px;background:#ffffff;'
            f'box-shadow:0 1px 3px rgba(13,33,55,0.06);">',
            unsafe_allow_html=True,
        )
        c = st.columns(H)

        # Status badge
        c[0].markdown(
            f'<div style="padding:2px 0">'
            f'{_DECISION_BADGE.get(status, f"<span>{status}</span>")}</div>',
            unsafe_allow_html=True,
        )

        # Clickable customer name — opens investigation modal
        c[1].markdown(
            f'<div style="padding:2px 0">'
            f'<div style="font-weight:600;color:#0d2137;font-size:0.95rem">{name}</div>'
            f'<div style="font-size:0.75rem;color:#546e8a;margin-top:2px">{cid} · {ctry}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if c[1].button("Open", key=f"db_open_{cid}", use_container_width=False,
                       help=f"Open investigation for {name}"):
            open_investigation(cid)
            st.rerun()

        c[2].markdown(
            f'<div style="padding:4px 0">{score_badge(score)}</div>',
            unsafe_allow_html=True,
        )
        c[3].markdown(
            f'<div style="padding:4px 0">{flags_html}</div>',
            unsafe_allow_html=True,
        )
        c[4].markdown(
            f'<div style="padding:6px 0;font-size:0.82rem;color:#546e8a">{ctype}</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Pagination controls ────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    dp1, dp2, dp3 = st.columns([1, 2, 1])
    with dp1:
        if st.button("← Previous", key="db_prev", disabled=(db_page == 0),
                     use_container_width=True):
            st.session_state["db_page"] = db_page - 1
            st.rerun()
    with dp2:
        st.markdown(
            f'<div style="text-align:center;padding:8px;font-size:0.85rem;color:#546e8a">'
            f'Page {db_page + 1} of {total_pages} · {total:,} customers</div>',
            unsafe_allow_html=True,
        )
    with dp3:
        if st.button("Next →", key="db_next", disabled=(db_page >= total_pages - 1),
                     use_container_width=True):
            st.session_state["db_page"] = db_page + 1
            st.rerun()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    inject_styles()
    init_db()

    # Tabs FIRST so they pin to the top of the viewport.
    tab_queue, tab_log, tab_db = st.tabs(
        ["Alert Queue", "Decision Log", "Customer Database"])

    render_sidebar()

    with tab_queue:
        render_queue_tab()
    with tab_log:
        render_decision_log_tab()
    with tab_db:
        render_database_tab()

    # Render the modal if one is open. Streamlit's st.dialog renders on top
    # of whatever tab is active, so the user never has to leave the queue.
    if st.session_state.get("modal_open") and st.session_state.get("modal_customer_id"):
        render_investigation_dialog(st.session_state["modal_customer_id"])


if __name__ == "__main__":
    main()  # entrypoint

