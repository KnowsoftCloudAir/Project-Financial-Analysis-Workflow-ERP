"""Admin social video embeds + Facebook Page sync + member muted autoplay feed."""
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote, urlencode
import json
import time
import re
import urllib.request
import urllib.error

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, SocialStreamLink, AppConfig
from app.auth import require_user, role_val

router = APIRouter(tags=["social-stream"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

FB_PAGE_ID_KEY = "social_fb_page_id"
FB_PAGE_TOKEN_KEY = "social_fb_page_token"
GRAPH = "https://graph.facebook.com/v21.0"


def _is_admin(user: User) -> bool:
    rv = (role_val(user.role) if hasattr(user, "role") else str(getattr(user, "role", ""))).lower()
    return rv == "general_admin" or "general" in rv or "admin" in rv


def _cfg_get(session: Session, key: str) -> Optional[str]:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    return (row.value if row else None) or None


def _cfg_set(session: Session, key: str, value: str) -> None:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    if not row:
        row = AppConfig(key=key, value=value, updated_at=datetime.utcnow())
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
    session.add(row)


def extract_youtube_channel_id(url: str) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    m = re.search(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})", u)
    if m:
        return m.group(1)
    if u.startswith("ytchan:") or u.startswith("channel:"):
        cid = u.split(":", 1)[1].strip()
        if cid.startswith("UC") and len(cid) >= 22:
            return cid
    m = re.search(r"[?&]channel=(UC[A-Za-z0-9_-]{20,})", u)
    if m:
        return m.group(1)
    return None


def resolve_youtube_handle_to_channel_id(handle: str) -> Optional[str]:
    handle = (handle or "").lstrip("@").strip()
    if not handle or not re.match(r"^[A-Za-z0-9._-]+$", handle):
        return None
    page = f"https://www.youtube.com/@{handle}"
    try:
        req = urllib.request.Request(
            page,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ChurchgateSocial/1.3)",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        for pat in (
            r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
            r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
            r"channel/(UC[A-Za-z0-9_-]{20,})",
        ):
            m = re.search(pat, html)
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


# channel_id -> (ts, video_id, is_live)
_channel_dock_cache = {}
_CHANNEL_DOCK_TTL = 120


def _yt_fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _unique_video_ids(html: str) -> List[str]:
    ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    if not ids:
        ids = re.findall(r"watch\?v=([A-Za-z0-9_-]{11})", html)
    seen = set()
    out: List[str] = []
    for v in ids:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def resolve_channel_dock(channel_id: str) -> Tuple[Optional[str], bool]:
    """Return (video_id, is_live).

    Prefer current live broadcast; if none, latest available video on channel.
    """
    cid = (channel_id or "").strip()
    if not cid.startswith("UC"):
        return None, False

    now = time.time()
    cached = _channel_dock_cache.get(cid)
    if cached and (now - cached[0]) < _CHANNEL_DOCK_TTL:
        return cached[1], cached[2]

    video_id: Optional[str] = None
    is_live = False
    try:
        live_html = _yt_fetch(f"https://www.youtube.com/channel/{cid}/live")
        live_match = re.search(
            r'"videoId":"([A-Za-z0-9_-]{11})"([\s\S]{0,400})"isLive(?:Now|Content)?"\s*:\s*true',
            live_html,
        )
        if not live_match:
            live_match = re.search(
                r'"isLive(?:Now|Content)?"\s*:\s*true([\s\S]{0,400})"videoId":"([A-Za-z0-9_-]{11})"',
                live_html,
            )
            if live_match:
                video_id = live_match.group(2)
                is_live = True
        else:
            video_id = live_match.group(1)
            is_live = True
        if not video_id and re.search(r'"isLive(?:Now|Content)?"\s*:\s*true', live_html):
            vids = _unique_video_ids(live_html)
            if vids:
                video_id = vids[0]
                is_live = True
        if not video_id:
            vids = _unique_video_ids(live_html)
            if vids:
                video_id = vids[0]
                is_live = False
    except Exception:
        pass

    if not video_id:
        try:
            vids_html = _yt_fetch(f"https://www.youtube.com/channel/{cid}/videos")
            vids = _unique_video_ids(vids_html)
            if vids:
                video_id = vids[0]
                is_live = False
        except Exception:
            pass

    _channel_dock_cache[cid] = (now, video_id, is_live)
    return video_id, is_live


def is_channel_live_embed(embed_url: Optional[str]) -> bool:
    if not embed_url:
        return False
    return "embed/live_stream" in embed_url and "channel=" in embed_url


