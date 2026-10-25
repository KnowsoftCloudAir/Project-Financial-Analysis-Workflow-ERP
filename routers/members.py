import shutil
"""Public member registration + member portal after approval."""
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime, date
import uuid, shutil

from app.database import get_session
from app.models import (
    User, UserRole, ChurchUnit, ChurchLevel, ChurchMember, ChurchLevel as CL
)
from app.activity import log_activity
from app.auth import (
    get_current_user, require_user, get_password_hash, create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES, verify_password
)

router = APIRouter(tags=["members"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
UPLOAD = Path("app/static/uploads")
UPLOAD.mkdir(parents=True, exist_ok=True)

@router.get("/join", response_class=HTMLResponse)
async def join_page(request: Request, session: Session = Depends(get_session)):
    globals_ = session.exec(
        select(ChurchUnit).where(
            ChurchUnit.level == ChurchLevel.global_church,
            ChurchUnit.approval_status == "approved"
        ).order_by(ChurchUnit.name)
    ).all()
    return templates.TemplateResponse("members/join.html", {
        "request": request, "globals": globals_
    })

@router.get("/api/churches")
async def list_child_churches(
    parent_id: int,
    session: Session = Depends(get_session)
):
    children = session.exec(
        select(ChurchUnit).where(
            ChurchUnit.parent_id == parent_id,
            ChurchUnit.approval_status == "approved"
        ).order_by(ChurchUnit.name)
    ).all()
    return [{"id": c.id, "name": c.name, "code": c.code, "level": c.level.value} for c in children]

@router.post("/join")
async def join_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    sex: str = Form(...),
    age_category: str = Form(...),
    confession: str = Form(...),
    member_since: str = Form(""),
    prayer_request: str = Form(""),
    address: str = Form(""),
    whatsapp: str = Form(""),
    phone: str = Form(""),
    global_id: int = Form(...),
    country_id: int = Form(...),
    state_id: int = Form(...),
    group_id: int = Form(...),
    district_id: int = Form(...),
    profile_pic: UploadFile = File(None),
    promo_code: str = Form(""),
    session: Session = Depends(get_session)
):
    if session.exec(select(User).where(User.email == email)).first():
        globals_ = session.exec(select(ChurchUnit).where(
            ChurchUnit.level == ChurchLevel.global_church, ChurchUnit.approval_status == "approved"
        )).all()
        return templates.TemplateResponse("members/join.html", {
            "request": request, "globals": globals_,
            "error": "Email already registered. Please sign in."
        }, status_code=400)

    district = session.get(ChurchUnit, district_id)
    if not district or district.level != ChurchLevel.district:
        raise HTTPException(400, "Please select a valid District church")

    pic_path = None
    if profile_pic and profile_pic.filename:
        ext = profile_pic.filename.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "webp", "gif"):
            fname = f"member_{uuid.uuid4().hex[:10]}.{ext}"
            dest = UPLOAD / fname
            with open(dest, "wb") as f:
                shutil.copyfileobj(profile_pic.file, f)
            pic_path = f"/static/uploads/{fname}"

    ms = None
    if member_since:
        try:
            ms = date.fromisoformat(member_since)
        except ValueError:
            ms = None

    member = ChurchMember(
        church_id=district_id,
        global_church_id=global_id,
        country_church_id=country_id,
        state_church_id=state_id,
        group_church_id=group_id,
        full_name=full_name.strip(),
        sex=sex,
        age_category=age_category,
        confession=confession,
        member_since=ms or date.today(),
        prayer_request=prayer_request.strip() or None,
        address=address.strip() or None,
        whatsapp=whatsapp.strip() or None,
        phone=phone.strip() or None,
        email=email.strip(),
        profile_pic=pic_path,
        status="member",
        approval_status="pending",
        is_active=True,
    )
    session.add(member)
    session.commit()
    session.refresh(member)

    from app.referral_logic import generate_promo_code, resolve_referrer
    user = User(
        email=email.strip(),
        hashed_password=get_password_hash(password),
        full_name=full_name.strip(),
        role=UserRole.member,
        church_id=district_id,
        member_id=member.id,
        is_active=True,  # can login but limited until approved
        promo_code=generate_promo_code(session, full_name),
    )
    ref = resolve_referrer(session, promo_code or "")
    if ref:
        user.referred_by_user_id = ref.id
    session.add(user)
    session.commit()

    return templates.TemplateResponse("members/pending.html", {
        "request": request, "full_name": full_name, "email": email
    })

