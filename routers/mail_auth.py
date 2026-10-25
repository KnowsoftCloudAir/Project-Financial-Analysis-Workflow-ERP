"""Email verification, 3-step login, password reset, admin mail-to-user."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, EmailChallenge, AuthBackupCode, AdminMailLog
from app.auth import (
    require_user,
    verify_password,
    get_password_hash,
    create_user_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    validate_password_strength,
    role_val,
)
from app.mailer import send_mail, branded, public_base

router = APIRouter(prefix="/auth", tags=["mail-auth"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

OTP_MINUTES = 5


def _hash(code: str) -> str:
    return hashlib.sha256((code or "").strip().upper().encode()).hexdigest()


def _otp6() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _issue(session: Session, email: str, purpose: str, user_id: int | None = None) -> str:
    code = _otp6()
    row = EmailChallenge(
        email=(email or "").strip().lower(),
        purpose=purpose,
        code_hash=_hash(code),
        pending_user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_MINUTES),
        used=False,
    )
    session.add(row)
    session.commit()
    return code


def _check(session: Session, email: str, purpose: str, code: str) -> EmailChallenge | None:
    email = (email or "").strip().lower()
    row = session.exec(
        select(EmailChallenge)
        .where(
            EmailChallenge.email == email,
            EmailChallenge.purpose == purpose,
            EmailChallenge.used == False,  # noqa: E712
        )
        .order_by(EmailChallenge.id.desc())
    ).first()
    if not row:
        return None
    if row.expires_at < datetime.utcnow():
        return None
    if row.code_hash != _hash(code):
        return None
    row.used = True
    session.add(row)
    session.commit()
    return row


def _set_session_cookie(response, user: User):
    token = create_user_token(user)
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=os.getenv("COOKIE_SECURE", "1") not in ("0", "false"),
    )


def _page(request, name, **ctx):
    ctx["request"] = request
    return templates.TemplateResponse(name, ctx)


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(request: Request, email: str = ""):
    return _page(request, "auth/verify_email.html", email=email, error=None)


@router.post("/verify-email")
async def verify_email_post(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    row = _check(session, email, "verify", code)
    if not row:
        return _page(request, "auth/verify_email.html", email=email, error="Invalid or expired code.")
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        try:
            user.email_verified = True  # type: ignore[attr-defined]
        except Exception:
            pass
        session.add(user)
        session.commit()
    return RedirectResponse("/auth/login?verified=1", status_code=303)


@router.post("/send-verify")
async def send_verify(email: str = Form(...), session: Session = Depends(get_session)):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        code = _issue(session, email, "verify", user.id)
        send_mail(
            email,
            "Confirm your Churchgate email",
            f"Your confirmation code is {code}. It expires in {OTP_MINUTES} minutes.",
            branded("Confirm your email", f"<p>Your code is</p><p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"),
        )
    return RedirectResponse(f"/auth/verify-email?email={email}", status_code=303)


@router.get("/step2", response_class=HTMLResponse)
async def step2_page(request: Request, email: str = "", session: Session = Depends(get_session)):
    """Login OTP step — DISABLED by default. Password login is enough after registration."""
    # Set REQUIRE_LOGIN_OTP=1 in env only if you want email codes on every login
    if os.getenv("REQUIRE_LOGIN_OTP", "0").strip() not in ("1", "true", "yes"):
        email = (email or request.query_params.get("email") or "").strip().lower()
        user = session.exec(select(User).where(User.email == email)).first() if email else None
        if user:
            resp = RedirectResponse("/member/portal", status_code=303)
            _set_session_cookie(resp, user)
            return resp
        return RedirectResponse("/auth/login", status_code=303)
    return _page(request, "auth/step2_otp.html", email=email, error=None)



@router.post("/step2")
async def step2_post(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    row = _check(session, email, "login_otp", code)
    if not row:
        return _page(request, "auth/step2_otp.html", email=email, error="Invalid or expired code.")
    return RedirectResponse(f"/auth/step3?email={email}", status_code=303)


@router.get("/step3", response_class=HTMLResponse)
async def step3_page(request: Request, email: str = "", session: Session = Depends(get_session)):
    if os.getenv("REQUIRE_LOGIN_OTP", "0").strip() not in ("1", "true", "yes"):
        email = (email or "").strip().lower()
        user = session.exec(select(User).where(User.email == email)).first() if email else None
        if user:
            resp = RedirectResponse("/member/portal", status_code=303)
            _set_session_cookie(resp, user)
            return resp
        return RedirectResponse("/auth/login", status_code=303)
    return _page(request, "auth/step3_backup.html", email=email, error=None)


@router.post("/step3")
async def step3_post(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        return _page(request, "auth/step3_backup.html", email=email, error="Account not found.")
    codes = session.exec(select(AuthBackupCode).where(AuthBackupCode.user_id == user.id, AuthBackupCode.used == False)).all()  # noqa
    ok = None
    for c in codes:
        if c.code_hash == _hash(code):
            ok = c
            break
    # Allow email OTP reused as third factor if no backup codes yet (first logins)
    if not ok:
        row = _check(session, email, "login_factor3", code)
        if row:
            ok = True
    if not ok:
        return _page(request, "auth/step3_backup.html", email=email, error="Invalid backup code.")
    if ok is not True:
        ok.used = True
        session.add(ok)
        session.commit()
    resp = RedirectResponse("/", status_code=303)
    _set_session_cookie(resp, user)
    return resp


@router.get("/forgot", response_class=HTMLResponse)
async def forgot_page(request: Request):
    return _page(request, "auth/forgot.html", error=None, sent=False)


@router.post("/forgot")
async def forgot_post(request: Request, email: str = Form(...), session: Session = Depends(get_session)):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        code = _issue(session, email, "reset", user.id)
        link = f"{public_base()}/auth/reset?email={email}"
        send_mail(
            email,
            "Reset your Churchgate password",
            f"Reset code: {code}\nOpen: {link}",
            branded("Reset password", f"<p>You requested a password reset for Knowsoft Churchgate.</p> <p>Your code (expires in 5 minutes): <b>{code}</b></p> <p><a href='{link}' style='background:#0d9488;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:700'>Open password reset form</a></p> <p style='font-size:13px'>Or open: {link}</p> <p style='font-size:13px'>Contact: info@knowsoft.org.uk</p>"),
        )
    return _page(request, "auth/forgot.html", error=None, sent=True, email=email)


@router.get("/reset", response_class=HTMLResponse)
async def reset_page(request: Request, email: str = ""):
    return _page(request, "auth/reset.html", email=email, error=None)


@router.post("/reset")
async def reset_post(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    err = validate_password_strength(password) if callable(validate_password_strength) else None
    if err:
        return _page(request, "auth/reset.html", email=email, error=str(err))
    row = _check(session, email, "reset", code)
    if not row:
        return _page(request, "auth/reset.html", email=email, error="Invalid or expired code.")
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        return _page(request, "auth/reset.html", email=email, error="Account not found.")
    user.hashed_password = get_password_hash(password)
    session.add(user)
    session.commit()
    return RedirectResponse("/auth/login?reset=1", status_code=303)


@router.get("/admin-mail", response_class=HTMLResponse)
async def admin_mail_page(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    rv = role_val(user.role)
    if rv not in ("general_admin",) and "admin" not in str(rv):
        return RedirectResponse("/restricted", status_code=303)
    members = session.exec(select(User).order_by(User.full_name).limit(400)).all()
    return _page(request, "admin/mail_users.html", user=user, members=members, sent=None)


@router.post("/admin-mail")
async def admin_mail_post(
    request: Request,
    to_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    rv = role_val(user.role)
    if rv not in ("general_admin",) and "admin" not in str(rv):
        return RedirectResponse("/restricted", status_code=303)
    ok = send_mail(to_email.strip(), subject.strip(), body.strip(), branded(subject.strip(), f"<p>{body.strip().replace(chr(10),'<br>')}</p>"))
    session.add(AdminMailLog(admin_id=user.id, to_email=to_email.strip(), subject=subject.strip(), ok=ok))
    session.commit()
    members = session.exec(select(User).order_by(User.full_name).limit(400)).all()
    return _page(request, "admin/mail_users.html", user=user, members=members, sent=ok)


# ---- Registration email confirmation link ----
CONFIRM_HOURS = 48



@router.get("/confirm-registration", response_class=HTMLResponse)
async def confirm_registration(
    request: Request,
    email: str = "",
    token: str = "",
    session: Session = Depends(get_session),
):
    """User clicks link in registration email → friendly page (never raw 400)."""
    from app.models import ChurchMember, ChurchUnit
    from urllib.parse import unquote

    def show(ok: bool, message: str, login: bool = False, auto_approved: bool = False):
        try:
            return _page(
                request,
                "auth/confirm_registration.html",
                ok=ok,
                message=message,
                login=login,
                auto_approved=auto_approved,
            )
        except Exception:
            # Absolute fallback if template missing
            color = "#0d9488" if ok else "#b45309"
            title = "Registration confirmed" if ok else "Confirmation link"
            body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>{title}</title></head><body style="font-family:system-ui;background:#f8fafc;padding:2rem;text-align:center">
            <div style="max-width:28rem;margin:auto;background:#fff;border-radius:1rem;padding:2rem;border:1px solid #e2e8f0">
            <h1 style="color:{color}">{title}</h1>
            <p style="color:#334155;line-height:1.5">{message}</p>
            {"<p><a href='/auth/login' style='display:inline-block;margin-top:1rem;background:#0d9488;color:#fff;padding:0.75rem 1.25rem;border-radius:0.75rem;text-decoration:none;font-weight:700'>Sign in</a></p>" if login else ""}
            <p style="margin-top:1.5rem;font-size:0.875rem"><a href="mailto:info@knowsoft.org.uk">info@knowsoft.org.uk</a></p>
            </div></body></html>"""
            return HTMLResponse(body)

    try:
        email = unquote((email or "").strip()).lower()
        token = unquote((token or "").strip())
        if not email or not token:
            return show(False, "This confirmation link is incomplete. Please use the full link from your email, or register again.")

        row = session.exec(
            select(EmailChallenge)
            .where(
                EmailChallenge.email == email,
                EmailChallenge.purpose == "register_confirm",
                EmailChallenge.used == False,  # noqa: E712
            )
            .order_by(EmailChallenge.id.desc())
        ).first()

        # Also accept already-used token once (friendly message, not error)
        if not row:
            used = session.exec(
                select(EmailChallenge)
                .where(
                    EmailChallenge.email == email,
                    EmailChallenge.purpose == "register_confirm",
                    EmailChallenge.used == True,  # noqa: E712
                )
                .order_by(EmailChallenge.id.desc())
            ).first()
            if used and used.code_hash == _hash(token):
                user = session.exec(select(User).where(User.email == email)).first()
                member = None
                if user and user.member_id:
                    member = session.get(ChurchMember, user.member_id)
                if not member:
                    member = session.exec(select(ChurchMember).where(ChurchMember.email == email)).first()
                auto = bool(member and (member.approval_status or "") == "approved")
                if auto:
                    return show(True, "Your registration is already confirmed and approved. You can sign in with your password.", True, True)
                return show(True, "Your email is already confirmed. You are awaiting church admin approval before full access.", True, False)

        if not row or row.expires_at < datetime.utcnow() or row.code_hash != _hash(token):
            return show(False, "This confirmation link is invalid or has expired. Please register again or contact Knowsoft at info@knowsoft.org.uk.")

        row.used = True
        session.add(row)

        user = session.exec(select(User).where(User.email == email)).first()
        member = None
        if user and user.member_id:
            member = session.get(ChurchMember, user.member_id)
        if not member:
            member = session.exec(select(ChurchMember).where(ChurchMember.email == email)).first()

        auto_approved = False
        if member:
            g = session.get(ChurchUnit, member.global_church_id) if member.global_church_id else None
            gname = (g.name or "").lower() if g else ""
            conf = (member.confession or "").lower()
            if conf in ("non_affiliate", "non-affiliate") or "knowsoft" in gname:
                member.approval_status = "approved"
                auto_approved = True
            session.add(member)

        if user:
            user.is_active = True
            session.add(user)
        session.commit()

        if auto_approved:
            return show(
                True,
                "Your email is confirmed and your registration is approved. You can sign in with the password you created.",
                True,
                True,
            )
        return show(
            True,
            "Confirmed, but awaiting church admin approval. You may sign in with limited access until your church admin approves full membership.",
            True,
            False,
        )
    except Exception as e:
        print("confirm-registration error:", e)
        return show(False, "We could not process this link right now. Please try again or contact info@knowsoft.org.uk.")




