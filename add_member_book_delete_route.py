#!/usr/bin/env python3
"""
Add member-level personal-book delete endpoint to app/routers/kwealth.py

Run from the OneChurchgate project root:
    python add_member_book_delete_route.py
"""
from pathlib import Path

ROUTER = Path("app/routers/kwealth.py")

ROUTE = '''
@router.post("/member/kwealth/books/delete")
async def kwealth_books_delete(
    book_id: int = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Allow a member to delete a personal book they uploaded (owner_user_id == user.id)."""
    book = session.get(KwealthBook, book_id)
    if not book or not getattr(book, "is_active", True):
        return RedirectResponse("/member/kwealth/books?deleted=0", status_code=303)
    own = getattr(book, "owner_user_id", None)
    # Only the owner may delete; admin/shared books (owner is None) cannot be deleted here
    if own is None or int(own) != int(user.id):
        return RedirectResponse("/member/kwealth/books?deleted=0", status_code=303)
    # Soft-delete preferred
    try:
        book.is_active = False
        session.add(book)
        session.commit()
    except Exception:
        session.rollback()
        try:
            session.delete(book)
            session.commit()
        except Exception:
            session.rollback()
            return RedirectResponse("/member/kwealth/books?deleted=0", status_code=303)
    return RedirectResponse("/member/kwealth/books?deleted=1", status_code=303)

'''

def main():
    if not ROUTER.exists():
        raise SystemExit(f"Missing {ROUTER}. Run from the OneChurchgate project root.")
    s = ROUTER.read_text(encoding="utf-8")
    if '/member/kwealth/books/delete' in s:
        print("Route already present — nothing to do.")
        return
    # Insert after the upload route
    marker = '@router.post("/member/kwealth/books/upload")'
    if marker not in s:
        # fallback: append near other member book routes
        marker2 = '@router.post("/member/kwealth/books/progress")'
        if marker2 in s:
            s = s.replace(marker2, ROUTE + "\n" + marker2, 1)
        else:
            raise SystemExit("Could not find a safe insertion point in kwealth.py")
    else:
        # Find end of the upload function and insert after it
        idx = s.find(marker)
        # Find the next @router after upload
        next_router = s.find("\n@router.", idx + len(marker))
        if next_router < 0:
            raise SystemExit("Could not locate end of upload route")
        s = s[:next_router] + "\n" + ROUTE + s[next_router:]
    ROUTER.write_text(s, encoding="utf-8")
    print("Added /member/kwealth/books/delete route to", ROUTER)

if __name__ == "__main__":
    main()