@router.get("/member/portal", response_class=HTMLResponse)
async def member_portal(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session)
):
    """Member dashboard. Sample / pending get limited UI; never 500 on missing data."""
    from app.models import SpecialProgram, ProgramPhoto, WeeklyStat, PhotoLike, PhotoComment
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()

    is_sample = bool(getattr(user, "is_sample_account", False))
    status = (getattr(member, "approval_status", None) or "") if member else ""
    is_preview = bool(member and status == "pending" and not is_sample)
    # Expired / waiting payment: same limited surface as awaiting approval
    is_awaiting_payment = bool(
        member
        and status in ("waiting_approval", "waiting_subscription")
    )
    # Sample trial over also locks (same UI as awaiting approval)



    church = session.get(ChurchUnit, user.church_id) if user.church_id else None
    if not church and member and getattr(member, "church_id", None):
        church = session.get(ChurchUnit, member.church_id)

    programs = []
    photos = []
    district_member_count = None
    weekly_note = None
    sample_warning = None
    sample_info = None
    pastor_messages = []
    sub_active = None
    sub_settings = None
    sub_days_left = 0
    sub_hours_left = 0
    sub_secs_left = 0
    sub_pct = 0
    sub_is_welcome = False
    had_expired_sub = False
    focus_notice_count = 0
    focus_latest_at = ""

    # Subscription / sample / welcome (must not break portal)
    try:
        from app.routers.subscriptions import (
            check_sample_member, expire_due_subscriptions, _settings, ensure_welcome_trial,
        )
        from app.models import MemberSubscription
        expire_due_subscriptions(session)
        if not is_sample and not is_preview and not is_awaiting_payment:
            try:
                ensure_welcome_trial(session, user)
            except Exception as we:
                print("welcome trial:", we)
            if user.member_id:
                member = session.get(ChurchMember, user.member_id) or member
            status = (getattr(member, "approval_status", None) or "") if member else status
            is_awaiting_payment = bool(
                member and status in ("waiting_approval", "waiting_subscription") and not is_sample
            )

        sample_info = check_sample_member(session, user)
        # Sample expired: stay logged in, lock like waiting_approval (do not redirect logout)
        if sample_info.get("expired") or sample_info.get("locked"):
            is_awaiting_payment = True
            is_sample = True
            if member:
                member.approval_status = "waiting_approval"
        if sample_info.get("show_warning") or sample_info.get("is_sample"):
            sample_warning = sample_info.get("message")

        if not is_sample:
            sub_settings = _settings(session)
            subs = list(session.exec(
                select(MemberSubscription).where(MemberSubscription.user_id == user.id)
                .order_by(MemberSubscription.created_at.desc())
            ).all())
            sub_active = next((s for s in subs if s.status == "active"), None)
            had_expired_sub = any(getattr(s, "status", None) == "expired" for s in subs)
            if sub_active and sub_active.ends_at:
                from datetime import datetime as _dt
                delta = sub_active.ends_at - _dt.utcnow()
                secs = max(0, int(delta.total_seconds()))
                sub_secs_left = secs
                sub_days_left = secs // 86400
                sub_hours_left = (secs % 86400) // 3600
                sub_is_welcome = (getattr(sub_active, "plan", None) or "") == "welcome"
                if sub_active.starts_at and sub_active.ends_at:
                    total_secs = max(1, int((sub_active.ends_at - sub_active.starts_at).total_seconds()))
                    sub_pct = min(100, max(0, round(100 * secs / total_secs)))
                else:
                    sub_pct = 100 if secs > 0 else 0
    except Exception as e:
        print("sample/sub check:", e)
        if sample_info is None and is_sample:
            sample_info = {
                "is_sample": True, "show_warning": True, "expired": False,
                "minutes_left": 5, "seconds_left": 300, "pct_left": 100,
                "message": "Sample membership (5-min trial). Register as a full member for perpetual access.",
                "can_subscribe": False,
            }
            sample_warning = sample_info["message"]

    # Programs / photos (optional)
    if church and not is_preview and not is_awaiting_payment:
        try:
            scope = {church.id}
            ch = church
            while ch and ch.parent_id:
                scope.add(ch.parent_id)
                ch = session.get(ChurchUnit, ch.parent_id)
            programs = list(session.exec(
                select(SpecialProgram).where(
                    SpecialProgram.church_id.in_(list(scope)),
                    SpecialProgram.is_active == True
                ).order_by(SpecialProgram.created_at.desc()).limit(10)
            ).all())
            prog_ids = [p.id for p in programs]
            if prog_ids:
                raw_photos = list(session.exec(
                    select(ProgramPhoto).where(ProgramPhoto.program_id.in_(prog_ids))
                    .order_by(ProgramPhoto.created_at.desc()).limit(12)
                ).all())
                for ph in raw_photos:
                    try:
                        likes = list(session.exec(select(PhotoLike).where(PhotoLike.photo_id == ph.id)).all())
                        comments = list(session.exec(select(PhotoComment).where(PhotoComment.photo_id == ph.id)).all())
                        photos.append({
                            "id": ph.id, "path": ph.file_path, "caption": ph.caption,
                            "program_id": ph.program_id,
                            "likes": len(likes),
                            "liked": any(l.user_id == user.id for l in likes),
                            "comment_count": len(comments),
                        })
                    except Exception:
                        photos.append({
                            "id": ph.id, "path": ph.file_path, "caption": ph.caption,
                            "program_id": ph.program_id, "likes": 0, "liked": False, "comment_count": 0,
                        })
        except Exception as e:
            print("programs load:", e)

    if church and getattr(user, "can_see_member_counts", False):
        try:
            from sqlmodel import func
            district_member_count = session.exec(
                select(func.count()).select_from(ChurchMember).where(
                    ChurchMember.church_id == church.id,
                    ChurchMember.approval_status == "approved",
                )
            ).one()
        except Exception:
            district_member_count = None

    if church:
        try:
            weekly_note = getattr(church, "weekly_activities_note", None)
        except Exception:
            weekly_note = None

    # Pastor messages (optional)
    try:
        from app.models import PastorMessage, ChurchUnit as CU
        cid = (user.church_id if user.church_id else None) or (member.church_id if member else None)
        if cid:
            allowed = set()
            cur = session.get(CU, cid)
            hops = 0
            while cur and hops < 12:
                allowed.add(cur.id)
                if not cur.parent_id:
                    break
                cur = session.get(CU, cur.parent_id)
                hops += 1
            pastor_messages = [
                p for p in session.exec(
                    select(PastorMessage).where(PastorMessage.is_active == True)
                    .order_by(PastorMessage.created_at.desc()).limit(40)
                ).all()
                if p.church_id in allowed
            ][:10]
    except Exception as e:
        print("pastor msgs:", e)
        pastor_messages = []


    focus_notice_count = 0
    focus_latest_at = ""
    try:
        from app.models import FocusGroup, FocusGroupMember, FocusGroupMessage
        from datetime import datetime, timedelta
        mrec = session.get(ChurchMember, user.member_id) if user.member_id else None
        if not mrec:
            mrec = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
        gids = []
        if mrec:
            gids = [
                fm.group_id for fm in session.exec(
                    select(FocusGroupMember).where(FocusGroupMember.member_id == mrec.id)
                ).all()
            ]
        if gids:
            since = datetime.utcnow() - timedelta(days=30)
            msgs = list(session.exec(
                select(FocusGroupMessage).where(
                    FocusGroupMessage.group_id.in_(gids),
                    FocusGroupMessage.created_at >= since,
                ).order_by(FocusGroupMessage.created_at.desc()).limit(100)
            ).all())
            incoming = [m for m in msgs if getattr(m, "sender_id", None) != user.id]
            focus_notice_count = len(incoming) if incoming else len(msgs)
            if msgs:
                ca = msgs[0].created_at
                focus_latest_at = ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
    except Exception as fe:
        print("focus notice:", fe)
        focus_notice_count = 0
        focus_latest_at = ""


    promo_code = None
    ref_stats = None
    try:
        from app.referral_logic import ensure_user_promo_code, count_referrals
        try:
            promo_code = ensure_user_promo_code(session, user)
            ref_stats = count_referrals(session, user.id)
        except Exception as _re:
            print("referral panel:", _re)
            promo_code = getattr(user, "promo_code", None)
            ref_stats = None
    except Exception as _re:
        print("referral panel:", _re)

    try:
        log_activity(session, user=user, action="portal_view", detail="Opened member dashboard", request=request)
    except Exception:
        pass
    ctx = {
        "request": request,
        "user": user,
        "member": member,
        "church": church,
        "programs": programs or [],
        "photos": photos or [],
        "district_member_count": district_member_count,
        "weekly_note": weekly_note,
        "sample_warning": sample_warning,
        "sample_info": sample_info or {"is_sample": False},
        "sub_active": sub_active,
        "sub_settings": sub_settings,
        "sub_days_left": sub_days_left or 0,
        "sub_hours_left": sub_hours_left or 0,
        "sub_secs_left": sub_secs_left or 0,
        "sub_pct": sub_pct or 0,
        "sub_is_welcome": bool(sub_is_welcome),
        "had_expired_sub": bool(had_expired_sub),
        "pastor_messages": pastor_messages or [],
        "pastor_notice_count": len(pastor_messages or []),
        "focus_notice_count": focus_notice_count if "focus_notice_count" in dir() else 0,
        "focus_latest_at": focus_latest_at if "focus_latest_at" in dir() else "",
        "is_preview": bool(is_preview),
        "is_awaiting_payment": bool(is_awaiting_payment),
        "promo_code": promo_code,
        "ref_stats": ref_stats,
    }
    try:
        return templates.TemplateResponse("members/portal.html", ctx)
    except Exception as _pe:
        print("portal template error:", _pe)
        return templates.TemplateResponse(
            "empty_state.html",
            {
                "request": request,
                "title": "Dashboard temporarily unavailable",
                "message": "Your login worked, but the member page hit an error. Use Home or try again shortly.",
            },
            status_code=200,
        )


