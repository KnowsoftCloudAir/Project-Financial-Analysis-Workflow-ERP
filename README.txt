FIX: Program Core menu + RFQ products from admin/products

1. templates/base.html
   - Removed "Client feedback" under Program Core sidebar
   - Program Core now only: Learning, reports, homepage

2. erp_extension.py
   - RFQ commodity dropdown loads from same products table as /admin/products
   - Uses Product ORM first, then SQL fallbacks
   - Warns if catalogue is empty

Upload both files to GitHub ROOT (overwrite), push main, redeploy Railway.
