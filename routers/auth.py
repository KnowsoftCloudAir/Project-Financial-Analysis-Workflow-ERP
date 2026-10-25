from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime
import secrets
import string

from app.database import get_session
from app.models import User, UserRole, ChurchUnit, ChurchLevel, ApprovalStatus, ChurchMember, TrialAccess, MemberSubscription
from app.auth import require_user, role_val, verify_password, get_password_hash, create_access_token, create_user_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES, validate_password_strength, record_login_failure, clear_login_failures, login_lockout_seconds
from app.activity import log_activity

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

def generate_code(prefix: str = "CG") -> str:
    suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{prefix}-{suffix}"

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: Optional[User] = Depends(get_current_user), session: Session = Depends(get_session)):
    if user and not getattr(user, "must_change_password", False):
        return RedirectResponse("/", status_code=303)
    from app.routers.announcements import active_login_announcements
    from app.models import MusicLink, YoutubeChannelLink
    announcements = active_login_announcements(session)
    # Same YouTube source as public home page (approved channel/video links), then MusicLink fallback
    slides = []
    try:
        for L in session.exec(
            select(YoutubeChannelLink).where(
                YoutubeChannelLink.is_approved == True,
                YoutubeChannelLink.is_active == True,
            ).order_by(YoutubeChannelLink.created_at.desc()).limit(8)
        ).all():
            vid = getattr(L, "youtube_video_id", None)
            if not vid:
                continue
            slides.append(type("S", (), {"youtube_id": vid, "title": L.title or "YouTube"})())
    except Exception as e:
        print(f"login yt clips: {e}")
    if not slides:
        for L in session.exec(
            select(MusicLink).where(MusicLink.is_active == True).order_by(MusicLink.sort_order).limit(8)
        ).all():
            slides.append(L)
    show_invite = True
    try:
        from app.models import AppConfig
        cfg = session.exec(select(AppConfig).where(AppConfig.key == "login_invite_note")).first()
        if cfg and (cfg.value or "").strip().lower() in ("0", "false", "off", "hide"):
            show_invite = False
    except Exception:
        pass
    return templates.TemplateResponse("auth/login.html", {
        "request": request, "announcements": announcements, "slides": slides,
        "force_form": bool(user and getattr(user, "must_change_password", False)),
        "show_invite_note": show_invite,
    })

