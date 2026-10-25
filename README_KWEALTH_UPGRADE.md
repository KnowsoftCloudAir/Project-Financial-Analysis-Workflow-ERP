# Kwealth Books Upgrade — OneChurchgate

Ready-to-merge package for GitHub: https://github.com/KnowsoftCloudAir/OneChurchgate

## What this upgrade does

1. **Scene replaces the book (no dual screens)**  
   When Scene is on, the physical book sheet is fully hidden. Only the 3D/CSS scene is visible, with book text overlaid on the scene surface while the voice reads.

2. **Better word display + fonts**  
   - New entrance styles: fill, fade-up, typewriter, scale-in, glow, center-block  
   - Extra fonts: Playfair Display, Cinzel, Inter (Google Fonts)  
   - Stronger text shadow / backdrop for readability over animations  

3. **Swipe / finger navigation**  
   - Swipe **left / right** → next / previous page  
   - Swipe **up / down** (when Scene or Fullscreen is on) → next / previous 3D scene  
   - Mouse drag supported on desktop  

4. **User uploads (already in backend)**  
   Member endpoints already support multi-file book + BGM upload:
   - `POST /member/kwealth/books/upload`
   - `POST /member/kwealth/bgm/upload`  
   This package focuses UI/UX on the reader experience.

5. **General Admin multi-book upload**  
   - New route: `POST /admin/library/books` (multiple PDF/TXT/DOC/DOCX)  
   - Updated `templates/admin/library.html` with multi-file picker  

## Files in this package

```
templates/kwealth/books.html          ← upgraded reader (replace existing)
templates/admin/library.html          ← multi-book admin UI (replace existing)
app/routers/admin.py                  ← includes multi-book route (replace existing)
app/routers/admin_library_books_multi.py  ← route snippet only (reference)
app/routers/kwealth.py                ← current member router (reference; already multi-upload)
README_KWEALTH_UPGRADE.md             ← this file
```

## How to apply on GitHub

### Option A — Copy files into your clone

```bash
git clone https://github.com/KnowsoftCloudAir/OneChurchgate.git
cd OneChurchgate

# Backup
cp templates/kwealth/books.html templates/kwealth/books.html.bak
cp templates/admin/library.html templates/admin/library.html.bak
cp app/routers/admin.py app/routers/admin.py.bak

# Copy upgraded files from this zip
cp /path/to/upgrade/templates/kwealth/books.html templates/kwealth/books.html
cp /path/to/upgrade/templates/admin/library.html templates/admin/library.html
cp /path/to/upgrade/app/routers/admin.py app/routers/admin.py

git add templates/kwealth/books.html templates/admin/library.html app/routers/admin.py
git commit -m "Kwealth: scene replaces book, text overlay, swipe, admin multi-upload"
git push
```

### Option B — Manual admin route only

If you prefer not to replace whole `admin.py`, paste the contents of  
`app/routers/admin_library_books_multi.py` into `app/routers/admin.py`  
near the existing `/library/book` handler, and ensure `List` is imported from `typing`.

## Acceptance checks after deploy

1. Open a book → turn **Scene** on → book sheet disappears; only scene + text remain.  
2. Enter **Fullscreen** → words appear on the scene while voice reads.  
3. Change **Word style** (fade-up, glow, etc.) and **Font**.  
4. Swipe left/right to change pages; swipe up/down to cycle scenes.  
5. Admin → Library → select multiple PDFs → Upload books → success count shown.  
6. Member can still upload own books and BGM via existing endpoints.

## Notes

- Existing free-book / subscription rules are unchanged.  
- WebGL scenes (`jupiter_close`, `milkyway`, etc.) continue via `CGWebGL`.  
- Text overlay uses `#sceneTextOverlay` / `#overlayText`.  
- Swipe threshold ≈ 55px (touch) / 80px (mouse).
