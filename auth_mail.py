"""
Churchgate-style email auth for CONTRAconnect / Project-Financial-Analysis-Workflow-ERP
=====================================================================================
Mirrors KnowsoftCloudAir/OneChurchgate patterns:

  • SMTP mailer (MAIL_HOST, MAIL_USER, MAIL_PASSWORD, MAIL_FROM, PUBLIC_BASE_URL)
  • Branded HTML emails (teal / Knowsoft)
  • Password reset: 6-digit code + link (expires 5 minutes)
  • Registration: confirmation email with link (expires 48 hours)
  • Optional login OTP when REQUIRE_EMAIL_OTP=1

Integration (in server.py, after models / before routes):

    from auth_mail import (
        send_mail, branded, public_base, app_base_from_request,
        issue_challenge, check_challenge, EmailChallenge,
        send_password_reset_email, send_registration_confirm_email,
        send_password_reset_success_email, OTP_MINUTES, CONFIRM_HOURS,
    )

Then replace forgot_password / reset_password handlers and call
send_registration_confirm_email after successful register().

Also add to ensure_db / create_all the EmailChallenge model via:
    from auth_mail import register_email_challenge_model
    EmailChallenge = register_email_challenge_model(db)
"""

from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional, Tuple
from urllib.parse import quote


# ---------------------------------------------------------------------------
# Config (same env names as OneChurchgate)
# ---------------------------------------------------------------------------
OTP_MINUTES = int(os.getenv("OTP_MINUTES", "5"))
CONFIRM_HOURS = int(os.getenv("CONFIRM_HOURS", "48"))
APP_NAME = os.getenv("MAIL_FROM_NAME") or os.getenv("APP_NAME") or "CONTRAconnect"
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL") or "info@knowsoft.org.uk"


def public_base() -> str:
    """Public URL of this app (Render / custom domain)."""
    raw = (os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_BASE_URL") or "").rstrip("/")
    if raw:
        return raw
    # Fallback — set PUBLIC_BASE_URL in production
    return "http://127.0.0.1:5000"


def app_base_from_request(request) -> str:
    """Prefer the live request host (so reset links hit the real deploy)."""
    try:
        proto = (request.headers.get("x-forwarded-proto") or request.scheme or "https").split(",")[0].strip()
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        ).split(",")[0].strip()
        if host and not host.startswith("localhost") and not host.startswith("127."):
            return f"{proto}://{host}".rstrip("/")
    except Exception:
        pass
    return public_base()


def from_addr() -> Tuple[str, str]:
    name = os.getenv("MAIL_FROM_NAME") or APP_NAME
    addr = os.getenv("MAIL_FROM") or os.getenv("MAIL_USER") or CONTACT_EMAIL
    return name, addr


