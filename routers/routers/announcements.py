"""System-wide announcements (maintenance / upgrade) by General Admin."""
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserRole, SystemAnnouncement, AppConfig
from app.auth import require_roles, require_user, get_password_hash

router = APIRouter(tags=["announcements"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def get_config(session: Session, key: str, default: str = "") -> str:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    return row.value if row and row.value is not None else default


def set_config(session: Session, key: str, value: str):
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    if not row:
        row = AppConfig(key=key, value=value)
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()


def active_login_announcements(session: Session):
    now = datetime.utcnow()
    rows = list(session.exec(
        select(SystemAnnouncement).where(SystemAnnouncement.is_active == True, SystemAnnouncement.show_on_login == True)
        .order_by(SystemAnnouncement.created_at.desc())
    ).all())
    out = []
    for r in rows:
        if r.expires_at and r.expires_at <= now:
            continue
        out.append(r)
    return out


@router.get("/admin/announcements", response_class=HTMLResponse)
async def admin_announcements_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    items = list(session.exec(select(SystemAnnouncement).order_by(SystemAnnouncement.created_at.desc())).all())
    force = get_config(session, "force_password_reset", "0") == "1"
    return templates.TemplateResponse("admin/announcements.html", {
        "request": request, "user": user, "items": items, "force_password": force,
    })


@router.post("/admin/announcements")
async def admin_announcement_create(
    title: str = Form(...),
    body: str = Form(...),
    show_on_login: Optional[str] = Form(None),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    session.add(SystemAnnouncement(
        title=title.strip(),
        body=body.strip(),
        is_active=True,
        show_on_login=show_on_login == "yes",
        created_by=user.id,
    ))
    session.commit()
    return RedirectResponse("/admin/announcements", status_code=303)


@router.post("/admin/announcements/{aid}/deactivate")
async def admin_announcement_off(
    aid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    a = session.get(SystemAnnouncement, aid)
    if a:
        a.is_active = False
        session.add(a)
        session.commit()
    return RedirectResponse("/admin/announcements", status_code=303)


@router.post("/admin/force-password-reset")
async def admin_force_password_reset(
    enable: str = Form("1"),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    """After software upgrade: require all users to set a new strong password on next login."""
    on = enable == "1"
    set_config(session, "force_password_reset", "1" if on else "0")
    if on:
        for u in session.exec(select(User)).all():
            u.must_change_password = True
            session.add(u)
        session.commit()
    else:
        for u in session.exec(select(User)).all():
            u.must_change_password = False
            session.add(u)
        session.commit()
    return RedirectResponse("/admin/announcements", status_code=303)
