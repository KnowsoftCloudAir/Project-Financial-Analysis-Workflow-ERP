# CONTRAconnect / Finance ERP — error page & professional templates (2026-10-09)

## What was fixed

### 1. Budget & inventory error pages
- **Root cause**: raw SQL used `is_active = 1`, which fails on PostgreSQL when the column is boolean (`true`/`false`).
- **Fix**: all such queries now use `(is_active IS TRUE OR is_active = 1)` so they work on both Postgres (Render) and SQLite.
- Files: `ops_upgrade.py`, `facility_flow.py`, `fmss_align.py`, `workflow_upgrade.py`.
- Inventory and budget routes also catch query failures and return an empty professional screen instead of a 500.

### 2. Branded full-page error (never a blank/stack page again)
- New template: `templates/error.html`
- Uses CONTRAconnect / app logo from branding, clear code (403/404/405/500), short message, and:
  - **← Go back** (browser history)
  - Sign in
  - Home
- Registered in `server.py` via `@app.errorhandler` for 403, 404, 405, 500 and unhandled exceptions.

### 3. Professional outlook for key screens
Templates restyled with consistent teal/navy hero headers, status pills, readable tables:
- `ops_inventory.html` — inventory position by warehouse / kiosk / PHC
- `ops_budget_template.html` — project budget vs actual
- `fin_variance.html` — variance report
- `fin_payments.html` — payment requests & expenses
- `expense_list.html` — project expense requests
- `ops_dispatch_list.html` / `ops_dispatch_form.html` — dispatch notes

## How to deploy on https://financeerp.knowsoft.org.uk/

1. Copy these files into the running app tree (same paths under the repo root):
   - `server.py`
   - `ops_upgrade.py`
   - `facility_flow.py`
   - `fmss_align.py`
   - `workflow_upgrade.py`
   - `templates/error.html` (new)
   - `templates/ops_inventory.html`
   - `templates/ops_budget_template.html`
   - `templates/fin_variance.html`
   - `templates/fin_payments.html`
   - `templates/expense_list.html`
   - `templates/ops_dispatch_list.html`
   - `templates/ops_dispatch_form.html`
2. Commit and push to the branch that Render (or your host) deploys from, **or** replace the files on the server and restart the web process.
3. Confirm after deploy:
   - `/ops/inventory` and `/ops/budget-template` load without error.
   - Visit a bad URL (e.g. `/this-does-not-exist`) → branded error page with **Go back**.
   - Finance payments, expenses, bank, variance, dispatch notes look consistent with the inventory/budget style.

## Note on login
Production may use a different `ADMIN_EMAIL` / `ADMIN_PASSWORD` than the seed defaults in the README. Use the credentials provisioned on the host environment.
