# Deploy Learning Data (LQ1–LQ11) + Churchgate auth to financeerp.knowsoft.org.uk

## What this package fixes

Previously files sat on GitHub but **`server.py` never registered routes**, so live showed:

- `/learning` → **404**
- `/reset-password` (without path token) → **404**
- Forgot UI mentioned “6-digit code” but backend still used old long-token flash

This package includes a **patched `server.py`** that wires everything.

## Contents

| Path | Action |
|------|--------|
| `server.py` | **Replace** repo root `server.py` |
| `learning_data.py` | Copy to repo root |
| `auth_mail.py` | Copy to repo root |
| `templates/*.html` | Merge into `templates/` (overwrite matching names) |

## Steps (GitHub → Render)

```bash
cd Project-Financial-Analysis-Workflow-ERP

# From the unzipped package:
cp server.py .
cp learning_data.py .
cp auth_mail.py .
cp templates/learning_*.html templates/
cp templates/forgot_password.html templates/
cp templates/reset_password.html templates/
cp templates/confirm_registration.html templates/
cp templates/staff_dashboard.html templates/
cp templates/base.html templates/

git add server.py learning_data.py auth_mail.py templates/
git commit -m "Wire LQ1-LQ11 learning data, charts, Excel/PPT export, Churchgate password reset"
git push
```

Render will auto-deploy. On first request, tables `learning_submissions`, `learning_assignments`, `email_challenges` are created.

## Env vars (Render)

```
PUBLIC_BASE_URL=https://financeerp.knowsoft.org.uk
MAIL_HOST=...
MAIL_PORT=587
MAIL_USER=...
MAIL_PASSWORD=...
MAIL_FROM=noreply@knowsoft.org.uk
MAIL_FROM_NAME=CONTRAconnect
```

Optional: `MAIL_DISABLED=1` for log-only emails while testing.

## After deploy — verify

| URL | Expected |
|-----|----------|
| `/learning` | Hub with H + LQ1–LQ11 cards (login as PM/staff) |
| `/learning/analysis` | Scorecard + **bar / pie / line / doughnut** charts |
| `/learning/export/excel` | Downloads `.xlsx` |
| `/learning/export/pptx` | Downloads `.pptx` |
| `/forgot-password` | Sends 6-digit code + link |
| `/reset-password?email=…&code=…` | Reset form (no 404) |

## Who sees Learning Data

- **Project Manager / Program Admin / General Admin**: full hub, assign staff, all templates, analysis, downloads
- **Programme staff** (finance_analyst, mel_consultant, etc.): hub, fill templates, analysis, downloads
- Entry points: **sidebar “Learning Data (LQ)”** and **staff dashboard** cards

## Data flow

1. Staff/PM fills LQ template → saved to `learning_submissions` (staff name, email, UTC timestamp, raw + computed indicators)
2. Analysis page aggregates vs targets (60%, NPS 40, 95% sync, etc.) and draws charts
3. Excel export mirrors template structure (Dashboard, Headline, LQ1–LQ11, Audit, Targets)
4. PPT export: title, scorecard, one slide per LQ
