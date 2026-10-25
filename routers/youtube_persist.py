"""Persist approved home-page YouTube links across code deploys.

Approved + active links are mirrored to data/persistent/youtube_home.json.
On startup, missing rows are restored from that file into the database.
Only admin/global delete or reject removes a link from DB and the file.

Requires a durable DATABASE_URL (Postgres) for full safety; the JSON file
is an extra safety net when the app disk is writable.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlmodel import Session, select

PERSIST_DIR = Path("data/persistent")
PERSIST_DIR.mkdir(parents=True, exist_ok=True)
YT_FILE = PERSIST_DIR / "youtube_home.json"


def _load() -> List[Dict[str, Any]]:
    if not YT_FILE.exists():
        return []
    try:
        data = json.loads(YT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(rows: List[Dict[str, Any]]) -> None:
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    YT_FILE.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")


def mirror_from_db(session: Session) -> int:
    from app.models import YoutubeChannelLink
    rows = list(session.exec(
        select(YoutubeChannelLink).where(
            YoutubeChannelLink.is_approved == True,
            YoutubeChannelLink.is_active == True,
        )
    ).all())
    payload = []
    for r in rows:
        payload.append({
            "title": r.title,
            "youtube_url": r.youtube_url,
            "youtube_video_id": r.youtube_video_id,
            "church_id": r.church_id,
            "owner_type": r.owner_type or "global_church",
            "is_approved": True,
            "is_active": True,
            "submitted_by": r.submitted_by,
            "approved_by": r.approved_by,
        })
    _save(payload)
    return len(payload)


def restore_into_db(session: Session) -> int:
    """Insert JSON links missing from DB. Never deletes existing DB rows."""
    from app.models import YoutubeChannelLink
    stored = _load()
    if not stored:
        return mirror_from_db(session)
    added = 0
    for item in stored:
        vid = item.get("youtube_video_id")
        url = item.get("youtube_url")
        if not vid and not url:
            continue
        existing = None
        if vid:
            existing = session.exec(
                select(YoutubeChannelLink).where(YoutubeChannelLink.youtube_video_id == vid)
            ).first()
        if not existing and url:
            existing = session.exec(
                select(YoutubeChannelLink).where(YoutubeChannelLink.youtube_url == url)
            ).first()
        if existing:
            if not existing.is_approved or not existing.is_active:
                existing.is_approved = True
                existing.is_active = True
                session.add(existing)
            continue
        session.add(YoutubeChannelLink(
            title=item.get("title") or "YouTube",
            youtube_url=url or f"https://www.youtube.com/watch?v={vid}",
            youtube_video_id=vid,
            church_id=item.get("church_id"),
            owner_type=item.get("owner_type") or "global_church",
            is_approved=True,
            is_active=True,
            submitted_by=item.get("submitted_by"),
            approved_by=item.get("approved_by"),
            approved_at=datetime.utcnow(),
        ))
        added += 1
    if added:
        session.commit()
    mirror_from_db(session)
    return added


def remove_from_mirror(video_id: Optional[str], url: Optional[str] = None) -> None:
    rows = _load()
    new = []
    for r in rows:
        if video_id and r.get("youtube_video_id") == video_id:
            continue
        if url and r.get("youtube_url") == url:
            continue
        new.append(r)
    _save(new)
