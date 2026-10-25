"""YouTube channel-live helpers for Churchgate social stream.
Merge into app/routers/social_stream.py (replace build_embed_url).
"""
from typing import Optional
from urllib.parse import quote
import re
import urllib.request


def extract_youtube_channel_id(url: str) -> Optional[str]:
    """Return UC… channel id from common YouTube URL shapes, if present."""
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
    """Best-effort resolve @handle → UC… without API key (HTML scrape)."""
    handle = (handle or "").lstrip("@").strip()
    if not handle or not re.match(r"^[A-Za-z0-9._-]+$", handle):
        return None
    page = f"https://www.youtube.com/@{handle}"
    try:
        req = urllib.request.Request(
            page,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ChurchgateSocial/1.2)",
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


def is_channel_live_embed(embed_url: Optional[str]) -> bool:
    if not embed_url:
        return False
    return "embed/live_stream" in embed_url and "channel=" in embed_url


def channel_live_embed(channel_id: str, muted: bool = True) -> str:
    cid = (channel_id or "").strip()
    mute = "1" if muted else "0"
    return (
        "https://www.youtube.com/embed/live_stream?channel="
        + quote(cid, safe="")
        + f"&autoplay=1&mute={mute}&playsinline=1&rel=0&modestbranding=1"
    )


def build_embed_url(platform: str, source_url: str) -> Optional[str]:
    """Build iframe embed URL. YouTube channel /live → persistent live_stream embed."""
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
        # Persistent channel live — e.g.
        # https://www.youtube.com/channel/UCEXGDNclvmg6RW0vipJYsTQ/live
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
            host = "https://www.youtube.com/embed/"
            q = "autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1&enablejsapi=1"
            return host + vid + "?" + q
        return None

    return None
