"""Activity footprint logging for General Admin reports."""
from typing import Optional
from fastapi import Request
from sqlmodel import Session
from app.models import ActivityLog, User


def client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if xf:
        return xf.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def location_from_request(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None
    parts = []
    # CDN / platform headers when present
    country = (
        request.headers.get("cf-ipcountry")
        or request.headers.get("x-vercel-ip-country")
        or request.headers.get("x-country-code")
        or request.headers.get("cloudfront-viewer-country")
    )
    city = (
        request.headers.get("cf-ipcity")
        or request.headers.get("x-vercel-ip-city")
        or request.headers.get("x-city")
    )
    region = request.headers.get("x-vercel-ip-country-region") or request.headers.get("cf-region")
    if city:
        parts.append(city)
    if region:
        parts.append(region)
    if country:
        parts.append(country)
    if parts:
        return ", ".join(parts)
    # Render and many hosts do not send geo headers — fall back to IP label
    ip = client_ip(request)
    if ip and ip not in ("127.0.0.1", "::1"):
        return f"IP region unknown ({ip})"
    return "Local / unknown"


def log_activity(
    session: Session,
    *,
    user: Optional[User] = None,
    action: str,
    detail: str = "",
    request: Optional[Request] = None,
    location_hint: Optional[str] = None,
) -> None:
    try:
        ip = client_ip(request) if request else None
        ua = (request.headers.get("user-agent") if request else None) or None
        path = str(request.url.path) if request else None
        loc = location_hint or location_from_request(request)
        name = None
        email = None
        uid = None
        church_id = None
        if user:
            uid = user.id
            email = user.email
            name = (user.full_name or "").strip() or user.email
            church_id = getattr(user, "church_id", None)
        session.add(ActivityLog(
            church_id=church_id,
            user_id=uid,
            email=email,
            full_name=name,
            action=(action or "event")[:64],
            detail=(detail or "")[:500],
            ip_address=ip,
            user_agent=(ua or "")[:300] if ua else None,
            location_hint=(loc or "")[:200] if loc else None,
            path=path,
        ))
        session.commit()
    except Exception as e:
        print("activity log error:", e)
        try:
            session.rollback()
        except Exception:
            pass