def send_mail(to_email: str, subject: str, text_body: str, html_body: Optional[str] = None) -> bool:
    """Send email via SMTP. Logs only when MAIL_DISABLED=1 or SMTP not configured."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False
    name, addr = from_addr()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{name} <{addr}>"
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    if os.getenv("MAIL_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        print(f"[mail:disabled] to={to_email} subject={subject}")
        print(f"[mail:disabled] body=\n{text_body[:500]}")
        return True

    host = os.getenv("MAIL_HOST") or os.getenv("SMTP_HOST")
    user = os.getenv("MAIL_USER") or os.getenv("SMTP_USER")
    password = (
        os.getenv("MAIL_PASSWORD")
        or os.getenv("SMTP_PASSWORD")
        or os.getenv("MAIL_PASS")
    )
    port = int(os.getenv("MAIL_PORT") or os.getenv("SMTP_PORT") or "587")
    if not host or not user or not password:
        print("⚠️ Mail not configured: set MAIL_HOST, MAIL_USER, MAIL_PASSWORD (or MAIL_DISABLED=1)")
        print(f"[mail:unconfigured] to={to_email} subject={subject}")
        print(f"[mail:unconfigured] body=\n{text_body[:500]}")
        return False
    try:
        with smtplib.SMTP(host, port, timeout=25) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except Exception:
                pass
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"✅ Mail sent {to_email} @ {datetime.utcnow().isoformat()}Z subject={subject}")
        return True
    except Exception as e:
        print(f"❌ Mail fail {to_email}: {e}")
        return False


def branded(title: str, body_html: str) -> str:
    """HTML email shell — same teal / dark style as Churchgate."""
    base = public_base()
    return f"""<!doctype html><html><body style="font-family:Georgia,serif;background:#0f172a;color:#e2e8f0;padding:24px">
  <div style="max-width:560px;margin:auto;background:#111827;border:1px solid #334155;border-radius:16px;padding:24px">
    <div style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8">{APP_NAME} · Knowsoft</div>
    <h1 style="font-size:22px;color:#f8fafc;margin:12px 0 16px">{title}</h1>
    <div style="line-height:1.6;color:#cbd5e1">{body_html}</div>
    <p style="margin-top:28px;font-size:12px;color:#64748b">{base}<br>
      Contact: <a href="mailto:{CONTACT_EMAIL}" style="color:#94a3b8">{CONTACT_EMAIL}</a></p>
  </div></body></html>"""


# ---------------------------------------------------------------------------
# Challenge codes (6-digit OTP or urlsafe token) — hashed at rest
# ---------------------------------------------------------------------------
def _hash(code: str) -> str:
    return hashlib.sha256((code or "").strip().upper().encode()).hexdigest()


def _otp6() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def register_email_challenge_model(db):
    """Bind EmailChallenge to the app's SQLAlchemy db instance."""

    class EmailChallenge(db.Model):
        __tablename__ = "email_challenges"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(120), nullable=False, index=True)
        purpose = db.Column(db.String(40), nullable=False, index=True)
        # purposes: reset | verify | login_otp | register_confirm
        code_hash = db.Column(db.String(64), nullable=False)
        pending_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        expires_at = db.Column(db.DateTime, nullable=False)
        used = db.Column(db.Boolean, default=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

    return EmailChallenge


def issue_challenge(db, EmailChallenge, email: str, purpose: str, user_id=None, code: str = None, hours=None, minutes=None):
    """Create a one-time challenge. Returns the plaintext code/token to email."""
    email = (email or "").strip().lower()
    if purpose == "register_confirm":
        code = code or secrets.token_urlsafe(24)
        expires = datetime.utcnow() + timedelta(hours=hours or CONFIRM_HOURS)
    else:
        code = code or _otp6()
        expires = datetime.utcnow() + timedelta(minutes=minutes or OTP_MINUTES)
    row = EmailChallenge(
        email=email,
        purpose=purpose,
        code_hash=_hash(code),
        pending_user_id=user_id,
        expires_at=expires,
        used=False,
    )
    db.session.add(row)
    db.session.commit()
    return code


def check_challenge(db, EmailChallenge, email: str, purpose: str, code: str):
    """Validate code; marks used on success. Returns row or None."""
    email = (email or "").strip().lower()
    row = (
        EmailChallenge.query.filter_by(email=email, purpose=purpose, used=False)
        .order_by(EmailChallenge.id.desc())
        .first()
    )
    if not row:
        return None
    if row.expires_at < datetime.utcnow():
        return None
    if row.code_hash != _hash(code):
        return None
    row.used = True
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# High-level email helpers (Churchgate wording / flow)
# ---------------------------------------------------------------------------
def send_password_reset_email(email: str, code: str, request=None) -> bool:
    """Email 6-digit code + reset link (expires OTP_MINUTES)."""
    base = app_base_from_request(request) if request is not None else public_base()
    link = f"{base}/reset-password?email={quote(email)}&code={quote(code)}"
    text = (
        f"Your {APP_NAME} reset code is {code}. It expires in {OTP_MINUTES} minutes.\n"
        f"Open this link, enter your email, new password, confirm password, and the code:\n{link}\n\n"
        f"If you did not request a reset, ignore this email.\n"
        f"— {APP_NAME} · Knowsoft\nContact: {CONTACT_EMAIL}"
    )
    html = branded(
        "Reset password",
        "<p>You requested a password reset for <b>"
        + APP_NAME
        + "</b>.</p>"
        f"<p>Your code (expires in {OTP_MINUTES} minutes):</p>"
        f"<p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"
        f"<p><a href='{link}' style='background:#0d9488;color:#fff;padding:12px 18px;"
        "border-radius:10px;text-decoration:none;font-weight:700'>Open password reset form</a></p>"
        f"<p style='font-size:13px'>Or open: {link}</p>"
        "<p style='font-size:13px'>On that page enter your email, new password, "
        "repeat new password, and this code, then submit.</p>",
    )
    return send_mail(email, f"Reset your {APP_NAME} password", text, html)


def send_password_reset_success_email(email: str) -> bool:
    text = (
        f"Your {APP_NAME} password has been reset. "
        "This reset link has expired and cannot be used again.\n"
        f"— {APP_NAME} · Knowsoft"
    )
    html = branded(
        "Password reset",
        "<p>Your password has been reset.</p>"
        "<p>This reset link has expired and cannot be used again.</p>"
        f"<p style='font-size:13px'>If this was not you, contact {CONTACT_EMAIL} immediately.</p>",
    )
    return send_mail(email, f"Your {APP_NAME} password has been reset", text, html)


def send_registration_confirm_email(email: str, full_name: str, token: str, request=None) -> bool:
    """Confirmation link for new registration (expires CONFIRM_HOURS)."""
    base = app_base_from_request(request) if request is not None else public_base()
    link = f"{base}/confirm-registration?email={quote(email)}&token={quote(token)}"
    text = (
        f"Hello {full_name},\n\n"
        f"You are receiving this email because you sent a registration request with {APP_NAME}.\n\n"
        f"Click the link below to confirm your registration:\n{link}\n\n"
        f"This link expires in {CONFIRM_HOURS} hours.\n\n"
        f"If you did not register, you can ignore this email.\n\n"
        f"— {APP_NAME} · Knowsoft\nContact: {CONTACT_EMAIL}"
    )
    html = branded(
        "Confirm your registration",
        f"<p>Hello <b>{full_name}</b>,</p>"
        f"<p>You are receiving this email because you have sent a registration request with "
        f"<b>{APP_NAME}</b>.</p>"
        "<p>Click the button below to confirm your registration:</p>"
        f"<p style='margin:24px 0'><a href='{link}' style='background:#0d9488;color:#fff;"
        "padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:700'>"
        "Confirm my registration</a></p>"
        f"<p style='font-size:13px;color:#94a3b8'>Or copy this link:<br>{link}</p>"
        f"<p style='font-size:13px'>This link expires in {CONFIRM_HOURS} hours.</p>",
    )
    return send_mail(email, f"Confirm your {APP_NAME} registration", text, html)


def send_login_otp_email(email: str, code: str) -> bool:
    text = f"Your {APP_NAME} sign-in code is {code}. It expires in {OTP_MINUTES} minutes."
    html = branded(
        "Sign-in code",
        f"<p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"
        f"<p style='font-size:13px'>Expires in {OTP_MINUTES} minutes.</p>",
    )
    return send_mail(email, f"Your {APP_NAME} sign-in code", text, html)
