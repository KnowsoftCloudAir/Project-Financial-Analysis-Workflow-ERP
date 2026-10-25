"""Member referral rewards + admin payout management."""
from pathlib import Path
from datetime import datetime, date
import secrets
import shutil
from fastapi import APIRouter, Depends, Request, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserRole, ReferralCashout
from app.auth import require_user, require_roles
from app.referral_logic import (
    ensure_user_promo_code, count_referrals,
    CASHOUT_THRESHOLD, BASE_PAYOUT_NGN, PAYOUT_DAY, PER_EXTRA_NGN,
    promo_enabled, set_promo_enabled,
)

router = APIRouter(tags=["referrals"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
UPLOAD = Path("app/static/uploads/identity")
UPLOAD.mkdir(parents=True, exist_ok=True)


@router.get("/member/rewards", response_class=HTMLResponse)
async def member_rewards_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    code = ensure_user_promo_code(session, user)
    stats = count_referrals(session, user.id)
    cashouts = list(session.exec(
        select(ReferralCashout).where(ReferralCashout.user_id == user.id)
        .order_by(ReferralCashout.created_at.desc())
    ).all())
    pending = next((c for c in cashouts if c.status in ("pending", "approved")), None)
    share_url = str(request.base_url).rstrip("/") + f"/join?promo={code}"
    today = date.today()
    is_payout_day = today.day >= PAYOUT_DAY  # 30th (or 31st months: allow 30+)
    # Feb: day 28/29 treated as month-end if needed
    if today.month == 2 and today.day >= 28:
        is_payout_day = True
    return templates.TemplateResponse("referrals/member_rewards.html", {
        "request": request,
        "user": user,
        "promo_code": code,
        "share_url": share_url,
        "stats": stats,
        "cashouts": cashouts,
        "pending_cashout": pending,
        "threshold": CASHOUT_THRESHOLD,
        "base_payout": BASE_PAYOUT_NGN,
        "per_extra": PER_EXTRA_NGN,
        "payout_day": PAYOUT_DAY,
        "today": today,
        "is_payout_day": is_payout_day,
        "promo_on": promo_enabled(session),
    })


@router.post("/member/rewards/cashout")
async def member_cashout_request(
    account_name: str = Form(""),
    account_number: str = Form(""),
    bank_name: str = Form(""),
    identity_evidence: UploadFile = File(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not promo_enabled(session):
        raise HTTPException(403, "Promo programme is currently turned off.")
    today = date.today()
    ok_day = today.day >= PAYOUT_DAY or (today.month == 2 and today.day >= 28)
    if not ok_day:
        raise HTTPException(400, f"Cashout requests open on the {PAYOUT_DAY}th of the month (month-end).")
    stats = count_referrals(session, user.id)
    if not stats["cashout_ready"]:
        raise HTTPException(400, f"Need at least {CASHOUT_THRESHOLD} active subscribers in this cycle.")
    existing = session.exec(
        select(ReferralCashout).where(
            ReferralCashout.user_id == user.id,
            ReferralCashout.status.in_(["pending", "approved"]),
        )
    ).first()
    if existing:
        raise HTTPException(400, "You already have a cashout in progress.")
    if not identity_evidence or not identity_evidence.filename:
        raise HTTPException(400, "Identity evidence (ID photo) is required.")
    ext = (identity_evidence.filename.rsplit(".", 1)[-1] or "jpg").lower()
    if ext not in ("jpg", "jpeg", "png", "webp", "pdf"):
        ext = "jpg"
    fname = f"id_{user.id}_{secrets.token_hex(6)}.{ext}"
    dest = UPLOAD / fname
    with dest.open("wb") as f:
        shutil.copyfileobj(identity_evidence.file, f)
    evidence_path = f"/static/uploads/identity/{fname}"
    row = ReferralCashout(
        user_id=user.id,
        active_count=stats["active_subscribers"],
        amount_ngn=stats["earnings_ngn"],
        status="pending",
        account_name=account_name.strip() or None,
        account_number=account_number.strip() or None,
        bank_name=bank_name.strip() or None,
        period_month=today.strftime("%Y-%m"),
        identity_evidence=evidence_path,
    )
    session.add(row)
    session.commit()
    # Counting for rewards resets automatically: new cycle = users joined after this cashout created_at
    return RedirectResponse("/member/rewards?cashout=1", status_code=303)


@router.get("/admin/referrals", response_class=HTMLResponse)
async def admin_referrals_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    from app.referral_logic import is_active_paid_subscriber
    all_users = list(session.exec(select(User).where(User.promo_code != None)).all())  # noqa
    leaders = []
    for u in all_users:
        st = count_referrals(session, u.id)
        if st["lifetime_registered"] == 0 and st["active_subscribers"] == 0:
            continue
        leaders.append({"user": u, "stats": st})
    leaders.sort(key=lambda x: x["stats"]["active_subscribers"], reverse=True)
    cashouts = list(session.exec(
        select(ReferralCashout).order_by(ReferralCashout.created_at.desc()).limit(100)
    ).all())
    cashout_rows = [{"c": c, "user": session.get(User, c.user_id)} for c in cashouts]
    referred = list(session.exec(
        select(User).where(User.referred_by_user_id != None).order_by(User.created_at.desc()).limit(80)  # noqa
    ).all())
    ref_rows = []
    for u in referred:
        ref = session.get(User, u.referred_by_user_id) if u.referred_by_user_id else None
        ref_rows.append({"user": u, "referrer": ref, "active": is_active_paid_subscriber(session, u.id)})
    return templates.TemplateResponse("referrals/admin_referrals.html", {
        "request": request, "user": user, "leaders": leaders,
        "cashout_rows": cashout_rows, "ref_rows": ref_rows,
        "threshold": CASHOUT_THRESHOLD, "base_payout": BASE_PAYOUT_NGN,
        "payout_day": PAYOUT_DAY, "promo_on": promo_enabled(session),
    })


@router.post("/admin/referrals/promo-toggle")
async def admin_promo_toggle(
    enabled: str = Form("on"),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    set_promo_enabled(session, enabled == "on")
    return RedirectResponse("/admin/referrals?promo=1", status_code=303)


@router.post("/admin/referrals/cashout/{cashout_id}/approve")
async def admin_approve_cashout(cashout_id: int, user: User = Depends(require_roles(UserRole.general_admin)), session: Session = Depends(get_session)):
    row = session.get(ReferralCashout, cashout_id)
    if not row:
        raise HTTPException(404)
    row.status = "approved"
    row.processed_by = user.id
    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return RedirectResponse("/admin/referrals", status_code=303)


@router.post("/admin/referrals/cashout/{cashout_id}/pay")
async def admin_pay_cashout(cashout_id: int, user: User = Depends(require_roles(UserRole.general_admin)), session: Session = Depends(get_session)):
    row = session.get(ReferralCashout, cashout_id)
    if not row:
        raise HTTPException(404)
    row.status = "paid"
    row.processed_by = user.id
    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return RedirectResponse("/admin/referrals", status_code=303)


@router.post("/admin/referrals/cashout/{cashout_id}/reject")
async def admin_reject_cashout(cashout_id: int, user: User = Depends(require_roles(UserRole.general_admin)), session: Session = Depends(get_session)):
    row = session.get(ReferralCashout, cashout_id)
    if not row:
        raise HTTPException(404)
    row.status = "rejected"
    row.processed_by = user.id
    row.processed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return RedirectResponse("/admin/referrals", status_code=303)
