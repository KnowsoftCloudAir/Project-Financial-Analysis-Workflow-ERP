COMPLETE UPLOAD PACKAGE — 11 Oct 2026
=====================================

Previous partial zip was missing critical modules. This package includes ALL of:

ROOT:
  server.py, wsgi.py, Procfile, requirements.txt, runtime.txt
  ops_upgrade.py, logistics_flow.py, workflow_upgrade.py, facility_flow.py
  finance_core.py, erp_extension.py, learning_data.py, auth_mail.py
  fmss_align.py, ifrs_reports.py

templates/  (all HTML — 120+)
static/     (css, icons, branding, img, js, splash)

HOW TO UPLOAD
1. Unzip OVER the root of Project-Financial-Analysis-Workflow-ERP
2. git add -A && git commit -m "Complete UPGRADE-2026-10-11 modules + templates" && git push origin main
3. Railway Start Command:
   gunicorn server:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120
4. Redeploy

VERIFY
  /upgrade-status  → UPGRADE-2026-10-11-...
  /debug-routes    → all endpoint_ok and import_ok (no MISSING / FAIL)
  /login           → Build UPGRADE-2026-10-11

If a page still errors after login, the error card will now show the exception type
(e.g. BuildError, OperationalError). Copy that text and report it.
