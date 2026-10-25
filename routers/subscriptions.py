"""Member subscriptions: GA sets prices; members request; GA confirms; auto-expire."""
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import secrets
import string
import shutil
from pathlib import Path as FsPath

from fastapi import APIRouter, Depends, Request, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    User, UserRole, ChurchMember, SubscriptionSettings, MemberSubscription
)
from app.auth import require_user, require_roles, role_val

router = APIRouter(tags=["subscriptions"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _settings(session: Session) -> SubscriptionSettings:
    s = session.exec(select(SubscriptionSettings).where(SubscriptionSettings.is_active == True)).first()
    if not s:
        s = SubscriptionSettings(
            title="Churchgate member subscription",
            currency="NGN",
            monthly_price=1500.0,
            annual_price=15000.0,
            instructions="Transfer to the account below. Use your email as payment narration, then submit this form. General Admin will confirm.",
            bank_name="GTBank",
            account_name="Knowsoft Technologies",
            account_number="0123456789",
            is_active=True,
        )
        session.add(s)
        session.commit()
        session.refresh(s)
    return s



def ensure_welcome_trial(session: Session, user: User):
    """After district approval, first portal login starts a 7-minute welcome subscription."""
    from typing import Optional
    if getattr(user, "is_sample_account", False):
        return None
    if not user.member_id:
        return None
    mem = session.get(ChurchMember, user.member_id)
    if not mem:
        return None
    if mem.approval_status not in ("approved", "waiting_approval", "waiting_subscription"):
        return None
    existing_paid = session.exec(
        select(MemberSubscription).where(
            MemberSubscription.user_id == user.id,
            MemberSubscription.status == "active",
            MemberSubscription.plan != "welcome",
        )
    ).first()
    if existing_paid:
        return existing_paid
    now = datetime.utcnow()
    welcome = session.exec(
        select(MemberSubscription).where(
            MemberSubscription.user_id == user.id,
            MemberSubscription.plan == "welcome",
        ).order_by(MemberSubscription.created_at.desc())
    ).first()
    if not welcome:
        if not getattr(user, "welcome_started_at", None):
            user.welcome_started_at = now
            session.add(user)
        ends = now + timedelta(minutes=7)
        welcome = MemberSubscription(
            user_id=user.id,
            member_id=user.member_id,
            plan="welcome",
            amount=0.0,
            currency="NGN",
            duration_days=0,
            status="active",
            payment_reference="WELCOME-7MIN",
            starts_at=now,
            ends_at=ends,
            note="Complimentary 7-minute welcome access after approval",
        )
        session.add(welcome)
        if mem.approval_status != "approved":
            mem.approval_status = "approved"
            session.add(mem)
        session.commit()
        session.refresh(welcome)
        return welcome
    if welcome.status == "active" and welcome.ends_at and welcome.ends_at <= now:
        welcome.status = "expired"
        session.add(welcome)
        mem.approval_status = "waiting_approval"
        session.add(mem)
        session.commit()
    elif welcome.status == "active":
        # If an older 30-min welcome is still running, leave ends_at as set
        if mem.approval_status != "approved":
            mem.approval_status = "approved"
            session.add(mem)
            session.commit()
    return welcome


def expire_due_subscriptions(session: Session) -> int:
    """Mark ended subscriptions expired; member goes to waiting_approval (can still pay)."""
    now = datetime.utcnow()
    n = 0
    active = list(session.exec(
        select(MemberSubscription).where(MemberSubscription.status == "active")
    ).all())
    for sub in active:
        if sub.ends_at and sub.ends_at <= now:
            sub.status = "expired"
            session.add(sub)
            user = session.get(User, sub.user_id)
            if user and user.member_id:
                mem = session.get(ChurchMember, user.member_id)
                if mem:
                    other = session.exec(
                        select(MemberSubscription).where(
                            MemberSubscription.user_id == user.id,
                            MemberSubscription.status == "active",
                            MemberSubscription.id != sub.id,
                        )
                    ).first()
                    if not other:
                        # Keep login; require new payment evidence
                        mem.approval_status = "waiting_approval"
                        session.add(mem)
                        # Account stays active so they can open Subscription
                        if not user.is_active:
                            user.is_active = True
                            session.add(user)
            n += 1
    if n:
        session.commit()
    return n


def check_sample_member(session: Session, user: User) -> dict:
    """Sample account: 5 minutes from first use, then deactivate. Cannot subscribe."""
    SAMPLE_SECONDS = 3 * 60  # 3 minutes per login (shared sample account)
    info = {
        "is_sample": bool(getattr(user, "is_sample_account", False)),
        "show_warning": False,
        "expired": False,
        "minutes_left": None,
        "seconds_left": None,
        "pct_left": 100,
        "message": None,
        "can_subscribe": True,
    }
    if not info["is_sample"]:
        return info
    info["can_subscribe"] = False
    info["locked"] = False
    now = datetime.utcnow()
    started = getattr(user, "sample_started_at", None)
    if not started:
        user.sample_started_at = now
        session.add(user)
        session.commit()
        started = now
        session.refresh(user)
    elapsed = max(0.0, (now - started).total_seconds())
    left = max(0, int(SAMPLE_SECONDS - elapsed))
    info["seconds_left"] = left
    info["minutes_left"] = left // 60
    info["pct_left"] = min(100, round(100 * left / SAMPLE_SECONDS)) if SAMPLE_SECONDS else 0
    mins = left // 60
    secs = left % 60
    info["message"] = (
        f"Sample membership (3-min session): {mins}m {secs:02d}s left. "
        "Sample accounts cannot subscribe — please register as a full member for perpetual access."
    )
    info["show_warning"] = True  # always show while sample is active
    if left <= 0:
        info["expired"] = True
        info["locked"] = True
        info["message"] = (
            "Sample 3-minute session ended. Register as a member of a church to continue. "
            "Resources and Angel are locked until you join as a full member."
        )
        # Do NOT log out — same as paid members: waiting_approval style lock
        user.is_active = True
        if user.member_id:
            mem = session.get(ChurchMember, user.member_id)
            if mem:
                mem.approval_status = "waiting_approval"
                session.add(mem)
        session.add(user)
        session.commit()
    return info


@router.get("/member/subscription", response_class=HTMLResponse)
async def member_subscription_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    expire_due_subscriptions(session)
    settings = _settings(session)
    subs = list(session.exec(
        select(MemberSubscription).where(MemberSubscription.user_id == user.id)
        .order_by(MemberSubscription.created_at.desc())
    ).all())
    active = next((s for s in subs if s.status == "active"), None)
    sample = check_sample_member(session, user)
    if sample.get("expired"):
        return RedirectResponse("/auth/login?sample=expired", status_code=303)
    return templates.TemplateResponse("subscriptions/member.html", {
        "request": request, "user": user, "settings": settings,
        "subs": subs, "active": active, "sample": sample,
    })


@router.post("/member/subscription/request")
async def member_subscription_request(
    plan: str = Form("monthly"),
    custom_days: int = Form(30),
    payment_reference: str = Form(""),
    payment_method: str = Form("bank"),
    evidence: UploadFile = File(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if getattr(user, "is_sample_account", False):
        raise HTTPException(
            403,
            "Sample members cannot subscribe. Please register as a full member."
        )
    settings = _settings(session)
    plan = (plan or "monthly").lower()
    method = (payment_method or "bank").lower()
    if method not in ("bank", "card"):
        method = "bank"
    if plan == "monthly":
        if method == "card" and getattr(settings, "card_enabled", True):
            amount, days = float(getattr(settings, "card_monthly_price", None) or settings.monthly_price), 30
            currency = getattr(settings, "card_currency", None) or "USD"
        else:
            amount, days = settings.monthly_price, 30
            currency = settings.currency or "NGN"
    elif plan == "annual":
        if method == "card" and getattr(settings, "card_enabled", True):
            amount, days = float(getattr(settings, "card_annual_price", None) or settings.annual_price), 365
            currency = getattr(settings, "card_currency", None) or "USD"
        else:
            amount, days = settings.annual_price, 365
            currency = settings.currency or "NGN"
    else:
        days = max(settings.custom_min_days or 7, int(custom_days or 30))
        if method == "card" and getattr(settings, "card_enabled", True):
            base = float(getattr(settings, "card_monthly_price", None) or 5.0)
            amount = round(base * (days / 30.0), 2)
            currency = getattr(settings, "card_currency", None) or "USD"
        else:
            amount = round(settings.monthly_price * (days / 30.0), 2)
            currency = settings.currency or "NGN"
        plan = "custom"
    ref = payment_reference.strip() or (
        "SUB-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    )
    evidence_path = None
    if evidence and evidence.filename:
        ext = (evidence.filename.rsplit(".", 1)[-1] or "jpg").lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "pdf"):
            ext = "jpg"
        upload_dir = FsPath("app/static/uploads/payment_evidence")
        upload_dir.mkdir(parents=True, exist_ok=True)
        fname = f"sub_{user.id}_{secrets.token_hex(6)}.{ext}"
        dest = upload_dir / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(evidence.file, f)
        evidence_path = f"/static/uploads/payment_evidence/{fname}"
    sub_row = MemberSubscription(
        user_id=user.id,
        member_id=user.member_id,
        plan=plan,
        amount=amount,
        currency=currency,
        duration_days=days,
        status="pending",
        payment_reference=ref,
        payment_method=method,
        evidence_image=evidence_path,
        note=("Card/international payment" if method == "card" else "Bank transfer"),
    )
    session.add(sub_row)
    session.commit()
    return RedirectResponse("/member/subscription?submitted=1", status_code=303)


@router.get("/admin/subscriptions", response_class=HTMLResponse)
async def admin_subscriptions_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    expire_due_subscriptions(session)
    settings = _settings(session)
    rows = list(session.exec(
        select(MemberSubscription).order_by(MemberSubscription.created_at.desc()).limit(150)
    ).all())
    data = []
    for s in rows:
        u = session.get(User, s.user_id)
        data.append({"s": s, "user": u})
    return templates.TemplateResponse("subscriptions/admin.html", {
        "request": request, "user": user, "settings": settings, "rows": data,
    })


@router.post("/admin/subscriptions/settings")
async def admin_subscription_settings(
    title: str = Form(...),
    currency: str = Form("NGN"),
    monthly_price: float = Form(1500),
    annual_price: float = Form(15000),
    custom_min_days: int = Form(7),
    instructions: str = Form(""),
    bank_name: str = Form(""),
    account_name: str = Form(""),
    account_number: str = Form(""),
    other_details: str = Form(""),
    card_enabled: str = Form("no"),
    card_currency: str = Form("USD"),
    card_monthly_price: float = Form(5),
    card_annual_price: float = Form(50),
    card_instructions: str = Form(""),
    card_payment_link: str = Form(""),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    s = _settings(session)
    s.title = title.strip()
    s.currency = currency.strip() or "NGN"
    s.monthly_price = float(monthly_price)
    s.annual_price = float(annual_price)
    s.custom_min_days = int(custom_min_days or 7)
    s.instructions = instructions.strip() or None
    s.bank_name = bank_name.strip() or None
    s.account_name = account_name.strip() or None
    s.account_number = account_number.strip() or None
    s.other_details = other_details.strip() or None
    s.card_enabled = card_enabled == "yes"
    s.card_currency = card_currency.strip() or "USD"
    s.card_monthly_price = float(card_monthly_price or 5)
    s.card_annual_price = float(card_annual_price or 50)
    s.card_instructions = card_instructions.strip() or None
    s.card_payment_link = card_payment_link.strip() or None
    from datetime import datetime
    s.updated_at = datetime.utcnow()
    session.add(s)
    session.commit()
    return RedirectResponse("/admin/subscriptions", status_code=303)



@router.post("/admin/subscriptions/{sub_id}/confirm")
async def admin_confirm_subscription(
    sub_id: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    sub = session.get(MemberSubscription, sub_id)
    if not sub:
        raise HTTPException(404)
    now = datetime.utcnow()
    sub.status = "active"
    sub.starts_at = now
    sub.ends_at = now + timedelta(days=sub.duration_days or 30)
    sub.confirmed_at = now
    sub.confirmed_by = user.id
    session.add(sub)
    # Reactivate member
    u = session.get(User, sub.user_id)
    if u:
        u.is_active = True
        session.add(u)
        if u.member_id:
            mem = session.get(ChurchMember, u.member_id)
            if mem:
                mem.approval_status = "approved"
                session.add(mem)
        try:
            from app.referral_logic import apply_referral_bonus_on_confirm
            apply_referral_bonus_on_confirm(session, sub, u)
        except Exception as _rb:
            print("referral bonus:", _rb)
    session.commit()
    return RedirectResponse("/admin/subscriptions", status_code=303)


@router.post("/admin/subscriptions/{sub_id}/reject")
async def admin_reject_subscription(
    sub_id: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    sub = session.get(MemberSubscription, sub_id)
    if not sub:
        raise HTTPException(404)
    sub.status = "rejected"
    session.add(sub)
    session.commit()
    return RedirectResponse("/admin/subscriptions", status_code=303)
