FULL SITE TEMPLATES + MODULES
==============================
Why pages crashed site-wide:
  The deploy was missing most HTML templates (login, finance, ops, erp, logistics, invoices…).
  Only ~50 templates were present; the app needs ~110+.

This zip has:
  - All root *.py modules (server, ops, erp, finance, learning, logistics, workflow, ifrs, facility…)
  - Full templates/ folder (~129 HTML files)

DEPLOY:
1. Extract to app ROOT (same folder as wsgi.py / Procfile)
2. Ensure templates/ is a folder at root with all HTML inside
3. Redeploy web service only (keep Postgres)
4. Hard refresh browser
5. Test:
   /dashboard
   /learning
   /ops/inventory
   /ops/rfq
   /finance/coa
   /expenses
   /erp/rfqs

Correct domain always: https://financeerp.knowsoft.org.uk/...
NOT https://learning/...
