# Merge: FMSS ERP features → Project-Financial-Analysis-Workflow-ERP

## What was done
- Ported **procurement LTA workflow**, vendors, COA, fixed assets, GRN, and invoice→finance from FMSS into this single-organisation CONTRAconnect app.
- **Password / auth system unchanged** — still Flask-Login, email login, `auth_mail.py`, forgot/reset, onboarding.
- **No multi-company**: one organisation only (Benin City / CONTRAconnect). Removed company slug login and superadmin company approval from the merged feature set.

## How to use
1. Log in with existing accounts (e.g. `admin@contraconnect.local` / env `ADMIN_PASSWORD` or default `Contra@Admin2026!`).
2. Sidebar → **ERP / Procurement**.
3. Optional: **Seed demo data** on the ERP dashboard (RFQ-FP-LOT1, vendors, PO/GRN/invoice).
4. Flow: RFQ → technical pass/fail → lowest price → Award+PO → GRN (all conditions) → Invoice → **Send to Finance** (creates Expense Request).

## New files
- `erp_extension.py` — models + routes (blueprint `/erp`)
- `templates/erp_*.html` — UI

## Unchanged
- All existing commodity, facility, encounter, cost analytics, learning data, password reset, staff approvals.
