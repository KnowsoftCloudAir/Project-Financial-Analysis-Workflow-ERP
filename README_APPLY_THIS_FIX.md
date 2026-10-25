# OneChurchgate — Book Library / Reading Room / Dashboard Clock Fix

This patch is prepared against the current `KnowsoftCloudAir/OneChurchgate` structure.

## What is fixed

1. **3D Book Library remains a clean library page.**
2. **Knowsoft Books** and **Personal Books** are displayed separately.
3. Book title and author text wrap inside the 3D book cover.
4. Clicking a book now targets the separate route:
   `/member/kwealth/books/reading-room?book_id=<ID>`
5. The Reading Room is a separate page containing the reading controls already built for Kwealth: Read, 3D scenes, Music, themes, fonts, page flip, jump-to-page, voice/read-aloud, and full-screen controls.
6. The Reading Room has visible **Back to Book Library** and **Kwealth** buttons.
7. Server-side personal-book validation is enforced by the supplied router patch: PDF/TXT/DOCX, max 3 personal books, max 4,000,000 bytes per book.
8. The dashboard clock is moved out of the Jinja `title` block. In the current repository it was being rendered inside `<title>`, which is why the clock did not appear. It is now rendered as normal dashboard HTML and remains visible/draggable.

## Files to copy

- `app/templates/kwealth/books.html`
- `app/templates/kwealth/reading_room.html`
- `app/templates/members/portal.html`
- `apply_reading_room_fix.py`

## Backend step — REQUIRED

The GitHub repository's current `app/routers/kwealth.py` still serves `kwealth/books.html` when `book_id` is supplied. The supplied `apply_reading_room_fix.py` inserts the separate Reading Room GET route and tightens the upload endpoint.

Run from the repository root:

```bash
python apply_reading_room_fix.py
```

Then deploy/restart the application.

## Resulting navigation

Kwealth → Book Library → click book → **Reading Room page** → Back to Book Library / Kwealth.

The library URL remains `/member/kwealth/books`.
The reader URL is `/member/kwealth/books/reading-room?book_id=<ID>`.