@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session)
):
    email = (email or "").strip().lower()
    lock = login_lockout_seconds(email)
    if lock > 0:
        mins = max(1, lock // 60)
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": f"Too many failed attempts. Try again in about {mins} minute(s)."
        }, status_code=429)
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        # case-insensitive fallback
        for u in session.exec(select(User)).all():
            if (u.email or "").strip().lower() == email:
                user = u
                break

    # Always heal sample angel credentials
    if user and email == "angel@churchgate.com" and password == "ilovechurhgate":
        try:
            user.hashed_password = get_password_hash("ilovechurhgate")
            user.is_active = True
            user.is_sample_account = True
            user.role = UserRole.member
            session.add(user)
            session.commit()
            session.refresh(user)
        except Exception as _ah:
            print("angel heal:", _ah)
            try:
                session.rollback()
            except Exception:
                pass

    # Auto-heal sample account if missing password match on known demo credentials
    if user and getattr(user, "is_sample_account", False):
        if not verify_password(password, user.hashed_password):
            if password in ("ilovechurhgate", "Church@12345", "Member@12345"):
                user.hashed_password = get_password_hash(password)
                user.is_active = True
                session.add(user)
                session.commit()
                session.refresh(user)
    if not user or not verify_password(password, user.hashed_password):
        # Last chance: create/heal angel sample on the fly when credentials match
        if email == "angel@churchgate.com" and password == "ilovechurhgate":
            try:
                from app.seed_sample import seed_sample_member
                seed_sample_member(session)
                user = session.exec(select(User).where(User.email == email)).first()
            except Exception as _se:
                print("on-login sample seed:", _se)
        if not user or not verify_password(password, user.hashed_password):
            record_login_failure(email)
            return templates.TemplateResponse("auth/login.html", {
                "request": request, "error": "Invalid email or password"
            }, status_code=400)
    clear_login_failures(email)
    if not user.is_active:
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "error": "Account deactivated. Contact Knowsoft Churchgate support."
        }, status_code=400)

    # 3-way auth: after password, email OTP then backup code (when mail is configured)
    try:
        import os
        mail_on = bool(os.getenv("MAIL_HOST") or os.getenv("SMTP_HOST"))
        require_otp = os.getenv("REQUIRE_EMAIL_OTP", "1" if mail_on else "0").strip() not in ("0", "false", "off")
        if require_otp and mail_on and not getattr(user, "is_sample_account", False):
            from app.routers.mail_auth import _issue
            from app.mailer import send_mail, branded
            code = _issue(session, email, "login_otp", user.id)
            send_mail(
                email,
                "Your Churchgate sign-in code",
                f"Your sign-in code is {code}. It expires in 12 minutes.",
                branded("Sign-in code", f"<p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"),
            )
            # factor 3 code emailed too if user has no backup codes
            from app.models import AuthBackupCode
            from sqlmodel import select as _sel
            have = session.exec(_sel(AuthBackupCode).where(AuthBackupCode.user_id == user.id)).first()
            if not have:
                c3 = _issue(session, email, "login_factor3", user.id)
                send_mail(
                    email,
                    "Your Churchgate backup sign-in code",
                    f"Backup code (step 3): {c3}",
                    branded("Backup code", f"<p>Use this on the third sign-in screen: <b>{c3}</b></p>"),
                )
            return RedirectResponse(f"/auth/step2?email={email}", status_code=303)
    except Exception as _otp:
        print("otp gate:", _otp)

    # Church admins must belong to an approved church
    if role_val(user.role) == "church_admin" and user.church_id:
        church = session.get(ChurchUnit, user.church_id)
        status = (church.approval_status or "approved") if church else "approved"
        if church and status not in ("approved",):
            return templates.TemplateResponse("auth/login.html", {
                "request": request, "error": "Your church is still pending approval by Knowsoft Admin."
            }, status_code=400)
    # Members need approved membership for full login
    if role_val(user.role) == "member" and not getattr(user, "is_sample_account", False):
        m = session.get(ChurchMember, user.member_id) if user.member_id else None
        if not m:
            m = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
        if m and m.approval_status == "pending":
            # Limited access only — pending page after login
            try:
                user.session_version = int(getattr(user, "session_version", 0) or 0) + 1
            except Exception:
                pass
            user.last_login = datetime.utcnow()
            session.add(user)
            session.commit()
            session.refresh(user)
            token = create_user_token(user)
            log_activity(session, user=user, action="login", detail="Pending/limited login", request=request)
            resp = RedirectResponse("/member/portal", status_code=303)
            resp.set_cookie("access_token", token, httponly=True,
                            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax", path="/")
            return resp
        if m and m.approval_status in ("rejected", "discontinued"):
            return templates.TemplateResponse("auth/login.html", {
                "request": request, "error": "Membership not active."
            }, status_code=400)
        # waiting_approval / deactivated-from-expiry: allow login so they can renew
        if m and m.approval_status == "deactivated":
            m.approval_status = "waiting_approval"
            session.add(m)
            session.commit()

    is_sample = bool(getattr(user, "is_sample_account", False))
    # --- Safe session / token (never 500 existing members) ---
    try:
        if is_sample:
            from datetime import timedelta as _td
            try:
                user.last_login = datetime.utcnow()
                user.sample_started_at = datetime.utcnow()
                user.is_active = True
                session.add(user)
                if user.member_id:
                    mem = session.get(ChurchMember, user.member_id)
                    if mem:
                        mem.approval_status = "approved"
                        mem.is_active = True
                        session.add(mem)
                session.commit()
                session.refresh(user)
            except Exception as _sc:
                print("sample login save:", _sc)
                try:
                    session.rollback()
                except Exception:
                    pass
            try:
                token = create_user_token(user, expires_delta=_td(minutes=3))
            except Exception:
                token = create_access_token({"sub": user.email, "sv": 0}, expires_delta=_td(minutes=3))
            cookie_age = 3 * 60
        else:
            try:
                if hasattr(user, "session_version"):
                    user.session_version = int(getattr(user, "session_version", 0) or 0) + 1
                user.last_login = datetime.utcnow()
                session.add(user)
                session.commit()
                session.refresh(user)
            except Exception as _sv:
                print("login session save:", _sv)
                try:
                    session.rollback()
                except Exception:
                    pass
                # Retry without session_version bump
                try:
                    user.last_login = datetime.utcnow()
                    session.add(user)
                    session.commit()
                except Exception as _sv2:
                    print("login minimal save:", _sv2)
                    try:
                        session.rollback()
                    except Exception:
                        pass
            try:
                token = create_user_token(user)
            except Exception:
                token = create_access_token({"sub": user.email, "sv": int(getattr(user, "session_version", 0) or 0)})
            cookie_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        try:
            log_activity(session, user=user, action="login", detail="Successful login", request=request)
        except Exception as _la:
            print("login activity:", _la)
    except Exception as _login_core:
        print("login core:", _login_core)
        try:
            token = create_access_token({"sub": user.email, "sv": 0})
        except Exception:
            return templates.TemplateResponse("auth/login.html", {
                "request": request,
                "error": "Login could not complete. Please try again or reset your password.",
            }, status_code=500)
        cookie_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    rv = role_val(user.role)
    if rv == "general_admin":
        dest = "/admin/"
    elif rv == "member":
        dest = "/member/portal"
    else:
        dest = "/dashboard"
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(
        "access_token", token,
        httponly=True,
        max_age=cookie_age,
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/register-church", response_class=HTMLResponse)
async def register_church_page(request: Request):
    return templates.TemplateResponse("auth/register_church.html", {"request": request})

@router.post("/register-church")
async def register_church(
    request: Request,
    name: str = Form(...),
    level: str = Form(...),
    parent_global_id: str = Form(""),
    parent_country_id: str = Form(""),
    parent_state_id: str = Form(""),
    parent_group_id: str = Form(""),
    country_name: str = Form(""),
    state_name: str = Form(""),
    doctrine: str = Form(""),
    activity_days: str = Form(""),
    owner_name: str = Form(...),
    resident_pastor: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    admin_full_name: str = Form(...),
    admin_password: str = Form(...),
    session: Session = Depends(get_session)
):
    level_raw = (level or "").strip().lower()
    level_map = {"global": "global", "global_church": "global", "country": "country",
                 "state": "state", "group": "group", "district": "district"}
    level_raw = level_map.get(level_raw, level_raw)
    try:
        church_level = ChurchLevel(level_raw)
    except ValueError:
        return templates.TemplateResponse("auth/register_church.html", {
            "request": request, "error": f"Invalid church level: {level}"
        }, status_code=400)

    parent_id = None
    global_code = country_code = state_code = group_code = district_code = None

    def get_unit(raw_id):
        if not raw_id or not str(raw_id).strip().isdigit():
            return None
        return session.get(ChurchUnit, int(raw_id))

    if church_level == ChurchLevel.global_church:
        parent_id = None
    elif church_level == ChurchLevel.country:
        g = get_unit(parent_global_id)
        if not g or g.approval_status != "approved":
            return templates.TemplateResponse("auth/register_church.html", {
                "request": request, "error": "Select an approved Global parent church"
            }, status_code=400)
        parent_id = g.id
        global_code = g.global_code or g.code
    elif church_level == ChurchLevel.state:
        g, c = get_unit(parent_global_id), get_unit(parent_country_id)
        if not g or not c or c.parent_id != g.id:
            return templates.TemplateResponse("auth/register_church.html", {
                "request": request, "error": "Select valid Global and Country parents"
            }, status_code=400)
        parent_id = c.id
        global_code = g.global_code or g.code
        country_code = c.country_code or c.code
    elif church_level == ChurchLevel.group:
        g, c, s = get_unit(parent_global_id), get_unit(parent_country_id), get_unit(parent_state_id)
        if not all([g, c, s]) or s.parent_id != c.id:
            return templates.TemplateResponse("auth/register_church.html", {
                "request": request, "error": "Select valid Global, Country and State parents"
            }, status_code=400)
        parent_id = s.id
        global_code = g.global_code or g.code
        country_code = c.country_code or c.code
        state_code = s.state_code or s.code
    elif church_level == ChurchLevel.district:
        g = get_unit(parent_global_id)
        c = get_unit(parent_country_id)
        s = get_unit(parent_state_id)
        gr = get_unit(parent_group_id)
        if not all([g, c, s, gr]) or gr.parent_id != s.id:
            return templates.TemplateResponse("auth/register_church.html", {
                "request": request, "error": "Select valid Global, Country, State and Group parents"
            }, status_code=400)
        parent_id = gr.id
        global_code = g.global_code or g.code
        country_code = c.country_code or c.code
        state_code = s.state_code or s.code
        group_code = gr.group_code or gr.code

    code = generate_code("CG")
    while session.exec(select(ChurchUnit).where(ChurchUnit.code == code)).first():
        code = generate_code("CG")

    if church_level == ChurchLevel.global_church:
        global_code = code
    elif church_level == ChurchLevel.country:
        country_code = code
    elif church_level == ChurchLevel.state:
        state_code = code
    elif church_level == ChurchLevel.group:
        group_code = code
    elif church_level == ChurchLevel.district:
        district_code = code

    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user:
        return templates.TemplateResponse("auth/register_church.html", {
            "request": request, "error": "Email already registered"
        }, status_code=400)

    church = ChurchUnit(
        code=code,
        name=name.strip(),
        level=church_level,
        parent_id=parent_id,
        global_code=global_code,
        country_code=country_code,
        state_code=state_code,
        group_code=group_code,
        district_code=district_code,
        country_name=country_name.strip() or None,
        state_name=state_name.strip() or None,
        doctrine=doctrine.strip() or None,
        activity_days=activity_days.strip() or None,
        owner_name=owner_name.strip(),
        resident_pastor=resident_pastor.strip(),
        address=address.strip() or None,
        phone=phone.strip() or None,
        email=email.strip(),
        approval_status="pending",
    )
    session.add(church)
    session.commit()
    session.refresh(church)

    admin = User(
        email=email.strip(),
        hashed_password=get_password_hash(admin_password),
        full_name=admin_full_name.strip(),
        role=UserRole.church_admin,
        church_id=church.id,
        is_active=True,
        can_create_churches=False,
        can_approve_members=False,
    )
    session.add(admin)
    session.commit()

    return templates.TemplateResponse("auth/pending.html", {
        "request": request,
        "church_name": name,
        "code": code,
        "email": email
    })

@router.get("/logout")
async def logout():
    """Clear session cookie and send client through a storage-clear page."""
    resp = RedirectResponse("/auth/clear-session", status_code=303)
    resp.delete_cookie("access_token")
    resp.delete_cookie("session")
    resp.delete_cookie("csrftoken")
    return resp


@router.get("/clear-session", response_class=HTMLResponse)
async def clear_session_page(request: Request):
    """Wipe local storage, caches, and service workers so re-login is clean."""
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signing out…</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center;padding:1.5rem}</style>
</head><body>
<p>Clearing site data for a clean login…</p>
<script>
(async function () {
  try { localStorage.clear(); } catch (e) {}
  try { sessionStorage.clear(); } catch (e) {}
  try {
    if (window.indexedDB && indexedDB.databases) {
      const dbs = await indexedDB.databases();
      for (const db of dbs || []) {
        if (db && db.name) indexedDB.deleteDatabase(db.name);
      }
    } else {
      indexedDB.deleteDatabase('churchgate_offline_v1');
    }
  } catch (e) {}
  try {
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map(function (k) { return caches.delete(k); }));
    }
  } catch (e) {}
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(function (r) { return r.unregister(); }));
    }
  } catch (e) {}
  // Clear cookies accessible from JS
  try {
    document.cookie.split(';').forEach(function (c) {
      var n = c.split('=')[0].trim();
      if (!n) return;
      document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
      document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=' + location.hostname;
    });
  } catch (e) {}
  location.replace('/auth/login?cleared=1');
})();
</script>
</body></html>"""
    from fastapi.responses import HTMLResponse as _HR
    resp = _HR(html)
    resp.delete_cookie("access_token")
    resp.delete_cookie("session")
    return resp



import hashlib
from datetime import timedelta

def _client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or ""
    if xf:
        return xf.split(",")[0].strip()
    return (request.client.host if request.client else "0.0.0.0") or "0.0.0.0"


def _ip_hash(ip: str) -> str:
    return hashlib.sha256((ip or "unknown").encode("utf-8")).hexdigest()[:48]


@router.post("/try-churchgate")
async def try_churchgate(request: Request, session: Session = Depends(get_session)):
    """10-minute free explore account for Knowsoft church; one completed trial per IP."""
    from app.models import TrialAccess, User, UserRole, ChurchMember, ChurchUnit
    from app.auth import get_password_hash, create_access_token
    import secrets

    ip = _client_ip(request)
    ih = _ip_hash(ip)
    now = datetime.utcnow()

    # Block if this IP already completed a trial
    done = session.exec(
        select(TrialAccess).where(TrialAccess.ip_hash == ih, TrialAccess.completed == True)
    ).first()
    if done:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Try Churchgate was already used from this network (10 minutes). Please register for full access.", "success": None},
            status_code=400,
        )

    # Reuse active trial if still valid
    active = session.exec(
        select(TrialAccess).where(
            TrialAccess.ip_hash == ih,
            TrialAccess.completed == False,
            TrialAccess.expires_at > now,
        )
    ).first()
    if active and active.user_id:
        user = session.get(User, active.user_id)
        if user:
            token = create_access_token({"sub": user.email, "sv": 0, "trial": True})
            resp = RedirectResponse("/member/portal", status_code=303)
            resp.set_cookie("access_token", token, httponly=True, samesite="lax")
            return resp

    # Create trial user
    email = f"trial_{ih[:10]}_{secrets.token_hex(3)}@try.churchgate.local"
    pwd = secrets.token_urlsafe(12)
    user = User(
        email=email,
        hashed_password=get_password_hash(pwd),
        full_name="Try Churchgate Guest",
        role=getattr(UserRole, "member", None) or "member",
        is_active=True,
    )
    # role may be enum
    try:
        user.role = UserRole.member
    except Exception:
        pass
    session.add(user)
    session.commit()
    session.refresh(user)

    # Attach to Knowsoft church if present
    try:
        unit = session.exec(
            select(ChurchUnit).where(ChurchUnit.name.ilike("%knowsoft%"))
        ).first()
        if not unit:
            unit = session.exec(select(ChurchUnit).limit(1)).first()
        if unit:
            user.church_id = unit.id
            session.add(user)
            cm = ChurchMember(
                church_id=unit.id,
                full_name="Try Churchgate Guest",
                email=email,
                approval_status="approved",
                status="member",
                is_active=True,
            )
            session.add(cm)
            session.commit()
            session.refresh(cm)
            user.member_id = cm.id
            session.add(user)
            session.commit()
    except Exception as e:
        print("try attach church:", e)

    expires = now + timedelta(minutes=10)
    trial = TrialAccess(ip_hash=ih, user_id=user.id, started_at=now, expires_at=expires, completed=False)
    session.add(trial)
    session.commit()

    token = create_access_token({"sub": user.email, "sv": 0, "trial": True})
    resp = RedirectResponse("/member/portal?trial=1", status_code=303)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=600)
    resp.set_cookie("cg_trial_exp", expires.isoformat() + "Z", max_age=600)
    return resp


@router.get("/api/trial-status")
async def trial_status(request: Request, session: Session = Depends(get_session)):
    from app.models import TrialAccess
    ip = _client_ip(request)
    ih = _ip_hash(ip)
    now = datetime.utcnow()
    active = session.exec(
        select(TrialAccess).where(TrialAccess.ip_hash == ih, TrialAccess.completed == False)
    ).first()
    if not active:
        return JSONResponse({"ok": True, "trial": False})
    remaining = max(0, int((active.expires_at - now).total_seconds()))
    if remaining <= 0:
        active.completed = True
        session.add(active)
        session.commit()
        return JSONResponse({"ok": True, "trial": False, "expired": True})
    return JSONResponse({
        "ok": True,
        "trial": True,
        "remaining_sec": remaining,
        "expires_at": active.expires_at.isoformat() + "Z",
    })

@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    user: User = Depends(require_user),
):
    return templates.TemplateResponse("auth/change_password.html", {
        "request": request, "user": user, "error": None, "success": None,
    })


@router.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Any logged-in user including General Admin can change their password."""
    if not verify_password(current_password, user.hashed_password):
        return templates.TemplateResponse("auth/change_password.html", {
            "request": request, "user": user,
            "error": "Current password is incorrect", "success": None,
        }, status_code=400)
    strength_err = validate_password_strength(new_password)
    if strength_err:
        return templates.TemplateResponse("auth/change_password.html", {
            "request": request, "user": user,
            "error": strength_err, "success": None,
        }, status_code=400)
    if new_password != confirm_password:
        return templates.TemplateResponse("auth/change_password.html", {
            "request": request, "user": user,
            "error": "New passwords do not match", "success": None,
        }, status_code=400)
    db_user = session.get(User, user.id)
    db_user.hashed_password = get_password_hash(new_password)
    session.add(db_user)
    session.commit()

    # Security alert: General Admin password change → dual email
    try:
        from app.mailer import send_mail, branded
        import os
        from datetime import datetime
        rv = str(role_val(user.role) if callable(role_val) else getattr(user.role, "value", user.role))
        if "general_admin" in rv:
            notify = os.getenv(
                "ADMIN_PASSWORD_NOTIFY_EMAILS",
                "info@knowsoft.org.ng.com,esemsun1@gmail.com",
            )
            when = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            subject = "Churchgate General Admin password changed"
            text = (
                f"The General Admin password for Churchgate was changed.\n\n"
                f"Account: {user.email}\nWhen: {when}\n"
                f"If you did not make this change, contact Knowsoft immediately.\n"
            )
            html = branded(
                subject,
                f"<p>The <b>General Admin</b> password for Churchgate was changed.</p>"
                f"<p>Account: <b>{user.email}</b><br>When: {when}</p>"
                f"<p>If you did not authorize this, contact Knowsoft immediately.</p>",
            )
            for to in [x.strip() for x in notify.split(",") if x.strip()]:
                send_mail(to, subject, text, html)
    except Exception as _e:
        print("admin password notify:", _e)

    return templates.TemplateResponse("auth/change_password.html", {
        "request": request, "user": user,
        "error": None, "success": "Password updated successfully.",
    })


