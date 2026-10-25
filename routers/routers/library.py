"""General books + reading background music (General Admin uploads; members read)."""
from pathlib import Path
from datetime import datetime
import uuid
import shutil

from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserRole, LibraryBook, ReadingMusic
from app.auth import require_user, require_roles, role_val

router = APIRouter(tags=["library"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

BOOK_DIR = Path("app/static/uploads/library_books")
MUSIC_DIR = Path("app/static/uploads/reading_music")
BOOK_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)


def _extract_text(path: Path, filename: str) -> str:
    name = filename.lower()
    try:
        if name.endswith(".txt") or name.endswith(".md"):
            return path.read_text(encoding="utf-8", errors="ignore")[:200000]
        if name.endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                parts = []
                for page in reader.pages[:200]:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t)
                return "\n\n".join(parts)[:200000]
            except Exception as e:
                return f"(Could not extract PDF text: {e})"
    except Exception as e:
        return f"(Read error: {e})"
    return ""


@router.get("/admin/library", response_class=HTMLResponse)
async def admin_library_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    books = list(session.exec(select(LibraryBook).order_by(LibraryBook.created_at.desc())).all())
    music = list(session.exec(select(ReadingMusic).order_by(ReadingMusic.created_at.desc())).all())
    return templates.TemplateResponse("admin/library.html", {
        "request": request, "user": user, "books": books, "music": music,
    })


@router.post("/admin/library/book")
async def admin_upload_book(
    title: str = Form(...),
    author: str = Form(""),
    description: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    fname_orig = file.filename or "book.pdf"
    ext = fname_orig.rsplit(".", 1)[-1].lower() if "." in fname_orig else "pdf"
    if ext not in ("pdf", "txt", "md"):
        raise HTTPException(400, "Upload PDF or text files")
    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 30 MB)")
    fname = f"book_{uuid.uuid4().hex[:10]}.{ext}"
    dest = BOOK_DIR / fname
    dest.write_bytes(data)
    text = _extract_text(dest, fname_orig)
    book = LibraryBook(
        title=title.strip(),
        author=(author or "").strip() or None,
        description=(description or "").strip() or None,
        file_path=f"/static/uploads/library_books/{fname}",
        text_content=text or None,
        is_active=True,
        uploaded_by=user.id,
    )
    session.add(book)
    session.commit()
    return RedirectResponse("/admin/library", status_code=303)


@router.post("/admin/library/book/{bid}/toggle")
async def admin_toggle_book(
    bid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    b = session.get(LibraryBook, bid)
    if b:
        b.is_active = not b.is_active
        session.add(b)
        session.commit()
    return RedirectResponse("/admin/library", status_code=303)


@router.post("/admin/library/book/{bid}/delete")
async def admin_delete_book(
    bid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    b = session.get(LibraryBook, bid)
    if b:
        try:
            p = Path("app") / b.file_path.lstrip("/")
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass
        session.delete(b)
        session.commit()
    return RedirectResponse("/admin/library", status_code=303)


@router.post("/admin/library/music")
async def admin_upload_music(
    title: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    fname_orig = file.filename or "track.mp3"
    ext = fname_orig.rsplit(".", 1)[-1].lower() if "." in fname_orig else "mp3"
    if ext not in ("mp3", "m4a", "ogg", "wav", "webm"):
        raise HTTPException(400, "Upload audio (mp3, m4a, ogg, wav)")
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "Audio too large (max 25 MB)")
    fname = f"read_{uuid.uuid4().hex[:10]}.{ext}"
    dest = MUSIC_DIR / fname
    dest.write_bytes(data)
    session.add(ReadingMusic(
        title=title.strip() or "Reading music",
        file_path=f"/static/uploads/reading_music/{fname}",
        is_active=True,
        uploaded_by=user.id,
    ))
    session.commit()
    return RedirectResponse("/admin/library", status_code=303)


@router.post("/admin/library/music/{mid}/delete")
async def admin_delete_music(
    mid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    m = session.get(ReadingMusic, mid)
    if m:
        try:
            p = Path("app") / m.file_path.lstrip("/")
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass
        session.delete(m)
        session.commit()
    return RedirectResponse("/admin/library", status_code=303)


@router.get("/api/library/books")
async def api_library_books(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    rows = list(session.exec(
        select(LibraryBook).where(LibraryBook.is_active == True).order_by(LibraryBook.title)
    ).all())
    return [
        {
            "id": b.id,
            "title": b.title,
            "author": b.author or "",
            "description": b.description or "",
            "has_text": bool(b.text_content),
            "pages": max(1, len((b.text_content or "").split("\n\n")) if b.text_content else 1),
        }
        for b in rows
    ]


@router.get("/api/library/books/{bid}")
async def api_library_book(
    bid: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    b = session.get(LibraryBook, bid)
    if not b or not b.is_active:
        raise HTTPException(404, "Book not found")
    # Split into paragraph "pages" for reader
    raw = (b.text_content or "").strip()
    paras = [p.strip() for p in raw.replace("\r", "").split("\n\n") if p.strip()]
    if not paras and raw:
        # fallback: split by single newlines or chunks
        paras = [p.strip() for p in raw.split("\n") if p.strip()]
    if not paras:
        paras = ["No extractable text for this book. Ask General Admin to re-upload a text-based PDF."]
    return {
        "id": b.id,
        "title": b.title,
        "author": b.author or "",
        "pages": [{"n": i + 1, "text": p} for i, p in enumerate(paras[:500])],
        "page_count": min(len(paras), 500),
    }


@router.get("/api/library/music")
async def api_reading_music(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    rows = list(session.exec(
        select(ReadingMusic).where(ReadingMusic.is_active == True).order_by(ReadingMusic.title)
    ).all())
    return [{"id": m.id, "title": m.title, "src": m.file_path} for m in rows]
