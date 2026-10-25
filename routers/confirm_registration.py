"""Robust registration confirmation + 1-day trial + auto-login."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import hashlib, os, secrets
from urllib.parse import quote, unquote
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.database import get_session
from app.models import User, EmailChallenge, ChurchMember, ChurchUnit
from app.auth import create_user_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.mailer import send_mail, branded, public_base

router = APIRouter(prefix="/auth", tags=["confirm"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
CONFIRM_HOURS = 72
TRIAL_HOURS = 24

def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()

def _page(request, **ctx):
    ctx["request"] = request
    try:
        return templates.TemplateResponse("auth/confirm_registration.html", ctx)
    except Exception:
        ok, msg = ctx.get("ok"), ctx.get("message") or ""
        return HTMLResponse(f"<!DOCTYPE html><html><body style='font-family:system-ui;padding:2rem;text-align:center'><h1>{'OK' if ok else 'Issue'}</h1><p>{msg}</p><p><a href='/auth/login'>Sign in</a></p></body></html>")

def _grant_one_day_trial(session: Session, user: User, member: ChurchMember | None):
    now = datetime.utcnow()
    user.welcome_started_at = now
    user.is_active = True
    session.add(user)
    if member:
        session.add(member)
    try:
        from app.models import MemberSubscription
        sub = session.exec(select(MemberSubscription).where(MemberSubscription.user_id == user.id)).first()
        ends = now + timedelta(hours=TRIAL_HOURS)
        if sub:
            sub.status = "active"
            if hasattr(sub, "ends_at"):
                sub.ends_at = ends
            session.add(sub)
        else:
            kwargs = {"user_id": user.id, "status": "active"}
            # best-effort fields
            for k, v in [("starts_at", now), ("ends_at", ends), ("plan", "welcome_trial")]:
                kwargs[k] = v
            try:
                session.add(MemberSubscription(**kwargs))
            except Exception:
                session.add(MemberSubscription(user_id=user.id, status="active"))
    except Exception as e:
        print("welcome trial:", e)
    session.commit()

def send_registration_confirm_email(session: Session, email: str, full_name: str, user_id: int | None = None) -> bool:
    token = secrets.token_urlsafe(32)
    session.add(EmailChallenge(
        email=(email or "").strip().lower(),
        purpose="register_confirm",
        code_hash=_hash_token(token),
        pending_user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(hours=CONFIRM_HOURS),
        used=False,
    ))
    session.commit()
    link = f"{public_base()}/auth/confirm-registration?email={quote(email.strip(), safe='')}&token={quote(token, safe='')}"
    text = f"Hello {full_name},\n\nConfirm your Knowsoft Churchgate registration:\n{link}\n\nAfter confirm, non-church affiliates get 1 day full access, then subscription is required.\n"
    html = branded("Confirm registration", f"<p>Hello <b>{full_name}</b>,</p><p><a href='{link}' style='background:#0d9488;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:700'>Confirm my registration</a></p><p style='font-size:12px;word-break:break-all'>{link}</p>")
    return send_mail(email.strip(), "Confirm your Knowsoft Churchgate registration", text, html)

@router.get("/confirm-registration", response_class=HTMLResponse)
async def confirm_registration(request: Request, email: str = "", token: str = "", session: Session = Depends(get_session)):
    email = unquote((email or "").strip()).lower()
    token = unquote((token or "").strip()).replace(" ", "").replace("\n", "").replace("\r", "")
    def fail(msg):
        return _page(request, ok=False, message=msg, login=True)
    if not email or not token:
        return fail("This confirmation link is incomplete. Use the full link from your email.")
    try:
        rows = list(session.exec(select(EmailChallenge).where(EmailChallenge.email == email, EmailChallenge.purpose == "register_confirm").order_by(EmailChallenge.id.desc())).all())
        th = _hash_token(token)
        th_old = hashlib.sha256(token.strip().upper().encode()).hexdigest()
        row = next((r for r in rows if r.code_hash in (th, th_old)), None)
        if not row:
            return fail("This confirmation link is invalid or already used. Try signing in, or register again after the latest update.")
        if row.expires_at < datetime.utcnow():
            return fail("This confirmation link has expired. Please register again.")
        if not row.used:
            row.used = True
            session.add(row)
        user = session.exec(select(User).where(User.email == email)).first()
        member = session.get(ChurchMember, user.member_id) if user and user.member_id else None
        if not member:
            member = session.exec(select(ChurchMember).where(ChurchMember.email == email)).first()
        auto_approved = False
        if member:
            g = session.get(ChurchUnit, member.global_church_id) if member.global_church_id else None
            gname = (g.name or "").lower() if g else ""
            conf = (member.confession or "").lower().replace("-", "_")
            if conf == "non_affiliate" or "knowsoft" in gname:
                member.approval_status = "approved"
                auto_approved = True
            session.add(member)
        if user:
            user.is_active = True
            session.add(user)
        session.commit()
        if user and (auto_approved or (member and (member.approval_status or "") == "approved")):
            _grant_one_day_trial(session, user, member)
            jwt = create_user_token(user)
            resp = RedirectResponse("/member/portal?welcome=1", status_code=303)
            resp.set_cookie("access_token", jwt, httponly=True, samesite="lax", max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, secure=os.getenv("COOKIE_SECURE", "1") not in ("0", "false"))
            return resp
        return _page(request, ok=True, message="Confirmed, but awaiting church admin approval. You can sign in with limited access until approved.", trial_note="After approval you get 1 day full access before subscription is required.", login=True, auto_approved=False)
    except Exception as e:
        print("confirm error:", e)
        return fail("We could not process this link right now. Email info@knowsoft.org.uk for help.")