def channel_live_embed(channel_id: str, muted: bool = True) -> str:
    """Dock to current live video, else latest video on channel."""
    cid = (channel_id or "").strip()
    mute = "1" if muted else "0"
    vid, _is_live = resolve_channel_dock(cid)
    if vid:
        return (
            f"https://www.youtube.com/embed/{vid}"
            f"?autoplay=1&mute={mute}&playsinline=1&rel=0&modestbranding=1&enablejsapi=1"
        )
    return (
        "https://www.youtube.com/embed/live_stream?channel="
        + quote(cid, safe="")
        + f"&autoplay=1&mute={mute}&playsinline=1&rel=0&modestbranding=1"
    )


def build_embed_url(platform: str, source_url: str) -> Optional[str]:
    """Build iframe embed. Channel /live docks to current live or latest video."""
    if not source_url:
        return None
    url = source_url.strip()
    p = (platform or "").lower().strip()
    low = url.lower()

    if p == "facebook":
        return (
            "https://www.facebook.com/plugins/video.php?href="
            + quote(url, safe="")
            + "&show_text=false&width=auto&allowfullscreen=true&autoplay=true"
        )

    if p == "tiktok":
        m = re.search(r"tiktok\.com/.*/video/(\d+)", url)
        if not m:
            m = re.search(r"tiktok\.com/.*?(\d{15,})", url)
        if m:
            return "https://www.tiktok.com/embed/v2/" + m.group(1)
        return None

    if p == "instagram":
        m = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
        if m:
            code = m.group(1)
            kind = "reel" if "/reel/" in url else "p"
            return "https://www.instagram.com/" + kind + "/" + code + "/embed"
        return None

    if p == "youtube" or "youtube.com" in low or "youtu.be" in low:
        cid = extract_youtube_channel_id(url)
        if cid:
            return channel_live_embed(cid)

        handle = re.search(r"youtube\.com/@([A-Za-z0-9._-]+)", url)
        if handle:
            resolved = resolve_youtube_handle_to_channel_id(handle.group(1))
            if resolved:
                return channel_live_embed(resolved)
            return None

        if re.search(r"youtube\.com/(?:c|user)/[A-Za-z0-9._-]+", url) and "/live" in low:
            return None

        m = re.search(
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/"
            r"|youtube\.com/live/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
            url,
        )
        if not m:
            m = re.search(r"(?:live/|v=|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
        if m:
            vid = m.group(1)
            return (
                "https://www.youtube.com/embed/"
                + vid
                + "?autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1&enablejsapi=1"
            )
        return None

    return None



def _graph_get(path: str, params: Dict[str, str]) -> Dict[str, Any]:
    qs = urlencode(params)
    url = f"{GRAPH}/{path.lstrip('?')}?{qs}" if path.startswith("?") else f"{GRAPH}/{path.lstrip('/')}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "ChurchgateSocial/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            msg = (err.get("error") or {}).get("message") or body
            code = (err.get("error") or {}).get("code")
            sub = (err.get("error") or {}).get("error_subcode")
            detail = f"{msg}"
            if code is not None:
                detail += f" (code {code}"
                if sub is not None:
                    detail += f"/{sub}"
                detail += ")"
        except Exception:
            detail = body[:300] or str(e)
        raise HTTPException(400, detail[:240])


def _validate_page_token(page_id: str, token: str) -> Tuple[str, str]:
    """Confirm token works; return (resolved_page_id, page_name)."""
    page_id = (page_id or "").strip()
    token = (token or "").strip()
    if not page_id or not token:
        raise HTTPException(400, "Missing Page ID or token")

    # 1) Token debug / identity
    try:
        me = _graph_get("me", {"fields": "id,name", "access_token": token})
    except HTTPException as e:
        raise HTTPException(
            400,
            "Token rejected by Facebook. Generate a Page access token in Graph API Explorer "
            f"(not only a User token). Detail: {e.detail}",
        )

    token_id = str(me.get("id") or "")
    token_name = str(me.get("name") or "")

    # If token is a Page token, /me returns the Page
    if token_id == page_id:
        return page_id, token_name or page_id

    # 2) Try reading the page with this token
    try:
        page = _graph_get(page_id, {"fields": "id,name", "access_token": token})
        return str(page.get("id") or page_id), str(page.get("name") or token_name or page_id)
    except HTTPException:
        pass

    # 3) User token path: list pages and pick matching id
    try:
        accounts = _graph_get("me/accounts", {"fields": "id,name,access_token", "access_token": token})
        for acc in accounts.get("data") or []:
            if str(acc.get("id")) == page_id and acc.get("access_token"):
                # Prefer the page token from accounts
                return page_id, str(acc.get("name") or page_id)
    except HTTPException:
        pass

    raise HTTPException(
        400,
        "Facebook rejected Page ID + token. Common causes: (1) ID is a personal profile not a Page, "
        "(2) token is a short User token without Page permissions, (3) app not connected to the Page. "
        f"Token identity id={token_id}. Open Graph API Explorer → me/accounts and use that Page access_token.",
    )


def _resolve_page_token_if_user(page_id: str, token: str) -> str:
    """If user token, exchange for page token via me/accounts."""
    try:
        accounts = _graph_get(
            "me/accounts",
            {"fields": "id,name,access_token", "access_token": token},
        )
        for acc in accounts.get("data") or []:
            if str(acc.get("id")) == str(page_id) and acc.get("access_token"):
                return str(acc["access_token"])
    except HTTPException:
        pass
    return token


def sync_facebook_page_videos(session: Session, page_id: str, token: str, limit: int = 30) -> int:
    page_id = (page_id or "").strip()
    token = (token or "").strip()
    _validate_page_token(page_id, token)
    token = _resolve_page_token_if_user(page_id, token)

    items: List[Dict[str, Any]] = []
    last_err = None

    # Try several endpoints — FB returns 400 when field/permission mismatch
    attempts = [
        (f"{page_id}/videos", {"fields": "id,title,description,permalink_url,created_time", "limit": str(limit)}),
        (f"{page_id}/videos", {"fields": "id,description,permalink_url,created_time", "limit": str(limit)}),
        (f"{page_id}/published_posts", {
            "fields": "id,message,permalink_url,created_time,attachments{media_type,url,target,media,subattachments}",
            "limit": str(limit),
        }),
        (f"{page_id}/posts", {
            "fields": "id,message,permalink_url,created_time,attachments{media_type,url,target}",
            "limit": str(limit),
        }),
        (f"{page_id}/feed", {
            "fields": "id,message,permalink_url,created_time,attachments{media_type,url,target}",
            "limit": str(limit),
        }),
    ]

    for path, fields in attempts:
        params = dict(fields)
        params["access_token"] = token
        try:
            data = _graph_get(path, params)
            batch = data.get("data") or []
            if batch:
                items = batch
                break
            # empty but success — keep trying other endpoints
            if not items:
                items = batch
        except HTTPException as e:
            last_err = e
            continue

    if not items and last_err is not None:
        raise last_err

    existing_urls = {
        (r.source_url or "").strip()
        for r in session.exec(select(SocialStreamLink)).all()
    }
    added = 0

    for it in items:
        permalink = (it.get("permalink_url") or "").strip()
        vid = str(it.get("id") or "")
        # posts ids look like PAGEID_POSTID
        if not permalink and vid:
            if "_" in vid:
                permalink = f"https://www.facebook.com/{vid.replace('_', '/posts/')}"
            else:
                permalink = f"https://www.facebook.com/{page_id}/videos/{vid}/"

        # Prefer video attachments from posts
        atts = it.get("attachments") or {}
        att_list = atts.get("data") if isinstance(atts, dict) else None
        media_type = ""
        if att_list:
            media_type = str((att_list[0] or {}).get("media_type") or "").lower()
            target = (att_list[0] or {}).get("target") or {}
            if isinstance(target, dict) and target.get("url") and not permalink:
                permalink = str(target.get("url"))

        # If from posts/feed and clearly not video, skip
        if media_type and media_type not in ("video", "video_inline", "animated_image_video"):
            # still allow if permalink contains /videos/
            if "/videos/" not in (permalink or "") and "video" not in media_type:
                continue

        if not permalink or permalink in existing_urls:
            continue

        title = (it.get("title") or it.get("message") or "Facebook video").strip()
        title = re.sub(r"\s+", " ", title)[:200]
        desc = (it.get("description") or it.get("message") or "Synced from Facebook Page").strip()[:500]
        embed = build_embed_url("facebook", permalink)
        row = SocialStreamLink(
            platform="facebook",
            title=title or "Facebook video",
            source_url=permalink[:800],
            embed_url=(embed[:900] if embed else None),
            description=desc,
            is_active=True,
            created_by=None,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        existing_urls.add(permalink)
        added += 1

    session.commit()
    return added


@router.get("/admin/social-stream", response_class=HTMLResponse)
async def admin_social_stream(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    links = list(
        session.exec(
            select(SocialStreamLink).order_by(SocialStreamLink.sort_order, SocialStreamLink.id.desc())
        ).all()
    )
    return templates.TemplateResponse(
        "admin/social_stream.html",
        {
            "request": request,
            "user": user,
            "links": links,
            "ok": request.query_params.get("ok"),
            "err": request.query_params.get("err"),
            "fb_page_id": _cfg_get(session, FB_PAGE_ID_KEY) or "",
            "has_token": bool(_cfg_get(session, FB_PAGE_TOKEN_KEY)),
            "synced": request.query_params.get("synced"),
        },
    )


@router.post("/admin/social-stream/facebook-page")
async def admin_save_facebook_page(
    page_id: str = Form(""),
    page_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    page_id = (page_id or "").strip()
    page_token = (page_token or "").strip()
    # Accept full profile URL and extract id=
    m = re.search(r"[?&]id=(\d+)", page_id)
    if m:
        page_id = m.group(1)
    m2 = re.search(r"facebook\.com/(\d{8,})", page_id)
    if m2 and not page_id.isdigit():
        page_id = m2.group(1)
    if page_id:
        _cfg_set(session, FB_PAGE_ID_KEY, page_id)
    if page_token:
        _cfg_set(session, FB_PAGE_TOKEN_KEY, page_token)
    session.commit()
    return RedirectResponse("/admin/social-stream?ok=fb_saved", status_code=303)


@router.post("/admin/social-stream/sync-facebook")
async def admin_sync_facebook(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    page_id = _cfg_get(session, FB_PAGE_ID_KEY)
    token = _cfg_get(session, FB_PAGE_TOKEN_KEY)
    if not page_id or not token:
        return RedirectResponse("/admin/social-stream?err=fb_config", status_code=303)
    try:
        n = sync_facebook_page_videos(session, page_id, token, limit=30)
    except HTTPException as e:
        return RedirectResponse(
            "/admin/social-stream?err=" + quote(str(e.detail)[:180]),
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            "/admin/social-stream?err=" + quote(str(e)[:180]),
            status_code=303,
        )
    return RedirectResponse(f"/admin/social-stream?ok=synced&synced={n}", status_code=303)


@router.post("/admin/social-stream/add")
async def admin_social_stream_add(
    platform: str = Form(...),
    title: str = Form(""),
    source_url: str = Form(...),
    description: str = Form(""),
    category: str = Form("tv"),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    platform = (platform or "").lower().strip()
    if platform not in ("facebook", "tiktok", "instagram", "youtube"):
        return RedirectResponse("/admin/social-stream?err=platform", status_code=303)
    source_url = (source_url or "").strip()
    if not source_url.startswith("http"):
        return RedirectResponse("/admin/social-stream?err=url", status_code=303)
    embed = build_embed_url(platform, source_url)
    cat = (category or "tv").strip().lower()
    if cat not in ("tv","movies","news","games","ministration","others"):
        cat = "tv"
    ycid = extract_youtube_channel_id(source_url)
    if not ycid and embed:
        ycid = extract_youtube_channel_id(embed)
    if platform == "youtube" and not embed:
        return RedirectResponse(
            "/admin/social-stream?err=yt_channel",
            status_code=303,
        )
    row = SocialStreamLink(
        platform=platform,
        title=(title or (platform.title() + " video")).strip()[:200],
        category=cat,
        source_url=source_url[:800],
        embed_url=(embed[:900] if embed else None),
        description=(description or "").strip()[:500] or None,
        youtube_channel_id=(ycid[:40] if ycid else None),
        is_active=True,
        created_by=getattr(user, "id", None),
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return RedirectResponse("/admin/social-stream?ok=1", status_code=303)


@router.post("/admin/social-stream/{link_id}/toggle")
async def admin_social_stream_toggle(
    link_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    row = session.get(SocialStreamLink, link_id)
    if not row:
        raise HTTPException(404)
    row.is_active = not bool(row.is_active)
    session.add(row)
    session.commit()
    return RedirectResponse("/admin/social-stream?ok=toggle", status_code=303)


@router.post("/admin/social-stream/{link_id}/delete")
async def admin_social_stream_delete(
    link_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    row = session.get(SocialStreamLink, link_id)
    if row:
        session.delete(row)
        session.commit()
    return RedirectResponse("/admin/social-stream?ok=del", status_code=303)





# Built-in library (all links provided by admin for restore after deploy)
STARTER_STREAM_LINKS = [('youtube', 'Enoch', 'https://youtu.be/wJkXjNbsD-Y', 'movies', 'Faith film'), ('youtube', 'Noah', 'https://youtu.be/KbZvD-Yd2a8', 'movies', 'Faith film'), ('youtube', 'The Passion of the Christ', 'https://youtu.be/FOfOqZIVmSY', 'movies', 'Faith film'), ('youtube', 'The Last Sin Easter', 'https://youtu.be/qC62QHN4Uzg', 'movies', 'Faith film'), ('youtube', 'Megiddo - The Omega Code', 'https://youtu.be/AnOz_ecu65s', 'movies', 'Faith film'), ('youtube', 'Encounter 1', 'https://youtu.be/kN4SK4cgopg', 'movies', 'Faith film'), ('youtube', "Pilgrim's Progress", 'https://youtu.be/XPB_GDg9qnk', 'movies', 'Faith film'), ('youtube', 'I Can Only Imagine', 'https://youtu.be/tpEbBMi_mO4', 'movies', 'Faith film'), ('youtube', 'Let Go and Let God', 'https://youtu.be/F8IPzpcuPGs', 'movies', 'Faith film'), ('youtube', 'Something the Lord Made', 'https://youtu.be/YsgL9etO52s', 'movies', 'Faith film'), ('youtube', 'Kenya TV Live', 'https://www.youtube.com/live/wd6e85PVwt0', 'tv', 'Kenya TV'), ('youtube', 'China TV Live', 'https://www.youtube.com/live/0i7n3r01L2U', 'tv', 'China Live'), ('youtube', 'Citizen TV Live (Kenya)', 'https://www.youtube.com/live/QR68tERO10g', 'tv', 'Kenya'), ('youtube', 'BBC News Live', 'https://www.youtube.com/live/sc21UUjyLaw', 'news', 'BBC'), ('youtube', 'Indian News Live', 'https://www.youtube.com/live/9kIboQPkkC0', 'news', 'India'), ('youtube', 'Sky News Live', 'https://www.youtube.com/live/xDWQ3LkccY8', 'news', 'SKY NEWS'), ('youtube', 'CBC News Live', 'https://www.youtube.com/live/5vfaDsMhCF4', 'news', 'CBC'), ('youtube', 'ABC News Live', 'https://www.youtube.com/live/vOTiJkg1voo', 'news', 'ABC News'), ('youtube', 'Euronews Live', 'https://www.youtube.com/live/pykpO5kQJ98', 'news', 'Euro News'), ('youtube', 'France TV Live', 'https://www.youtube.com/live/HvZt-nh9sGg', 'tv', 'France TV'), ('youtube', 'Al Jazeera Live', 'https://www.youtube.com/live/gCNeDWCI0vo', 'news', 'Al Jazeera'), ('youtube', 'CNN Live', 'https://www.youtube.com/live/GotlA1KKWoo', 'news', 'CNN'), ('youtube', 'Arise Live', 'https://www.youtube.com/live/Fy_03Aorpq8', 'news', 'Arise'), ('youtube', 'Africa TV Live', 'https://www.youtube.com/live/NQjabLGdP5g', 'tv', 'Africa TV'), ('youtube', 'TVC News Live', 'https://www.youtube.com/live/b-Yzp0l8cAM', 'news', 'TVC'), ('youtube', 'Joy TV Live', 'https://www.youtube.com/live/MHFpXY4d_LI', 'tv', 'Joy TV'), ('youtube', 'Channels TV Live', 'https://www.youtube.com/live/W8nThq62Vb4', 'news', 'Channels TV'), ('youtube', 'AIT News Live', 'https://www.youtube.com/live/9MC8X0TOGzo', 'news', 'AIT'), ('youtube', 'William Booth', 'https://youtu.be/9Mn2uYUsr04', 'ministration', 'Teaching'), ('youtube', 'Sinners in the Hands of an Angry God - Jonathan Edwards', 'https://youtu.be/TtHijgqceXo', 'ministration', 'Jonathan Edwards'), ('youtube', 'Rebecca Brown', 'https://youtu.be/9wEgQcvvmNc', 'ministration', 'Rebecca Brown'), ('youtube', 'He Came to Set the Captives Free', 'https://youtu.be/_sK4pgAcQj4', 'ministration', 'Rebecca Brown'), ('youtube', 'Watchman Nee - The Holy Spirit', 'https://youtu.be/vZL_cJZd5RE', 'ministration', 'Watchman Nee'), ('youtube', 'Watchman Nee - Spirit, Soul & Body (Chapter 1)', 'https://youtu.be/NKSoxghLHBk', 'ministration', 'Watchman Nee'), ('youtube', 'Billy Graham - The Real Meaning of the Cross', 'https://youtu.be/U89zkUZPd5w', 'ministration', 'Billy Graham'), ('youtube', 'John Wesley - The Almost Christian', 'https://www.youtube.com/watch?v=uGSkCCOgHso', 'ministration', 'John Wesley'), ('youtube', 'Charles H. Spurgeon - What Is Your Life?', 'https://www.youtube.com/watch?v=XwZVHqsoLXI', 'ministration', 'Spurgeon'), ('youtube', 'Charles H. Spurgeon - The Indwelling and Outflowing of the Holy Spirit', 'https://www.youtube.com/watch?v=UBlZCjRzB3E', 'ministration', 'Spurgeon'), ('youtube', 'Charles H. Spurgeon - The Secret Power in Prayer', 'https://www.youtube.com/watch?v=uMje1vYLjQM', 'ministration', 'Spurgeon'), ('youtube', 'Leonard Ravenhill - Pure Heart, Pure Church', 'https://www.youtube.com/watch?v=MnKUD0OGIPY', 'ministration', 'Ravenhill'), ('youtube', 'Leonard Ravenhill - No Man Is Greater Than His Prayer Life', 'https://www.youtube.com/watch?v=M20aQ7ODuuw', 'ministration', 'Ravenhill'), ('youtube', 'Kathryn Kuhlman - The Price for the Anointing', 'https://youtu.be/dTRYYypEyD8', 'ministration', 'Kathryn Kuhlman'), ('youtube', 'Kathryn Kuhlman - Dying to Self', 'https://youtu.be/ZnWqLkx79nc', 'ministration', 'Kathryn Kuhlman'), ('youtube', 'Kathryn Kuhlman - How to Talk to the Holy Spirit', 'https://www.youtube.com/watch?v=emrFx5tLjqU', 'ministration', 'Kathryn Kuhlman'), ('youtube', 'Dr. Arome Osayi', 'https://youtu.be/x6PmnWMJUos', 'ministration', 'Dr. Arome Osayi'), ('youtube', 'Koinonia', 'https://youtu.be/XNrauZ9EqUY', 'ministration', 'Koinonia'), ('youtube', 'Deeper Life Live', 'https://www.youtube.com/live/XfxRoLMy4F8', 'ministration', 'Deeper Life'), ('youtube', 'Winners Live', 'https://www.youtube.com/live/iEAqejdwh3w', 'ministration', 'Winners'), ('youtube', 'Hillsong Church Australia Live', 'https://www.youtube.com/@hillsong.australia/live', 'ministration', 'Hillsong'), ('youtube', 'Harvest Christian Fellowship Live', 'https://www.youtube.com/@harvestchurchyt/live', 'ministration', 'Harvest'), ('youtube', 'Elevation Church Live', 'https://www.youtube.com/@elevationchurch/live', 'ministration', 'Elevation'), ('youtube', 'House on the Rock Live', 'https://www.youtube.com/@HOTR/live', 'ministration', 'HOTR'), ('youtube', 'Faith Tabernacle / Winners Live', 'https://www.youtube.com/@faithtabernacle/live', 'ministration', 'Winners'), ('youtube', 'RCCG Live', 'https://www.youtube.com/channel/UCDKGpzgtcvexRsqFI7Rvq6A/live', 'ministration', 'RCCG'), ('youtube', 'ONE Championship Live', 'https://www.youtube.com/@ONEChampionship/live', 'games', 'ONE Championship'), ('youtube', 'Olympics Live', 'https://www.youtube.com/@Olympics/live', 'games', 'Olympics'), ('youtube', 'PGA TOUR Live', 'https://www.youtube.com/@PGATOUR/live', 'games', 'PGA TOUR'), ('youtube', 'WWE Live', 'https://www.youtube.com/@WWE/live', 'games', 'WWE'), ('youtube', 'World Aquatics Live', 'https://www.youtube.com/@WorldAquatics/live', 'games', 'World Aquatics'), ('youtube', 'World Rugby Live', 'https://www.youtube.com/@worldrugby/live', 'games', 'World Rugby'), ('youtube', 'NBA Live', 'https://www.youtube.com/@NBA/live', 'games', 'NBA'), ('youtube', 'Red Bull Live', 'https://www.youtube.com/@redbull/live', 'games', 'Red Bull'), ('youtube', 'Formula 1 Live', 'https://www.youtube.com/@Formula1/live', 'games', 'Formula 1'), ('youtube', 'FIFA Live', 'https://www.youtube.com/@FIFA/live', 'games', 'FIFA'), ('youtube', 'AIT Live Channel', 'https://www.youtube.com/@ait_live/live', 'news', 'AIT TV'), ('youtube', 'Channels TV (channel live)', 'https://www.youtube.com/channel/UCEXGDNclvmg6RW0vipJYsTQ/live', 'news', 'Channels TV'), ('youtube', 'TVC News Channel Live', 'https://www.youtube.com/@TVCNewsNigeria/live', 'news', 'TVC'), ('youtube', 'K24 Kenya Live', 'https://www.youtube.com/@K24TV/live', 'tv', 'Kenya TV'), ('youtube', 'Joy News Channel Live', 'https://www.youtube.com/channel/UChd1DEecCRlxaa0-hvPACCw/live', 'tv', 'Joy TV'), ('youtube', 'Metro TV Ghana Live', 'https://www.youtube.com/@metrotvghana/live', 'tv', 'Metro Ghana'), ('youtube', 'BBC Africa Live', 'https://www.youtube.com/@BBCAfrica/live', 'news', 'BBC Africa'), ('youtube', 'India Today Live', 'https://www.youtube.com/@indiatoday/live', 'news', 'India Today'), ('youtube', 'TRT World Live', 'https://www.youtube.com/@trtworld/live', 'news', 'TRT World'), ('youtube', 'NHK World Japan Live', 'https://www.youtube.com/@NHKWORLDJAPAN/live', 'news', 'Japan TV'), ('youtube', 'Channel News Asia Live', 'https://www.youtube.com/@channelnewsasia/live', 'news', 'Channel Asia'), ('youtube', 'Euronews Channel Live', 'https://www.youtube.com/@euronews/live', 'news', 'Euro News'), ('youtube', 'DW News Live', 'https://www.youtube.com/@dwnews/live', 'news', 'DW News'), ('youtube', 'France 24 Live', 'https://www.youtube.com/@France24_en/live', 'news', 'France 24'), ('youtube', 'ABC News Channel Live', 'https://www.youtube.com/@ABCNews/live', 'news', 'ABC News'), ('youtube', 'Sky News Channel Live', 'https://www.youtube.com/@SkyNews/live', 'news', 'Sky News'), ('youtube', 'Al Jazeera English Channel Live', 'https://www.youtube.com/@AlJazeeraEnglish/live', 'news', 'Al Jazeera'), ('youtube', 'BBC News Channel Live', 'https://www.youtube.com/channel/UC16niRr50-MSBwiO3YDb3RA/live', 'news', 'BBC Live')]


def _seed_starter_links(session: Session, user_id=None, replace: bool = False) -> int:
    """Insert STARTER_STREAM_LINKS. If replace=True, delete all first."""
    from datetime import datetime
    if replace:
        for old in session.exec(select(SocialStreamLink)).all():
            session.delete(old)
        session.commit()
    existing = {(r.source_url or "").strip() for r in session.exec(select(SocialStreamLink)).all()}
    added = 0
    for i, (platform, title, url, category, note) in enumerate(STARTER_STREAM_LINKS):
        url = (url or "").strip()
        if not url or url in existing:
            continue
        emb = build_embed_url(platform, url)
        ycid = extract_youtube_channel_id(url)
        if ycid and platform == "youtube":
            try:
                emb = channel_live_embed(ycid)
            except Exception:
                pass
        session.add(SocialStreamLink(
            platform=(platform or "youtube")[:20],
            title=(title or "Stream")[:200],
            source_url=url[:800],
            embed_url=(emb[:900] if emb else None),
            description=(note or None),
            category=(category or "tv")[:30],
            youtube_channel_id=(ycid[:40] if ycid else None),
            is_active=True,
            sort_order=i * 10,
            created_by=user_id,
            created_at=datetime.utcnow(),
        ))
        existing.add(url)
        added += 1
    session.commit()
    return added


@router.post("/admin/social-stream/load-library")
async def admin_load_library(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
    replace: str = Form("1"),
):
    """One-click load of all built-in YouTube/news/movies links."""
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    n = _seed_starter_links(session, getattr(user, "id", None), replace=str(replace).strip() in ("1", "true", "yes", "on"))
    return RedirectResponse(f"/admin/social-stream?ok=library&added={n}", status_code=303)


# ========== CSV backup / restore for Social Stream links ==========
@router.get("/admin/social-stream/export.csv")
async def admin_social_stream_export_csv(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Download all stream links as CSV so they can be re-uploaded after a redeploy."""
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    import csv
    import io
    from fastapi.responses import StreamingResponse

    rows = list(
        session.exec(
            select(SocialStreamLink).order_by(SocialStreamLink.sort_order, SocialStreamLink.id)
        ).all()
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "platform", "title", "source_url", "category", "description",
        "is_active", "sort_order", "embed_url", "youtube_channel_id",
    ])
    for L in rows:
        w.writerow([
            L.platform or "",
            L.title or "",
            L.source_url or "",
            L.category or "tv",
            L.description or "",
            "1" if L.is_active else "0",
            int(L.sort_order or 0),
            L.embed_url or "",
            L.youtube_channel_id or "",
        ])
    buf.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="churchgate_social_stream_links.csv"'
    }
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


@router.post("/admin/social-stream/import-csv")
async def admin_social_stream_import_csv(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Upload a CSV (same columns as export) to restore links after deploy."""
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    import csv
    import io
    from datetime import datetime

    form = await request.form()
    replace = str(form.get("replace") or "").strip() in ("1", "true", "yes", "on")
    upload = form.get("file")
    if not upload or not hasattr(upload, "read"):
        return RedirectResponse("/admin/social-stream?err=csv_file", status_code=303)

    raw = await upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        text = raw.decode("latin-1", errors="ignore")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return RedirectResponse("/admin/social-stream?err=csv_empty", status_code=303)

    # normalize headers
    def cell(row, *keys):
        for k in keys:
            for fk in row.keys():
                if (fk or "").strip().lower() == k.lower():
                    return (row.get(fk) or "").strip()
        return ""

    if replace:
        for old in session.exec(select(SocialStreamLink)).all():
            session.delete(old)
        session.commit()

    existing = {
        ((r.source_url or "").strip(), (r.platform or "").strip().lower())
        for r in session.exec(select(SocialStreamLink)).all()
    }
    added = 0
    skipped = 0
    for row in reader:
        platform = cell(row, "platform").lower() or "youtube"
        source_url = cell(row, "source_url", "url", "link", "public_url", "public url")
        if not source_url:
            skipped += 1
            continue
        key = (source_url, platform)
        if key in existing and not replace:
            skipped += 1
            continue
        title = cell(row, "title") or (platform.title() + " stream")
        description = cell(row, "description", "note") or None
        category = (cell(row, "category") or "tv").lower()
        if category not in ("tv", "movies", "news", "games", "ministration", "others"):
            category = "tv"
        ycid = cell(row, "youtube_channel_id", "channel_id") or None
        if not ycid:
            ycid = extract_youtube_channel_id(source_url)
        emb = cell(row, "embed_url") or None
        if not emb:
            emb = build_embed_url(platform, source_url)
        if ycid and platform in ("youtube", ""):
            emb = channel_live_embed(ycid)
        is_active = cell(row, "is_active", "active") not in ("0", "false", "no", "off")
        try:
            sort_order = int(cell(row, "sort_order") or "0")
        except ValueError:
            sort_order = 0
        session.add(SocialStreamLink(
            platform=platform[:20],
            title=title[:200],
            source_url=source_url[:800],
            embed_url=(emb[:900] if emb else None),
            description=(description[:500] if description else None),
            category=category[:30],
            youtube_channel_id=(ycid[:40] if ycid else None),
            is_active=is_active,
            sort_order=sort_order,
            created_by=getattr(user, "id", None),
            created_at=datetime.utcnow(),
        ))
        existing.add(key)
        added += 1
    session.commit()
    return RedirectResponse(
        f"/admin/social-stream?ok=csv&added={added}&skipped={skipped}",
        status_code=303,
    )


@router.get("/member/social-watch", response_class=HTMLResponse)
async def member_social_watch(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cat = (request.query_params.get("cat") or "all").strip().lower()
    if cat not in ("all", "tv", "movies", "news", "games", "ministration", "others"):
        cat = "all"
    links = list(
        session.exec(
            select(SocialStreamLink)
            .where(SocialStreamLink.is_active == True)  # noqa: E712
            .order_by(SocialStreamLink.sort_order, SocialStreamLink.id.desc())
        ).all()
    )
    playable = []
    for L in links:
        emb = getattr(L, "embed_url", None) or ""
        src_u = getattr(L, "source_url", None) or ""
        ycid = getattr(L, "youtube_channel_id", None) or extract_youtube_channel_id(src_u)
        if ycid and (getattr(L, "platform", "") or "").lower() in ("youtube", ""):
            emb = channel_live_embed(ycid)
            try:
                L.embed_url = emb
            except Exception:
                pass
        elif not emb:
            emb = build_embed_url(getattr(L, "platform", "") or "youtube", src_u) or ""
            try:
                L.embed_url = emb
            except Exception:
                pass
        if not emb or "undefined" in emb or emb.strip() in ("", "#"):
            continue
        lc = (getattr(L, "category", None) or "").lower() or "tv"
        if cat != "all" and lc != cat:
            continue
        playable.append(L)
    return templates.TemplateResponse(
        "members/social_watch.html",
        {"request": request, "user": user, "links": playable, "cat": cat},
    )