def _notify_password_changed(phone: str, email: str):
    """Send confirmation via WhatsApp/SMS from +2348081650914 (configure TWILIO_* or WHATSAPP_* env)."""
    import os
    msg = "Your password has been changed successfully in Churchgate."
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_num = os.getenv("TWILIO_FROM", "+2348081650914")
    to = (phone or "").strip()
    if sid and token and to:
        try:
            from urllib.request import Request as UrlReq, urlopen
            import base64
            from urllib.parse import urlencode
            data = urlencode({"From": from_num, "To": to if to.startswith("+") else "+"+to, "Body": msg}).encode()
            req = UrlReq(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=data,
                method="POST",
            )
            auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
            req.add_header("Authorization", f"Basic {auth}")
            urlopen(req, timeout=10)
            return True
        except Exception as e:
            print(f"SMS notify failed: {e}")
    print(f"[Churchgate notify] password changed for {email} phone={to or 'n/a'} via {from_num}: {msg}")
    return False


@router.get("/force-password", response_class=HTMLResponse)
async def force_password_page(
    request: Request,
    user: User = Depends(require_user),
):
    return templates.TemplateResponse("auth/force_password.html", {
        "request": request, "user": user, "error": None,
    })


@router.post("/force-password", response_class=HTMLResponse)
async def force_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    phone: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    err = validate_password_strength(new_password)
    if err:
        return templates.TemplateResponse("auth/force_password.html", {
            "request": request, "user": user, "error": err,
        }, status_code=400)
    if new_password != confirm_password:
        return templates.TemplateResponse("auth/force_password.html", {
            "request": request, "user": user, "error": "Passwords do not match",
        }, status_code=400)
    db = session.get(User, user.id)
    db.hashed_password = get_password_hash(new_password)
    db.must_change_password = False
    if phone.strip():
        db.phone = phone.strip()
    session.add(db)
    session.commit()
    _notify_password_changed(db.phone or phone, db.email)
    return RedirectResponse("/", status_code=303)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request, "error": None, "success": None,
    })


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    phone: str = Form(""),
    session: Session = Depends(get_session),
):
    email = (email or "").strip().lower()
    lock = login_lockout_seconds(email)
    if lock > 0:
        return templates.TemplateResponse("auth/forgot_password.html", {
            "request": request,
            "error": f"Too many attempts. Please wait about {max(1, lock // 60)} minute(s) and try again.",
            "success": None,
        }, status_code=429)
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        record_login_failure(email)
        return templates.TemplateResponse("auth/forgot_password.html", {
            "request": request, "error": "No account found for that email.", "success": None,
        }, status_code=400)
    err = validate_password_strength(new_password)
    if err:
        return templates.TemplateResponse("auth/forgot_password.html", {
            "request": request, "error": err, "success": None,
        }, status_code=400)
    if new_password != confirm_password:
        return templates.TemplateResponse("auth/forgot_password.html", {
            "request": request, "error": "Passwords do not match.", "success": None,
        }, status_code=400)
    user.hashed_password = get_password_hash(new_password)
    user.must_change_password = False
    if phone.strip():
        user.phone = phone.strip()
    session.add(user)
    session.commit()
    clear_login_failures(email)
    _notify_password_changed(user.phone or phone, user.email)
    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request, "error": None,
        "success": "Password updated. A confirmation was sent to your phone when SMS is configured. You can sign in now.",
    })
