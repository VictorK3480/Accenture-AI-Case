---
name: nordikbank-workbench-ui
description: Use when the user is designing or building the analyst workbench UI for the NordikBank AML case — the web app that compliance analysts would use to review flagged customers. Triggers on "workbench", "dashboard", "UI", "frontend", "alert queue", "investigation view", "customer drill-down", "score explanation", "demo", or any reference to the third deliverable (the analyst-facing application). Do NOT use for model training (that's the modeling skill) or raw data analysis (that's the EDA skill).
---

# NordikBank AML — Analyst Workbench UI

## Business context

The third deliverable for the NordikBank case is a **web-based analyst workbench** — the tool that compliance analysts would use day-to-day to review the model's flagged customers. This is what gets demoed live to the panel. The brief states explicitly that a live demo of the workbench is worth more than slides of methodology.

The audience for the demo is mixed technical/business. The workbench has to make sense to a compliance analyst, not just a data scientist.

## What the workbench must do

Four core views. Everything else is optional polish.

1. **Prioritized alert queue** — list of customers ranked by predicted probability, descending. Show enough at-a-glance to triage: customer ID, type (personal/corporate), risk score, top 2–3 driver features, and a status (new / under review / cleared / escalated).

2. **Customer investigation view** — drill into one customer. Show their profile (KYC, PEP status, country, occupation/industry), account list, recent transaction sample, baseline behavioral features, and historical alerts.

3. **Score explanation** — *why* did the model rank this customer high? Show the top contributing features (SHAP values or equivalent) translated into plain language. The form should be "[customer's metric] is [N×] the [cohort] average" — but use the *actual values from the model output*, never hardcode example numbers.

4. **Investigation workflow** — the analyst can mark a customer as cleared, under review, or escalated, and add a free-text note. For the demo: persist this to a small file or sqlite database so a refresh doesn't wipe state. Pure in-memory state will be lost on reload, which is risky during a live demo.

## Data the UI needs at runtime

The workbench is downstream of the modeling pipeline. It needs:
- **Predictions**: per-customer probability + the top-N driver features. Typically loaded from `predictions.csv` and `prediction_drivers.csv` (produced by the modeling skill). If these don't exist when starting UI work, ask the user how predictions will be supplied — don't fabricate them.
- **Customer data**: the case CSVs (customers, accounts, transactions, alert_history, country_risk). Load these from wherever the user has placed them.
- **Cohort baselines** for the "vs. cohort average" explanations: precomputed averages per customer segment (e.g. personal vs. corporate). Either compute these once on app start or precompute and load.

If any of these are missing when implementing a feature that needs them, stop and confirm with the user — don't invent placeholder data that might survive into a demo.

## Stack

**Not yet decided.** When the user picks one, replace this section with their choice. Until then, design recommendations stay framework-agnostic — talk about views, components, and data flow, not specific libraries.

When the user is choosing a stack, the trade-offs that matter for this case (in rough order):
- Speed to build a working demo
- Live-demo reliability
- Visual polish for a mixed technical/business panel
- Team familiarity

Streamlit and Gradio are typically faster to ship; React/Next.js typically offers more visual control; Dash sits in between. These are tendencies, not rules — let the team's existing skills weigh in.

## Design principles

- **The analyst is not a data scientist.** Explanations in plain language. No raw SHAP plots without translation, no model jargon in the UI.
- **One customer per page** for the investigation view, not a dashboard-of-dashboards. The investigation view is the heart of the demo.
- **Show the evidence, not just the score.** A risk score of 0.87 means nothing without "here's why" — model transparency is the whole regulatory point.
- **Make it skimmable.** An analyst triaging a queue doesn't read paragraphs. Tables, badges, sparklines.
- **Avoid dark patterns.** Don't pre-select "escalate" or hide the "clear" action. The UI should be neutral.

## What to put in the alert queue row

The panel will scan this in seconds. Suggested columns:
- Customer ID + type (personal/corporate badge)
- Risk score (number + color band)
- 2–3 short driver chips (e.g. "high cash %", "FATF-grey counterparty", "PEP") — these come from `prediction_drivers.csv`
- Country
- Status badge

Don't put 12 columns. Don't put the full SHAP breakdown. That's the next click.

## What to put in the investigation view

Three sections, top to bottom:
1. **Header**: who is this customer (KYC summary, status pills for PEP/sanctions/high-risk-country)
2. **Why flagged**: top contributing features in plain language, each with the customer's value vs. their cohort baseline
3. **Evidence**: tabs for Accounts, Recent Transactions, Historical Alerts. Don't try to show all 77k transactions in the dataset — sample, paginate, or aggregate.

## Demo discipline

- **Pick one flagged customer in advance** to walk through. Rehearse the click path.
- **Have a backup screenshot deck** in case the demo crashes.
- **Time it.** A two-minute walkthrough beats a ten-minute one.

## Frontend design

If the public `frontend-design` skill is available in the environment (typically at `/mnt/skills/public/frontend-design/SKILL.md` in this Claude environment), read it before writing UI code — it covers component patterns, design tokens, and styling. If it's not present, default to clean, simple component design and confirm styling preferences with the user.

## How to push back

- If the user wants to add a feature that's cool but not on the demo path, ask whether it survives a 5-minute demo cut. If not, deprioritize.
- If the user wants to show raw model output (SHAP plots, probability tables) without translation, push for the analyst-language version.
- If the user is building a third dashboard before the investigation view works, redirect — the investigation view is the demo.
- If predictions or driver data don't exist yet, don't generate fake data to "make the UI work" — ask how the data will arrive.

## What "done" looks like

A working app where the user can: open the queue, click a high-scored customer, see why they were flagged in plain language, see their accounts and recent transactions, mark them as escalated/cleared, and have that persist across a refresh. Everything else is polish.
