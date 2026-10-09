# CONTRAconnect / Finance ERP fixes — 2026-10-09 (v2)

## Inventory (your logic)
- **Main warehouse first** (facility name or type containing “warehouse”) — procurement is offloaded here.
  Columns: Commodity | Opening qty | Qty received | Qty dispatched | Facility dispatched to | Qty balance
- **Each other facility** (kiosk / PHC / other) on its own sheet:
  Columns: Commodity | Received qty | Administered qty | Transferred qty | Facility transferred to | Balance qty
- **System summary** across all sites:
  Item | Quantity | Total value (unit cost from product/procurement) | Administered last month | this month | projected next month | quarterly | semi-annual | annual
- Facility officers / approving officers can post receive, dispatch, transfer, administer on each sheet.
- **Dispatch is no longer a standalone menu page.** After a warehouse **Dispatch to outlet**, the system posts the stock movement and immediately offers a **downloadable dispatch-note PDF**.

## Bank reconciliation (restored)
- Hardened `/ops/bank` so missing cash accounts, empty ledgers, or tick-table issues no longer 500.
- Loads Cash / Asset accounts, ticks journal lines, bank vs cash-book difference, ADD/LESS statement fields, PDF and Excel — aligned with the Knowsoft FMSS bank reconciliation flow.

## Budget template
- Remains a **view** of recorded budget lines (Budget ID, Project, Expense code, Description, Start, End, Budget, Actual, Variance, Status) with Excel download. No change to the data model.

## Error page
- Branded CONTRAconnect full-page error with **Go back** for 403/404/405/500.

## Files to deploy
- `server.py`
- `ops_upgrade.py`
- `facility_flow.py`, `fmss_align.py`, `workflow_upgrade.py` (boolean SQL fix)
- `templates/error.html` (new)
- `templates/ops_inventory.html`
- `templates/ops_budget_template.html`
- `templates/fin_variance.html`
- `templates/fin_payments.html`
- `templates/expense_list.html`
- `templates/ops_bank.html` (existing, keep)
- `templates/base.html` (dispatch nav removed)
- `templates/ops_section.html` (dispatch cards removed)

Restart the web process after copy. Create at least one facility whose name includes “warehouse” so the warehouse sheet appears first.
