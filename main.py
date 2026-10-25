from fastapi import FastAPI, Request, Depends, Form, HTTPException
from typing import Optional
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager
from sqlmodel import Session, select
from pathlib import Path

import app.models  # ensure tables registered including TrialAccess
from app.database import create_db_and_tables, get_session, engine
from app.models import User, UserRole, AngelResourceFile, ChurchHymnal  # noqa: F401 — register tables
from app.auth import get_password_hash, get_current_user, verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.routers import feed, manna, auth, admin, church, district, members, programs, projects, community, payments, youtube_data, messages, subscriptions, backup, announcements, device_music, referrals, kwealth, memories, social_stream, mail_auth, wallet, confirm_registration, angel_resources_admin
from app.seed_sample import ensure_all_sample_data

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    # Restore live data from bundled backup, then lock privileged GA password
    try:
        from app.bundled_restore import restore_bundled_backup
        restore_bundled_backup(force=False)
        # force_general_admin_password()  # disabled: do not reset GA password on deploy
    except Exception as be:
        print(f"⚠️ Bundled restore: {be}")
        try:
            from app.bundled_restore import force_general_admin_password
            # force_general_admin_password()  # disabled: do not reset GA password on deploy
        except Exception as e2:
            print(f"⚠️ GA force: {e2}")

    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in [
                "ALTER TABLE membersubscription ADD COLUMN IF NOT EXISTS payment_method VARCHAR DEFAULT 'bank'",
                "ALTER TABLE membersubscription ADD COLUMN IF NOT EXISTS evidence_image VARCHAR",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_enabled BOOLEAN DEFAULT TRUE",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_currency VARCHAR DEFAULT 'USD'",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_monthly_price FLOAT DEFAULT 5",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_annual_price FLOAT DEFAULT 50",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_instructions TEXT",
                "ALTER TABLE subscriptionsettings ADD COLUMN IF NOT EXISTS card_payment_link VARCHAR",
                "ALTER TABLE membersubscription ADD COLUMN payment_method VARCHAR",
                "ALTER TABLE membersubscription ADD COLUMN evidence_image VARCHAR",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as _pe:
        print("payment cols migrate:", _pe)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in (
                "ALTER TABLE user ADD COLUMN IF NOT EXISTS session_version INTEGER DEFAULT 0",
                "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS session_version INTEGER DEFAULT 0",
                "ALTER TABLE user ADD COLUMN session_version INTEGER DEFAULT 0",
                "ALTER TABLE socialstreamlink ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT 'tv'",
                "ALTER TABLE socialstreamlink ADD COLUMN IF NOT EXISTS youtube_channel_id VARCHAR",
            ):
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as _sv:
        print("session_version migrate:", _sv)

    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in [
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS email VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS full_name VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS ip_address VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS user_agent VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS location_hint VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN IF NOT EXISTS path VARCHAR",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            # SQLite variants without IF NOT EXISTS
            for stmt in [
                "ALTER TABLE activitylog ADD COLUMN email VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN full_name VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN ip_address VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN user_agent VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN location_hint VARCHAR",
                "ALTER TABLE activitylog ADD COLUMN path VARCHAR",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as _ae:
        print("activitylog migrate:", _ae)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in [
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS promo_code VARCHAR',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referral_count_anchor_at TIMESTAMP',
                'ALTER TABLE user ADD COLUMN IF NOT EXISTS referral_count_anchor_at TIMESTAMP',
                'ALTER TABLE referralcashout ADD COLUMN IF NOT EXISTS identity_evidence VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS topic VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS image_path VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS audio_path VARCHAR',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referral_bonus_applied BOOLEAN DEFAULT FALSE',
                'ALTER TABLE user ADD COLUMN IF NOT EXISTS promo_code VARCHAR',
                'ALTER TABLE user ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER',
                'ALTER TABLE user ADD COLUMN IF NOT EXISTS referral_bonus_applied BOOLEAN DEFAULT 0',
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as _ref:
        print("referral cols migrate:", _ref)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE churchmember ADD COLUMN IF NOT EXISTS is_travelling BOOLEAN DEFAULT FALSE"))
            except Exception:
                try:
                    conn.execute(text("ALTER TABLE churchmember ADD COLUMN is_travelling BOOLEAN DEFAULT 0"))
                except Exception:
                    pass
    except Exception as _e:
        print("migrate is_travelling:", _e)

    # Referral / promo columns (safe if already exist)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            for stmt in [
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS promo_code VARCHAR',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER',
                'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS referral_bonus_applied BOOLEAN DEFAULT FALSE',
                'ALTER TABLE referralcashout ADD COLUMN IF NOT EXISTS identity_evidence VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS topic VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS image_path VARCHAR',
                'ALTER TABLE focusgroupmessage ADD COLUMN IF NOT EXISTS audio_path VARCHAR',
                # SQLite fallbacks (ignore errors)
                'ALTER TABLE user ADD COLUMN promo_code VARCHAR',
                'ALTER TABLE user ADD COLUMN referred_by_user_id INTEGER',
                'ALTER TABLE user ADD COLUMN referral_bonus_applied BOOLEAN DEFAULT 0',
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception as _refm:
        print("referral migrate:", _refm)

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kwealthbook ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE"))
    except Exception as _kp:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE kwealthbook ADD COLUMN is_premium BOOLEAN DEFAULT 0"))
        except Exception as _kp2:
            print("kwealth is_premium migrate:", _kp2)


    try:
        with Session(engine) as session:
            # Always ensure General Admin exists with known password
            admin = session.exec(select(User).where(User.email == "admin@knowsoft.com")).first()
            if not admin:
                admin = User(
                    email="admin@knowsoft.com",
                    hashed_password=get_password_hash("Knowsoft#GA2026!"),
                    full_name="Knowsoft General Admin",
                    role=UserRole.general_admin,
                    is_active=True
                )
                session.add(admin)
            else:
                # NEVER reset an existing admin password on deploy
                admin.is_active = True
                admin.role = UserRole.general_admin
                session.add(admin)
            session.commit()
            if session.exec(select(User).where(User.email == "admin@knowsoft.com")).first():
                print("✅ General Admin present (password unchanged if already set)")
            try:
                from app.youtube_persist import restore_into_db, mirror_from_db
                n = restore_into_db(session)
                print(f"✅ YouTube persist restore/mirror: {n}")
            except Exception as ye:
                print("youtube persist:", ye)

            # Hierarchy + music first (sample member needs a district)
            try:
                ensure_all_sample_data(session)
            except Exception as se:
                print(f"⚠️ Sample data seed failed: {se}")
                import traceback
                traceback.print_exc()
            try:
                from app.bundled_restore import force_general_admin_password
                # force_general_admin_password()  # disabled: do not reset GA password on deploy
            except Exception as e:
                print("GA force after seed:", e)
            # Shared sample member (multi-login, 3 minutes each)
            from app.seed_sample import seed_sample_member
            try:
                seed_sample_member(session)
            except Exception as se:
                print("sample member seed:", se)
            # Force-reset sample password every boot so login never drifts
            try:
                sample = session.exec(select(User).where(User.email == "angel@churchgate.com")).first()
                if sample:
                    sample.hashed_password = get_password_hash("ilovechurhgate")
                    sample.is_active = True
                    sample.is_sample_account = True
                    sample.role = UserRole.member
                    sample.sample_started_at = None
                    session.add(sample)
                    session.commit()
                    print("✅ Sample login forced: angel@churchgate.com / ilovechurhgate")
                else:
                    print("⚠️ Sample user angel@churchgate.com still missing after seed")
            except Exception as se:
                print("sample force password:", se)
    except Exception as e:
        print(f"⚠️ Seed: {e}")
        import traceback
        traceback.print_exc()
    yield


app = FastAPI(
    title="Knowsoft Churchgate",
    description="Church hierarchy, membership & growth analytics platform",
    version="1.0.0",
    lifespan=lifespan
)


@app.middleware("http")
async def trial_feature_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/member/") and not path.startswith("/member/subscription") and path != "/member/portal":
        try:
            from jose import jwt
            from app.auth import SECRET_KEY, ALGORITHM, get_user_by_email, role_val
            from app.database import engine
            from app.member_access import features_open
            from sqlmodel import Session as _S
            token = request.cookies.get("access_token")
            if token:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                email = payload.get("sub")
                with _S(engine) as session:
                    user = get_user_by_email(session, email) if email else None
                    if user and role_val(user.role) == "member" and not features_open(session, user):
                        from fastapi.responses import RedirectResponse
                        return RedirectResponse("/member/subscription?expired=1", status_code=303)
        except Exception as _gate:
            print("trial gate:", _gate)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(self), camera=()")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response



BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(church.router)
app.include_router(district.router)
app.include_router(members.router)
app.include_router(programs.router)
app.include_router(projects.router)
app.include_router(community.router)
app.include_router(payments.router)
app.include_router(messages.router)
app.include_router(subscriptions.router)
app.include_router(backup.router)
app.include_router(announcements.router)
app.include_router(device_music.router)
app.include_router(youtube_data.router)
app.include_router(feed.router)
app.include_router(manna.router)
app.include_router(referrals.router)
app.include_router(kwealth.router)
app.include_router(memories.router)
app.include_router(social_stream.router)
app.include_router(wallet.router)
app.include_router(mail_auth.router)
app.include_router(confirm_registration.router)
app.include_router(angel_resources_admin.router)
try:
    from app.routers import permanent_library
    app.include_router(permanent_library.router)
except Exception as _pl:
    print('permanent_library not loaded:', _pl)


@app.get("/privacy")
async def privacy_page(request: Request):
    return templates.TemplateResponse("legal/privacy.html", {"request": request})

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "empty_state.html",
        {"request": request, "title": "Page not found", "message": "This page was not found or has no content."},
        status_code=404,
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    accept = (request.headers.get("accept") or "")
    wants_html = "text/html" in accept or exc.status_code in (401, 403, 404, 500)
    if wants_html or exc.status_code >= 400:
        title = "Restricted area" if exc.status_code in (401, 403) else (
            "Page not found" if exc.status_code == 404 else "Something went wrong"
        )
        return templates.TemplateResponse(
            "empty_state.html",
            {
                "request": request,
                "title": title,
                "message": str(exc.detail) if exc.detail else "You can go back or return to the home page.",
            },
            status_code=exc.status_code,
        )
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    print("UNHANDLED:", exc)
    traceback.print_exc()
    return templates.TemplateResponse(
        "empty_state.html",
        {
            "request": request,
            "title": "Something went wrong",
            "message": "An unexpected error occurred. Please go back or return home and try again.",
        },
        status_code=500,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        from app.auth import role_val
        rv = role_val(user.role)
        if rv == "general_admin":
            return RedirectResponse("/admin/", status_code=303)
        if rv == "member" and not getattr(user, "can_view_church_dashboard", False):
            return RedirectResponse("/member/portal", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)
    # Public landing: General-Admin-approved Global church programs
    featured = []
    try:
        from sqlmodel import Session, select
        from app.database import engine
        from app.models import SpecialProgram, ProgramPhoto, ProgramVideo, ChurchUnit, ChurchLevel
        with Session(engine) as session:
            from datetime import datetime as _dt
            now = _dt.utcnow()
            progs = list(session.exec(
                select(SpecialProgram).where(
                    SpecialProgram.featured_on_home == True,
                    SpecialProgram.is_active == True,
                ).order_by(SpecialProgram.created_at.desc())
            ).all())
            for p in progs:
                ends = getattr(p, "home_display_ends_at", None)
                if ends and ends <= now:
                    p.featured_on_home = False
                    session.add(p)
                    continue
                if ends is None and getattr(p, "home_display_hours", None):
                    # legacy without ends_at — skip until re-approved
                    continue
                church = session.get(ChurchUnit, p.church_id)
                if not church:
                    continue
                lv = str(getattr(church.level, "value", church.level)).lower()
                if lv not in ("global", "global_church"):
                    continue
                photo = session.exec(
                    select(ProgramPhoto).where(ProgramPhoto.program_id == p.id)
                    .order_by(ProgramPhoto.created_at.desc())
                ).first()
                video = session.exec(
                    select(ProgramVideo).where(ProgramVideo.program_id == p.id)
                    .order_by(ProgramVideo.created_at.desc())
                ).first()
                try:
                    session.commit()
                except Exception:
                    pass
                logo = getattr(church, "logo_url", None) or ""
                featured.append({
                    "title": p.title,
                    "church": church.name,
                    "church_logo": logo if logo.startswith("/") else (("/" + logo) if logo else ""),
                    "date": str(p.program_date) if p.program_date else "",
                    "venue": p.location or "",
                    "photo": (
                        photo.file_path if photo and photo.file_path.startswith("/")
                        else ("/" + photo.file_path if photo and photo.file_path else "")
                    ),
                    "video": (video.file_path if video and video.file_path.startswith("/") else (("/" + video.file_path) if video and video.file_path else "")),
                    "description": (p.description or "")[:180],
                })
    except Exception as e:
        print(f"featured load: {e}")
    youtube_clips = []
    live_stats = {"churches": 0, "countries": 0, "states": 0, "members": 0}
    try:
        from app.models import YoutubeChannelLink, ChurchMember, ChurchLevel
        with Session(engine) as session:
            for L in session.exec(
                select(YoutubeChannelLink).where(
                    YoutubeChannelLink.is_approved == True,
                    YoutubeChannelLink.is_active == True,
                ).order_by(YoutubeChannelLink.created_at.desc())
            ).all():
                if not L.youtube_video_id:
                    continue
                ch = session.get(ChurchUnit, L.church_id) if L.church_id else None
                youtube_clips.append({
                    "title": L.title or "YouTube",
                    "church": ch.name if ch else "Knowsoft Churchgate",
                    "video_id": L.youtube_video_id,
                    "url": L.youtube_url,
                })
            units = list(session.exec(select(ChurchUnit).where(ChurchUnit.is_active == True)).all())
            countries = set()
            states = set()
            n_churches = 0
            for u in units:
                if (u.approval_status or "approved") != "approved":
                    continue
                n_churches += 1
                lv = str(getattr(u.level, "value", u.level)).lower()
                if u.country_name:
                    countries.add(u.country_name.strip().lower())
                if "country" in lv:
                    countries.add((u.name or "").strip().lower())
                if u.state_name:
                    states.add(f"{(u.country_name or '')}:{(u.state_name or '')}".lower())
                if "state" in lv:
                    states.add((u.name or "").strip().lower())
            n_members = len(session.exec(
                select(ChurchMember).where(ChurchMember.approval_status == "approved", ChurchMember.is_active == True)
            ).all())
            live_stats = {
                "churches": max(n_churches, 1),
                "countries": max(len(countries), 1),
                "states": max(len(states), 1),
                "members": max(n_members, 1),
            }
    except Exception as e:
        print(f"home yt/stats: {e}")
    return templates.TemplateResponse("index.html", {
        "request": request, "user": None,
        "featured_programs": featured,
        "youtube_clips": youtube_clips,
        "live_stats": live_stats,
    })


@app.get("/manifest.json")
async def root_manifest():
    from fastapi.responses import FileResponse
    return FileResponse(str(BASE_DIR / "app" / "static" / "manifest.json"), media_type="application/manifest+json")

@app.get("/sw.js")
async def root_sw():
    from fastapi.responses import FileResponse, Response
    path = BASE_DIR / "app" / "static" / "sw.js"
    content = path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/javascript; charset=utf-8",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )

@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "ok", "app": "Knowsoft Churchgate"}

@app.head("/")
async def home_head():
    """Render / uptime probes send HEAD; avoid 405 noise."""
    from fastapi.responses import Response
    return Response(status_code=200)


# Hidden admin portal
@app.get("/ks-admin/login", response_class=HTMLResponse)
async def ks_admin_login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request})

@app.post("/ks-admin/login")
async def ks_admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session)
):
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("admin/login.html", {
            "request": request, "error": "Invalid credentials"
        }, status_code=400)
    if user.role != UserRole.general_admin:
        return templates.TemplateResponse("admin/login.html", {
            "request": request, "error": "General Admin only"
        }, status_code=403)
    token = create_access_token({"sub": user.email})
    resp = RedirectResponse("/admin/", status_code=303)
    resp.set_cookie("access_token", token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
    return resp
