RFQ + Learning + Client feedback fix — 11 Oct 2026

Upload to GitHub ROOT (overwrite):

  workflow_upgrade.py
  learning_data.py
  server.py (if you have latest)
  templates/wf_rfq_form.html
  templates/wf_rfq_detail.html
  templates/learning_hub.html
  templates/client_feedback_hub.html
  templates/client_feedback_dashboard.html

RFQ flow after deploy:
  1. /ops/rfq/new — up to 10 catalogue lines (qty, unit, optional price/total), TOR PDF
  2. Submits → Program Manager approval (pending_review)
  3. PM Approves → status approved
  4. Procurement: Create vendor share link on RFQ detail page

Learning:
  - Report dashboard access fixed for admins
  - Client feedback icon on Learning hub → /learning/feedback (share link + list + ambassadors)

Verify:
  /ops/rfq/new
  /learning
  /learning/feedback
  /learning/report
