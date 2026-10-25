"""Referral / promo reward helpers for Churchgate members."""
from __future__ import annotations
import secrets
import string
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

CASHOUT_THRESHOLD = 50
BASE_PAYOUT_NGN = 3000.0
PER_EXTRA_NGN = BASE_PAYOUT_NGN / CASHOUT_THRESHOLD
NETWORK_PRIZE_THRESHOLD = 20
NETWORK_PRIZE_NGN = 3000.0
REFERRAL_FREE_MONTHS = 3
PAYOUT_DAY = 30


def promo_enabled(session: Session) -> bool:
    from app.models import AppConfig
    row = session.exec(select(AppConfig).where(AppConfig.key == "promo_enabled")).first()
    if not row or row.value is None:
        return True
    return str(row.value).strip().lower() in ("1", "true", "yes", "on")


def set_promo_enabled(session: Session, enabled: bool) -> None:
    from app.models import AppConfig
    row = session.exec(select(AppConfig).where(AppConfig.key == "promo_enabled")).first()
    if not row:
        row = AppConfig(key="promo_enabled", value="true" if enabled else "false")
    else:
        row.value = "true" if enabled else "false"
        row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()


def generate_promo_code(session: Session, full_name: str = "") -> str:
    from app.models import User
    for _ in range(40):
        body = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        code = f"KS-{body}"
        if not session.exec(select(User).where(User.promo_code == code)).first():
            return code
    return f"KS-{secrets.token_hex(4).upper()}"


def ensure_user_promo_code(session: Session, user) -> str:
    if getattr(user, "promo_code", None):
        return user.promo_code
    code = generate_promo_code(session, getattr(user, "full_name", "") or "")
    user.promo_code = code
    session.add(user)
    session.commit()
    session.refresh(user)
    return code


def resolve_referrer(session: Session, promo_code: str):
    from app.models import User
    if not promo_code or not promo_enabled(session):
        return None
    code = promo_code.strip().upper()
    return session.exec(select(User).where(User.promo_code == code)).first()


def is_active_paid_subscriber(session: Session, user_id: int) -> bool:
    from app.models import MemberSubscription
    now = datetime.utcnow()
    for s in session.exec(
        select(MemberSubscription).where(
            MemberSubscription.user_id == user_id,
            MemberSubscription.status == "active",
        )
    ).all():
        if (getattr(s, "plan", None) or "").lower() == "welcome":
            continue
        if s.ends_at and s.ends_at <= now:
            continue
        return True
    return False


def _referral_baseline_at(session: Session, referrer_user_id: int) -> Optional[datetime]:
    """After a cashout is submitted, only count referrals created after that moment."""
    from app.models import ReferralCashout
    last = session.exec(
        select(ReferralCashout).where(
            ReferralCashout.user_id == referrer_user_id,
            ReferralCashout.status.in_(["pending", "approved", "paid"]),
        ).order_by(ReferralCashout.created_at.desc())
    ).first()
    return last.created_at if last else None


def direct_referral_count(session: Session, user_id: int) -> int:
    from app.models import User
    return len(list(session.exec(select(User).where(User.referred_by_user_id == user_id)).all()))


def count_referrals(session: Session, referrer_user_id: int) -> Dict[str, Any]:
    from app.models import User, ChurchMember
    baseline = _referral_baseline_at(session, referrer_user_id)
    referred = list(session.exec(
        select(User).where(User.referred_by_user_id == referrer_user_id)
    ).all())
    # Cycle count: only users who joined after last cashout request
    cycle = []
    for u in referred:
        if baseline and u.created_at and u.created_at <= baseline:
            continue
        cycle.append(u)
    rows = []
    active_n = 0
    network_qualifiers = 0
    for u in cycle:
        active = is_active_paid_subscriber(session, u.id)
        if active:
            active_n += 1
        their_refs = direct_referral_count(session, u.id)
        if their_refs >= 1:
            network_qualifiers += 1
        mem = session.get(ChurchMember, u.member_id) if u.member_id else None
        rows.append({
            "user_id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "joined_at": u.created_at,
            "is_active_subscriber": active,
            "their_referrals": their_refs,
            "network_qualifier": their_refs >= 1,
            "member_status": getattr(mem, "approval_status", None) if mem else None,
        })
    earnings = compute_earnings(active_n)
    pct = min(100, round(100 * active_n / CASHOUT_THRESHOLD)) if CASHOUT_THRESHOLD else 0
    return {
        "total_registered": len(cycle),
        "active_subscribers": active_n,
        "network_qualifiers": network_qualifiers,
        "network_prize_ready": network_qualifiers >= NETWORK_PRIZE_THRESHOLD,
        "network_threshold": NETWORK_PRIZE_THRESHOLD,
        "network_prize_ngn": NETWORK_PRIZE_NGN,
        "rows": rows,
        "earnings_ngn": earnings,
        "cashout_ready": active_n >= CASHOUT_THRESHOLD,
        "threshold": CASHOUT_THRESHOLD,
        "base_payout": BASE_PAYOUT_NGN,
        "progress_pct": pct,
        "lifetime_registered": len(referred),
        "promo_on": promo_enabled(session),
    }


def compute_earnings(active_count: int) -> float:
    if active_count < CASHOUT_THRESHOLD:
        return round(active_count * PER_EXTRA_NGN, 2)
    return round(BASE_PAYOUT_NGN + (active_count - CASHOUT_THRESHOLD) * PER_EXTRA_NGN, 2)


def apply_referral_bonus_on_confirm(session: Session, sub, user) -> None:
    from datetime import timedelta
    if not promo_enabled(session):
        return
    if not getattr(user, "referred_by_user_id", None):
        return
    if getattr(user, "referral_bonus_applied", False):
        return
    if (getattr(sub, "plan", None) or "").lower() == "welcome":
        return
    bonus_days = REFERRAL_FREE_MONTHS * 30
    if sub.ends_at:
        sub.ends_at = sub.ends_at + timedelta(days=bonus_days)
    else:
        sub.ends_at = datetime.utcnow() + timedelta(days=(sub.duration_days or 30) + bonus_days)
    sub.duration_days = (sub.duration_days or 30) + bonus_days
    sub.note = ((sub.note or "") + f" | +{REFERRAL_FREE_MONTHS} months referral promo").strip(" |")
    user.referral_bonus_applied = True
    session.add(sub)
    session.add(user)
