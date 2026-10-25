# Why the Reading Room was not opening

The library was linking to the same `/member/kwealth/books` endpoint with `book_id`, so the library template itself rendered the selected book. The repository also did not have the dedicated `/member/kwealth/books/reading-room` GET route that the new links require.

This package separates the two views:

- `/member/kwealth/books` = clean 3D Book Library only.
- `/member/kwealth/books/reading-room?book_id=<ID>` = dedicated Reading Room.

The supplied `apply_reading_room_fix.py` adds the missing FastAPI route and enforces the personal-book upload rules on the server.

The book covers wrap long titles/authors inside the cover, and the dashboard clock template is included.
