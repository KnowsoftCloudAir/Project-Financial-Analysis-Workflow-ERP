# Upload these files to fix the live crash + restore upgrades

## Why the site was broken
1. `ModuleNotFoundError: No module named 'wsgi'` → `wsgi.py` missing in the container
2. Home page HTTP 500 → public home path not hardened
3. Features unchanged → old Oct 9/10 code still deployed

## Railway Start Command (Settings → Deploy)
```
gunicorn server:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120
```
Root Directory: leave **empty**

## Files in this zip (copy to repo ROOT, overwrite)

### Must overwrite at repository root
| File | Purpose |
|------|---------|
| `wsgi.py` | Gunicorn entry (fixes ModuleNotFoundError) |
| `Procfile` | `web: gunicorn wsgi:app ...` |
| `server.py` | Hardened `/` and `/about`, `/debug-home`, upgrade marker |
| `ops_upgrade.py` | Inventory Returned columns + balances |
| `logistics_flow.py` | Client assigned list facility filter |
| `workflow_upgrade.py` | RFQ workflow + cash recon |
| `requirements.txt` | Dependencies |
| `runtime.txt` | Python version hint |

### templates/ (overwrite these)
- `public_home.html`, `public_base.html`, `public_about.html` — public home
- `error.html`, `base.html`, `login.html`, `staff_dashboard.html`
- `ops_inventory.html` — inventory sheets with Returned
- `wf_*.html` — RFQ + cash recon UI

### static/ (overwrite if missing on server)
- `css/app.css`, `icons/*`, `branding/*`, `img/*`, `manifest.json`

## Upload methods

### A) GitHub web UI
1. Open https://github.com/KnowsoftCloudAir/Project-Financial-Analysis-Workflow-ERP
2. Upload each root `.py` / `Procfile` / `requirements.txt` (click file → pencil or “Add file”)
3. Upload into `templates/` and `static/` the same way
4. Commit to **main**
5. Railway auto-deploys (or click Redeploy)

### B) Git CLI (preferred)
```bash
cd Project-Financial-Analysis-Workflow-ERP
# unzip this package OVER the repo root
unzip -o UPLOAD_FIX_2026-10-11.zip
git add -A
git status
git commit -m "UPGRADE-2026-10-11: wsgi + home harden + inventory + RFQ + cash recon"
git push origin main
```

## After deploy — verify
1. https://financeerp.knowsoft.org.uk/upgrade-status  
   Must show: `UPGRADE-2026-10-11-inventory-rfq-cash-clients`
2. https://financeerp.knowsoft.org.uk/login  
   Banner must say **Build UPGRADE-2026-10-11**
3. https://financeerp.knowsoft.org.uk/  
   Home page loads (not 500)
4. If home still fails: https://financeerp.knowsoft.org.uk/debug-home  
   Copy the text and send it for the next fix

## Do NOT
- Delete the whole repo then partially re-upload (that removed `wsgi.py` before)
- Set Root Directory to a subfolder
- Use Render only if the domain points at **Railway**