def send_registration_confirm_email(session: Session, email: str, full_name: str, user_id: int | None = None) -> bool:
    """Issue token and email confirmation link for new registration."""
    token = secrets.token_urlsafe(24)
    row = EmailChallenge(
        email=(email or "").strip().lower(),
        purpose="register_confirm",
        code_hash=_hash(token),
        pending_user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(hours=CONFIRM_HOURS),
        used=False,
    )
    session.add(row)
    session.commit()
    from urllib.parse import quote as _q
    link = f"{public_base()}/auth/confirm-registration?email={_q(email.strip())}&token={_q(token)}"
    text = (
        f"Hello {full_name},\n\n"
        "You are receiving this email because you have sent a registration request with Knowsoft Churchgate.\n\n"
        "Click the link below to confirm your registration:\n"
        f"{link}\n\n"
        "This link expires in 48 hours.\n\n"
        "If you did not register, you can ignore this email.\n\n"
        "— Knowsoft Churchgate\n"
        f"Contact: info@knowsoft.org.uk"
    )
    html = branded(
        "Confirm your registration",
        f"<p>Hello <b>{full_name}</b>,</p>"
        "<p>You are receiving this email because you have sent a registration request with "
        "<b>Knowsoft Churchgate</b>.</p>"
        "<p>Click the button below to confirm your registration:</p>"
        f"<p style='margin:24px 0'><a href='{link}' style='background:#0d9488;color:#fff;"
        "padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:700'>"
        "Confirm my registration</a></p>"
        f"<p style='font-size:13px;color:#94a3b8'>Or copy this link:<br>{link}</p>"
        "<p style='font-size:13px'>This link expires in 48 hours.</p>"
        "<p style='font-size:13px'>Contact: <a href='mailto:info@knowsoft.org.uk'>info@knowsoft.org.uk</a></p>",
    )
    return send_mail(
        email.strip(),
        "Confirm your Knowsoft Churchgate registration",
        text,
        html,
    )


