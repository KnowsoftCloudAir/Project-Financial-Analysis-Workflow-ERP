# Learning Data Module – Integration Guide

## What this adds

In-app data collection for **Headline (H)** and **LQ1–LQ11** from  
`Benin_City_Learning_Data_Template.xlsx`.

| Feature | Detail |
|--------|--------|
| Fillable templates | One form per LQ with the same input fields as the Excel yellow cells |
| Audit trail | Every submission stores **staff name, email, date, time (UTC)** |
| Computed outputs | Same indicators as the Excel grey formula cells (conversion rates, NPS, unit cost, etc.) |
| Analysis | Scorecard vs targets + respondent-by-respondent log |
| PM assignment | Project Manager / Program Admin / General Admin assign staff to each LQ |

Password management, roles, onboarding, and force-change flows are **unchanged** — this module only uses existing `User`, `login_required`, and role helpers (`project_manager`, staff roles, etc.).

---

## Files to add

```
learning_data.py                    → project root (next to server.py)
templates/learning_hub.html
templates/learning_form.html
templates/learning_submission.html
templates/learning_analysis.html
templates/learning_assign.html
```

Copy the five HTML files into your existing `templates/` folder.

---

## Wire into `server.py`

### 1. Import and register (near the bottom, before `if __name__ == '__main__':`)

```python
from learning_data import register_learning_routes

register_learning_routes(
    app, db, User, login_required, current_user,
    STAFF_ROLES, ADMIN_ROLES, PROGRAM_OPS_ROLES,
    log_activity, _is_admin_role,
)
```

### 2. Optional nav link

In `templates/base.html` (or staff dashboard nav), add for staff/PM:

```html
{% if current_user.is_authenticated and current_user.role in [
  'project_manager','program_admin','general_admin','admin',
  'finance_analyst','mel_consultant','rh_consultant',
  'demand_consultant','sdoc_consultant','logistics_consultant'
] %}
<a class="nav-link" href="{{ url_for('learning_hub') }}">Learning Data</a>
{% endif %}
```

### 3. Deploy

```bash
git add learning_data.py templates/learning_*.html
git commit -m "Add Learning Data module: LQ1-LQ11 templates, PM assign, analysis"
git push
```

On first request after deploy, `db.create_all()` creates:

- `learning_assignments`
- `learning_submissions`

---

## Routes

| URL | Who | Purpose |
|-----|-----|---------|
| `/learning` | Staff / PM | Hub – open templates, recent submissions |
| `/learning/template/<LQ>` | Assigned staff / PM | Fill form and save |
| `/learning/submission/<id>` | Staff / PM | View one submission (inputs + computed) |
| `/learning/analysis` | Staff / PM | Scorecard + respondent log |
| `/learning/assign` | PM / Program / General Admin | Assign or revoke staff per LQ |
| `/learning/export/excel` | Staff / PM | **Download Excel** – Dashboard + Headline + LQ1–LQ11 + Audit + Targets |
| `/learning/export/pptx` | Staff / PM | **Download PPT report** – title, scorecard, one slide per LQ |
| `/learning/api/submissions` | Staff / PM | JSON feed |

### Excel workbook sheets

| Sheet | Content |
|-------|---------|
| Dashboard | Scorecard: latest value vs target, staff, date/time, entry count |
| Headline, LQ1_Experience … LQ11_Sustain | All submissions: input columns + computed columns + staff/email/time audit |
| Audit_Log | Full respondent-by-respondent log with raw & computed JSON |
| Settings_Targets | Target reference table from the strategy / Excel template |

### PowerPoint slides

1. Title – Benin City pilot Learning Report  
2. Scorecard table (all LQs vs targets)  
3. One slide per H + LQ1–LQ11 (latest value, staff, period, recent respondents)  
4. Closing slide |

---

## Default demo accounts (existing seed)

| Role | Email | Password |
|------|-------|----------|
| Project Manager | pm@contraconnect.local | (see seed / change on first login) |
| Admin | admin@contraconnect.local | admin123 |

PM logs in → **Learning Data → Assign staff** → pick LQ + staff → staff fills templates → **Analysis** shows staff, date/time, and outputs vs targets.

---

## Mapping to Excel template

| LQ | Primary indicator | Target (Settings sheet) |
|----|-------------------|-------------------------|
| H | Uptake conversion rate | 60% |
| LQ1 | Avg client satisfaction (1–5) | 4.00 |
| LQ2 | Funnel conversion | Monitor |
| LQ3 | Net Promoter Score | 40 |
| LQ4 | % unassisted completion | 50% |
| LQ5 | Monthly attrition rate | 5% limit |
| LQ6 | Best site category | Monitor |
| LQ7 | Most-used method | Monitor |
| LQ8 | Unit cost per client | Monitor |
| LQ9 | Best channel | Monitor |
| LQ10 | Data-sync success rate | 95% |
| LQ11 | % co-financing achieved | Monitor |

Computed fields mirror the grey formula columns in each LQ sheet.
