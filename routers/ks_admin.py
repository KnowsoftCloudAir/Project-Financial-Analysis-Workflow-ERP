"""Special General Admin login at /ks-admin/login."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserRole
from app.auth import (
    verify_password,
    create_user_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    record_login_failure,
    clear_login_failures,
    login_lockout_seconds,
    role_val,
)

router = APIRouter(tags=["ks-admin"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _page(request: Request, error=None, email=""):
    return templates.TemplateResponse(
        "auth/ks_admin_login.html",
        {"request": request, "error": error, "email": email},
    )


@router.get("/ks-admin/login", response_class=HTMLResponse)
async def ks_admin_login_page(request: Request):
    return _page(request)


@router.post("/ks-admin/login", response_class=HTMLResponse)
async def ks_admin_login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    email = (email or "").strip().lower()
    wait = login_lockout_seconds(email)
    if wait:
        return _page(request, error=f"Too many attempts. Try again in {wait} seconds.", email=email)

    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        record_login_failure(email)
        return _page(request, error="Invalid admin email or password.", email=email)

    rv = role_val(user.role)
    if rv != "general_admin" and "general_admin" not in str(getattr(user.role, "value", user.role)):
        record_login_failure(email)
        return _page(request, error="This portal is for General Admin only.", email=email)

    if not getattr(user, "is_active", True):
        return _page(request, error="Admin account is inactive.", email=email)

    clear_login_failures(email)
    token = create_user_token(user)
    dest = "/admin"
    if getattr(user, "must_change_password", False):
        dest = "/auth/change-password"
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
    )
    return resp


@router.get("/ks-admin", response_class=HTMLResponse)
async def ks_admin_root():
    return RedirectResponse("/ks-admin/login", status_code=303)
