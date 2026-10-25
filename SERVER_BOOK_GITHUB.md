# Churchgate permanent Knowsoft server book

This package contains the permanent Knowsoft server book **Araby — James Joyce**.

## Deployment

Copy the contents of `server_books/` into the application's server-side/admin-global book storage used by the Kwealth Books endpoint. The book must be loaded into `admin_books` so the Book Lib wall can render it permanently from the server collection.

The Book Lib template intentionally does not create a separate default-book record. It renders the permanent book from `admin_books`, and the server book therefore counts as a normal server book.

## Personal books

The Book Lib upload control is for members' personal books only. The UI accepts TXT/text files. Users are instructed to convert books to TXT and remove pictures/images before uploading for simpler, faster reading.

## Reader

Clicking the permanent wall book opens the normal reader route with all reading controls/settings: theme, font, font size, page flip, page jump, voice/rate, paragraph pause, music, 3D ambience and the Knowsoft wall clock.

## Clock

The in-book Knowsoft clock uses the browser/device `Date` time and updates continuously with `requestAnimationFrame`, so it follows the computer/device local time rather than a hard-coded time.
