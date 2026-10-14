# Clean Railway redeploy (keep your database)

## Do NOT delete the Postgres database
Deleting the whole Railway *project* can wipe data. Only redeploy the **web app** service.

## Recommended steps

1. Push these files to GitHub **repo root** (not a nested folder):
   - server.py
   - ops_upgrade.py
   - facility_flow.py
   - learning_data.py
   - erp_extension.py
   - logistics_flow.py
   - ifrs_reports.py
   - templates/ops_section.html
   - templates/main_dashboard.html
   - templates/staff_dashboard.html
   - templates/base.html (if present at root, keep root as source of truth)

2. On Railway → your **web service** (not the Postgres service):
   - Settings → Root Directory = **empty / repo root** (not Project-Financial-Analysis-Workflow-ERP/nested)
   - Deploy from GitHub `main` (or reconnect repo)
   - Optional: Settings → Clear build cache → Redeploy

3. After deploy, open:
   https://financeerp.knowsoft.org.uk/upgrade-status
   You must see: `build=SAFE-URLFOR-2026-10-14`
   If you still see `build=UPGRADE-2026-10-11`, the new code is **not** live.

4. Log in → /dashboard

## If you delete the web service only
- Recreate web service from same GitHub repo
- Re-link **same** Postgres / DATABASE_URL
- Re-set SECRET_KEY and other env vars
- Do **not** create a new empty database unless you want a full data reset

## Full project delete
Only if you accept losing the service config. **Keep the Postgres plugin** attached or export a backup first from /admin/backup.
