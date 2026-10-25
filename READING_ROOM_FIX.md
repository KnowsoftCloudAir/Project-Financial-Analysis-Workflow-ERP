# Reading Room fix

Each library book now opens `/member/kwealth/books/reading-room?book_id=...`, a separate Reading Room page. The library stays a clean 3D wall; the Reading Room contains the existing Read, 3D scenes, Music, themes, fonts, page flip and full-screen controls, with visible navigation back to Book Library and Kwealth.

Book titles/authors wrap neatly on the 3D cover.

`apply_reading_room_fix.py` patches `app/routers/kwealth.py` and enforces personal uploads server-side: PDF/TXT/DOCX only, maximum 3 personal books per member, maximum 4 MB per book.
