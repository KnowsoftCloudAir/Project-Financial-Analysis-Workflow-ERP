# Kwealth upgrades applied

Files to copy into your OneChurchgate checkout (overwrite):

1. `app/routers/kwealth.py`  
   - Added `POST /member/kwealth/books/delete` (ownership check, soft-delete, file unlink, redirect).  
   - Added `GET /member/kwealth/quote-sculpture`.

2. `templates/kwealth/home.html`  
   - Link to Quote Sculpture panel.

3. `templates/kwealth/quote_sculpture.html` (new)  
   - Dedicated panel: quote, scroll type, calligraphy font, size, author → full-screen golden feather writing animation. Ends with author or “Anonymous”.

4. `templates/kwealth/books.html`  
   - Delete button already present; JS now does immediate option removal + confirmation.

5. `templates/members/portal.html`  
   - Prayer request board converts free text into Bible-reference prayer points and offers per-point / all-points voice reading (Speech Synthesis).

After deploy, visit:
- /member/kwealth/books → delete personal books safely  
- /member/kwealth/quote-sculpture → animation  
- /member/portal → Prayer panel
