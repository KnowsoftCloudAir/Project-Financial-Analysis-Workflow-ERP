from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.auth import require_user
from app.models import User

router = APIRouter(tags=["device-music"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

@router.get("/member/device-music", response_class=HTMLResponse)
async def device_music_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("member/device_music.html", {"request": request, "user": user})