@router.post("/member/update-profile")
async def update_profile(
    request: Request,
    full_name: str = Form(...),
    whatsapp: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    prayer_request: str = Form(""),
    confession: str = Form(""),
    requested_status: str = Form(""),
    requested_title: str = Form(""),
    profile_pic: UploadFile = File(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session)
):
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    if not member:
        raise HTTPException(404, "Member profile not found")
    if member.approval_status not in ("approved", "pending"):
        raise HTTPException(403, "Account not active")
    member.full_name = full_name.strip()
    member.whatsapp = whatsapp or None
    member.phone = phone or None
    member.address = address or None
    member.prayer_request = prayer_request or None
    if confession:
        member.confession = confession
    # Profile picture change from member page
    if profile_pic and getattr(profile_pic, "filename", None):
        if profile_pic.content_type and profile_pic.content_type.startswith("image/"):
            ext = (profile_pic.filename or "jpg").rsplit(".", 1)[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            up = Path("app/static/uploads/profiles")
            up.mkdir(parents=True, exist_ok=True)
            fname = f"m{member.id}_{uuid.uuid4().hex[:8]}.{ext}"
            dest = up / fname
            with open(dest, "wb") as f:
                shutil.copyfileobj(profile_pic.file, f)
            member.profile_pic = f"/static/uploads/profiles/{fname}"
    # Member may propose status; admin confirms via Approvals / members list
    if requested_status or requested_title:
        note = f"[Status request: {requested_status or member.status}"
        if requested_title:
            note += f" / title: {requested_title}"
        note += "]"
        member.notes = ((member.notes or "") + " " + note).strip()
        # Soft-update display title only if they already have a role; full status stays until admin edits
        if requested_title:
            member.custom_title = requested_title.strip()
    user.full_name = full_name.strip()
    session.add(member)
    session.add(user)
    session.commit()
    return RedirectResponse("/member/portal", status_code=303)

@router.post("/member/request-discontinue")
async def request_discontinue(
    user: User = Depends(require_user),
    session: Session = Depends(get_session)
):
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    if member:
        member.discontinue_requested = True
        session.add(member)
        session.commit()
    return RedirectResponse("/member/portal", status_code=303)


@router.get("/api/churches-by-level")
async def churches_by_level(level: str = "global", session: Session = Depends(get_session)):
    try:
        lv = ChurchLevel(level if level != "global" else "global")
    except ValueError:
        lv = ChurchLevel.global_church
    if level == "global":
        lv = ChurchLevel.global_church
    rows = session.exec(
        select(ChurchUnit).where(
            ChurchUnit.level == lv,
            ChurchUnit.approval_status == "approved"
        ).order_by(ChurchUnit.name)
    ).all()
    return [{"id": c.id, "name": c.name, "code": c.code, "level": getattr(c.level, "value", str(c.level))} for c in rows]


@router.get("/api/geo/countries")
async def geo_countries():
    import json
    from pathlib import Path as P
    p = P(__file__).resolve().parent.parent / "data" / "countries.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/api/music-links")
