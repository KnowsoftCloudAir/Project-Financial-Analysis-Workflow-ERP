# CONTRAconnect logistics + finance fixes — 2026-10-10

## Confirmed repository access
Work continues on the live Flask ERP (`financeerp.knowsoft.org.uk` / Project-Financial-Analysis-Workflow-ERP pattern).
`KnowsoftCloudAir/FMSS_Smark_Multi_user_online` was also cloned for reference (FastAPI stack).

## Strict stock logic implemented

1. **Main Warehouse** (permanent, auto-created with sample opening stock)
2. **Goods Received Note** (`/ops/grn`)  
   - Item, qty, description, unit cost, total value, shelf life  
   - Updates product catalogue cost + shelf life  
   - Stock into Main Warehouse  
   - Journal: **Dr Commodity stock (1300) / Cr Cash (1000)**
3. **Dispatch** (`/ops/dispatch-move`)  
   - Moves stock Main Warehouse → kiosk/PHC  
   - **PDF dispatch note** after each dispatch (not a menu icon)
4. **Inventory** (`/ops/inventory`)  
   - **View only** (no input forms)  
   - Excel / PDF export (PM/admin: all sites; facility user: own site)
5. **Product catalogue** (`/ops/catalogue`)  
   - Shelf life + total qty across warehouse + all outlets + total value
6. **Uptake Administration** (`/ops/uptake`) — Admin, PM, privileged users  
   - **Uptake form**: up to 10 commodity lines + method, quality, testimony, complaints → **Administer**  
     → reduces service-point stock; journal **Dr Commodity expensed (5100) / Cr Commodity stock (1300)**  
   - **Transfer form**: between outlets or back to warehouse → pending PM/Admin approval  
   - **Transfers list**: approve / accept / reject → certificate PDF after accept  
   - **Client assigned list**: open request / contact details

## Facilities / dispatch 500s
- Facility list and create wrapped so DB errors surface as flash messages, not blank 500
- Dispatch falls back to `/ops/dispatch-move` if legacy DispatchNote model is unbound
- Warehouse helper prefers Main Warehouse

## Deploy
Copy all files from this package into the app root (especially):
- `logistics_flow.py` **(new)**
- `server.py`, `ops_upgrade.py`, `facility_flow.py`, `workflow_upgrade.py`, `finance_core.py`
- `templates/logistics_*.html`, `templates/ops_inventory.html`, `templates/base.html`, `templates/error.html`
- Restart the web process

After deploy, open `/upgrade-status` — should show `UPGRADE-2026-10-10` and the new paths.
