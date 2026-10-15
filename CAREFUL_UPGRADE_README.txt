CAREFUL UPGRADE on stable base (Project-Financial-Analysis-Workflow-ERP)
=======================================================================
Source base: KnowsoftCloudAir/Project-Financial-Analysis-Workflow-ERP
Features taken carefully from FMS-Multi-user-online nested ERP + prior fixes.

WHAT WAS ADDED (without full rewrite of nav):
1. GRN posts to Main Warehouse (create products if needed), closes RFQ, saves vendor, opens invoice
2. Inventory reads live stock_items; /ops/inventory/full expandable view
3. Uptake blocked when facility stock insufficient
4. Learning forms: client name, phone, Client Unique No.
5. ifrs_reports.py included (fixes ModuleNotFoundError)
6. Expenses: Remove sample data button; /admin/currency operating currency
7. BuildError protection: path-only section links + safe Jinja url_for
8. User manual not forced as navigation hub

DEPLOY:
- Upload/extract to Railway/GitHub REPO ROOT (same folder as Procfile)
- Do NOT nest under Project-Financial-Analysis-Workflow-ERP/...
- Keep Postgres DATABASE_URL
- After deploy open /upgrade-status — expect build=CAREFUL-UPGRADE-2026-10-15
- Then /dashboard, /ops/inventory, /learning

Do NOT delete the database.