async def api_music_links(
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """
    Returns:
      platform: General Admin tracks (church_id is null)
      church: tracks added by this member's church and parent churches only
    """
    from app.models import MusicLink, ChurchUnit
    platform, church = [], []
    try:
        rows = list(session.exec(
            select(MusicLink).where(MusicLink.is_active == True).order_by(MusicLink.sort_order, MusicLink.id)
        ).all())
        allowed = set()
        own_id = None
        cid = getattr(user, "church_id", None) if user else None
        if not cid and user and getattr(user, "member_id", None):
            m = session.get(ChurchMember, user.member_id)
            if m:
                cid = m.church_id
        own_id = cid
        if cid:
            cur = session.get(ChurchUnit, cid)
            hops = 0
            while cur and hops < 12:
                allowed.add(cur.id)
                if not cur.parent_id:
                    break
                cur = session.get(ChurchUnit, cur.parent_id)
                hops += 1
        seen_p, seen_c = set(), set()
        for L in rows:
            yid = (L.youtube_id or "").strip()
            if not yid:
                continue
            if L.church_id is None:
                if yid not in seen_p:
                    seen_p.add(yid)
                    platform.append({"id": yid, "title": L.title or yid, "source": "platform"})
            elif L.church_id in allowed:
                if yid not in seen_c:
                    seen_c.add(yid)
                    # label: own church vs parent
                    src = "my_church" if own_id and L.church_id == own_id else "parent_church"
                    church.append({
                        "id": yid,
                        "title": L.title or yid,
                        "source": src,
                    })
    except Exception as e:
        print("music links", e)
    # backward compatible flat list
    flat = list(platform) + list(church)
    return {"platform": platform, "church": church, "all": flat}



@router.post("/member/{member_id}/toggle-broadcast")
async def toggle_broadcast(
    member_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """District/church admin may grant broadcast privilege to an approved member."""
    from app.auth import role_val
    if role_val(user.role) not in ("church_admin", "general_admin"):
        raise HTTPException(403, "Admin only")
    target = session.exec(select(User).where(User.member_id == member_id)).first()
    if not target:
        raise HTTPException(404, "User not found")
    target.can_broadcast = not bool(getattr(target, "can_broadcast", False))
    session.add(target)
    session.commit()
    return RedirectResponse("/district/members", status_code=303)


@router.get("/member/pending", response_class=HTMLResponse)
async def member_pending_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    return templates.TemplateResponse("members/pending_access.html", {
        "request": request, "user": user, "member": member,
    })


@router.post("/member/api/log")
async def member_api_log(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    from app.activity import log_activity
    try:
        body = await request.json()
    except Exception:
        body = {}
    log_activity(
        session,
        user=user,
        action=str(body.get("action") or "client_event")[:64],
        detail=str(body.get("detail") or "")[:400],
        request=request,
        location_hint=body.get("location"),
    )
    return {"ok": True}


@router.get("/api/district-members")
async def api_district_members(
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
):
    """Approved members in the same district (or unit) as the current member."""
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    if not member or not member.church_id:
        return []
    church = session.get(ChurchUnit, member.church_id)
    rows = list(session.exec(
        select(ChurchMember).where(
            ChurchMember.church_id == member.church_id,
            ChurchMember.approval_status == "approved",
            ChurchMember.is_active == True,
        ).order_by(ChurchMember.full_name)
    ).all())
    district_name = church.name if church else ""
    out = []
    for m in rows:
        unit = (m.custom_title or m.worker_type or m.leader_type or m.status or "member")
        out.append({
            "id": m.id,
            "name": m.full_name,
            "district": district_name,
            "sex": m.sex or "",
            "unit": unit,
            "status": m.status or "member",
            "profile_pic": m.profile_pic or "",
            "is_travelling": bool(getattr(m, "is_travelling", False)),
            "is_self": bool(user.member_id and m.id == user.member_id),
        })
    return out


@router.post("/api/member-travel")
async def api_member_travel(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
):
    """Current member sets whether they have travelled out of the district."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    travelling = bool(body.get("is_travelling"))
    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    if not member:
        raise HTTPException(404, "Member not found")
    member.is_travelling = travelling
    session.add(member)
    session.commit()
    return {"ok": True, "is_travelling": member.is_travelling}
