"""Proxy Daily Manna (dailymanna.app) for member portal + Angel."""
from datetime import date
from typing import Optional
import json
import urllib.request
import urllib.error

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.auth import require_user
from app.models import User

router = APIRouter(tags=["manna"])

DM_API = "https://dailymanna-backend-jt33.onrender.com/api"


def _post_json(url: str, payload: dict, timeout: int = 25) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "KnowsoftChurchgate/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_daily_manna(category: str = "Adult", day: Optional[str] = None) -> dict:
    """Fetch full devotional text from Daily Manna backend (category Adult|Youth)."""
    cat = category if category in ("Adult", "Youth") else "Adult"
    payload = {"timezone": "Africa/Lagos", "category": cat}
    if day:
        payload["date"] = day
        url = f"{DM_API}/devotionals/date/{day}"
    else:
        url = f"{DM_API}/devotionals/today"
    try:
        raw = _post_json(url, payload)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e)
        try:
            err = json.loads(body)
            msg = err.get("message") or body
        except Exception:
            msg = body or str(e)
        return {"ok": False, "error": msg, "source": "https://www.dailymanna.app/"}
    except Exception as e:
        return {"ok": False, "error": str(e), "source": "https://www.dailymanna.app/"}

    data = (raw or {}).get("data") or {}
    dev = data.get("devotional") or {}
    if not dev:
        return {
            "ok": False,
            "error": "No devotional returned for this date",
            "source": "https://www.dailymanna.app/",
        }
    return {
        "ok": True,
        "source": "https://www.dailymanna.app/",
        "attribution": "Daily Manna — Pastor Dr. W. F. Kumuyi / Deeper Christian Life Ministry",
        "date": (dev.get("date") or "")[:10],
        "category": dev.get("category") or cat,
        "topic": dev.get("topic") or "",
        "key_verse": dev.get("keyVerse") or "",
        "text_ref": f"{dev.get('book') or ''} {dev.get('chapter') or ''}:{dev.get('verse') or ''}".strip(),
        "message": dev.get("description") or "",
        "thought": dev.get("thoughtOfTheDay") or "",
        "bible_in_one_year": dev.get("bibleInOneYear") or "",
        "audio_url": dev.get("audioUrl") or "",
        "full_text": "\n\n".join(
            x for x in [
                (dev.get("topic") or ""),
                (dev.get("keyVerse") or ""),
                f"TEXT — {dev.get('book') or ''} {dev.get('chapter') or ''}:{dev.get('verse') or ''}".strip(),
                (dev.get("description") or ""),
                f"Thought for the day: {dev.get('thoughtOfTheDay')}" if dev.get("thoughtOfTheDay") else "",
                f"Bible in one year: {dev.get('bibleInOneYear')}" if dev.get("bibleInOneYear") else "",
            ] if x
        ),
    }


@router.get("/member/api/daily-manna")
async def api_daily_manna(
    category: str = Query("Adult"),
    date_str: Optional[str] = Query(None, alias="date"),
    user: User = Depends(require_user),
):
    """Full Daily Manna text for the member panel and Angel read-aloud."""
    result = fetch_daily_manna(category=category, day=date_str)
    status = 200 if result.get("ok") else 502
    return JSONResponse(result, status_code=status)
