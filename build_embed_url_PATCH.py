# Paste these helpers into app/routers/social_stream.py
# Replace the existing build_embed_url function with the version below.
# Also set youtube_channel_id when adding a link.


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
    # live_stream embed already has channel=
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
            r'channel/(UC[A-Za-z0-9_-]{20,})',
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
    """Build iframe-ready embed URL. YouTube channel /live → persistent live_stream embed."""
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
        # --- Persistent channel live (never tied to one ended broadcast) ---
        # Examples:
        #   https://www.youtube.com/channel/UCEXGDNclvmg6RW0vipJYsTQ/live
        #   https://www.youtube.com/channel/UCEXGDNclvmg6RW0vipJYsTQ
        #   ytchan:UCEXGDNclvmg6RW0vipJYsTQ
        cid = extract_youtube_channel_id(url)
        if cid:
            return channel_live_embed(cid)

        # @Handle or @Handle/live → resolve to channel id when possible
        handle = re.search(r"youtube\.com/@([A-Za-z0-9._-]+)", url)
        if handle:
            h = handle.group(1)
            resolved = resolve_youtube_handle_to_channel_id(h)
            if resolved:
                return channel_live_embed(resolved)
            # Fallback: cannot embed by handle alone; return None so admin uses channel URL
            return None

        # /c/Name or /user/Name — only useful if /live and we cannot resolve without API
        if re.search(r"youtube\.com/(?:c|user)/[A-Za-z0-9._-]+", url) and "/live" in low:
            return None  # ask admin for channel/UC…/live

        # Specific video / live video id (ends when that broadcast ends)
        m = re.search(
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|"
            r"youtube\.com/live/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
            url,
        )
        if not m:
            m = re.search(r"(?:live/|v=|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
        if m:
            vid = m.group(1)
            # Prefer standard host for live-ish URLs
            is_live = ("/live/" in low) or ("live=1" in low)
            host = "https://www.youtube.com/embed/"
            q = "autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1&enablejsapi=1"
            return host + vid + "?" + q
        return None

    return None


# --- In admin_social_stream_add, after embed = build_embed_url(...): ---
#   cid = extract_youtube_channel_id(source_url)
#   if not cid and embed and "channel=" in embed:
#       cid = extract_youtube_channel_id(embed)
#   row = SocialStreamLink(..., youtube_channel_id=cid, embed_url=...)
