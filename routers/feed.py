"""Member interaction feed — posts, likes, comments, photos, shares; expire in 24h; same global church."""
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import uuid
import shutil

from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    User, UserRole, ChurchUnit, ChurchMember, ChurchLevel,
    MemberFeedPost, MemberFeedLike, MemberFeedComment,
    FocusGroup, FocusGroupMember, FocusGroupJoinRequest,
)
from app.auth import require_user, role_val

router = APIRouter(tags=["feed"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
UPLOAD = Path("app/static/uploads/feed")
UPLOAD.mkdir(parents=True, exist_ok=True)


def _global_root_id(session: Session, church_id: Optional[int]) -> Optional[int]:
    if not church_id:
        return None
    cur = session.get(ChurchUnit, church_id)
    if not cur:
        return None
    while cur and cur.parent_id:
        parent = session.get(ChurchUnit, cur.parent_id)
        if not parent:
            break
        cur = parent
    return cur.id if cur else church_id


def _member(session: Session, user: User) -> Optional[ChurchMember]:
    if user.member_id:
        return session.get(ChurchMember, user.member_id)
    return session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()


def _expire_old(session: Session):
    now = datetime.utcnow()
    for p in session.exec(
        select(MemberFeedPost).where(MemberFeedPost.is_active == True, MemberFeedPost.expires_at <= now)
    ).all():
        p.is_active = False
        session.add(p)
    try:
        session.commit()
    except Exception:
        session.rollback()


def _post_payload(session: Session, p: MemberFeedPost, user: User) -> dict:
    author = session.get(User, p.author_user_id)
    mem = session.get(ChurchMember, p.author_member_id) if p.author_member_id else None
    likes = list(session.exec(select(MemberFeedLike).where(MemberFeedLike.post_id == p.id)).all())
    comments = list(session.exec(
        select(MemberFeedComment).where(MemberFeedComment.post_id == p.id)
        .order_by(MemberFeedComment.created_at)
    ).all())
    clist = []
    for c in comments:
        cu = session.get(User, c.user_id)
        clist.append({"id": c.id, "body": c.body, "user": (cu.full_name if cu else "Member"), "user_id": c.user_id, "at": c.created_at})
    shared = None
    if p.shared_post_id:
        sp = session.get(MemberFeedPost, p.shared_post_id)
        if sp:
            su = session.get(User, sp.author_user_id)
            shared = {
                "id": sp.id,
                "body": sp.body,
                "image": sp.image_path,
                "author": su.full_name if su else "Member",
            }
    return {
        "id": p.id,
        "body": p.body or "",
        "image": p.image_path,
        "author": (mem.full_name if mem and getattr(mem, "full_name", None) else (author.full_name if author else "Member")),
        "author_id": p.author_user_id,
        "likes": len(likes),
        "liked": any(l.user_id == user.id for l in likes),
        "comments": clist,
        "shared": shared,
        "expires_at": p.expires_at,
        "created_at": p.created_at,
    }


@router.get("/member/feed", response_class=HTMLResponse)
async def feed_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    _expire_old(session)
    gid = _global_root_id(session, user.church_id)
    posts = []
    if gid:
        rows = list(session.exec(
            select(MemberFeedPost).where(
                MemberFeedPost.global_church_id == gid,
                MemberFeedPost.is_active == True,
                MemberFeedPost.expires_at > datetime.utcnow(),
            ).order_by(MemberFeedPost.created_at.desc()).limit(50)
        ).all())
        posts = [_post_payload(session, p, user) for p in rows]
    # Focus groups available to request join
    groups = []
    m = _member(session, user)
    if gid and m:
        # all groups under global tree churches
        from app.routers.community import _scope_ids
        try:
            scope = _scope_ids(session, user)
        except Exception:
            scope = [user.church_id] if user.church_id else []
        if scope:
            gs = list(session.exec(
                select(FocusGroup).where(FocusGroup.church_id.in_(scope), FocusGroup.is_active == True)
            ).all())
            my_ids = {
                x.group_id for x in session.exec(
                    select(FocusGroupMember).where(FocusGroupMember.member_id == m.id)
                ).all()
            }
            pending = {
                x.group_id for x in session.exec(
                    select(FocusGroupJoinRequest).where(
                        FocusGroupJoinRequest.member_id == m.id,
                        FocusGroupJoinRequest.status == "pending",
                    )
                ).all()
            }
            for g in gs:
                groups.append({
                    "id": g.id,
                    "name": g.name,
                    "joined": g.id in my_ids,
                    "pending": g.id in pending,
                })
    return templates.TemplateResponse("members/feed.html", {
        "request": request, "user": user, "posts": posts, "groups": groups,
    })


@router.post("/member/feed/post")
async def feed_create(
    body: str = Form(""),
    file: UploadFile = File(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    gid = _global_root_id(session, user.church_id)
    if not gid:
        raise HTTPException(400, "No church linked")
    text = (body or "").strip()
    img = None
    if file and file.filename:
        if not (file.content_type or "").startswith("image/"):
            raise HTTPException(400, "Images only for upload")
        ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            ext = "jpg"
        fname = f"feed_{user.id}_{uuid.uuid4().hex[:8]}.{ext}"
        dest = UPLOAD / fname
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        img = f"/static/uploads/feed/{fname}"
    if not text and not img:
        raise HTTPException(400, "Write something or upload a picture")
    now = datetime.utcnow()
    m = _member(session, user)
    post = MemberFeedPost(
        global_church_id=gid,
        author_user_id=user.id,
        author_member_id=m.id if m else None,
        body=text or None,
        image_path=img,
        is_active=True,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(post)
    session.commit()
    return RedirectResponse("/member/feed", status_code=303)


@router.post("/member/feed/{post_id}/like")
async def feed_like(
    post_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    p = session.get(MemberFeedPost, post_id)
    if not p or not p.is_active:
        raise HTTPException(404)
    existing = session.exec(
        select(MemberFeedLike).where(MemberFeedLike.post_id == post_id, MemberFeedLike.user_id == user.id)
    ).first()
    if existing:
        session.delete(existing)
    else:
        session.add(MemberFeedLike(post_id=post_id, user_id=user.id))
    session.commit()
    return RedirectResponse("/member/feed", status_code=303)


@router.post("/member/feed/{post_id}/comment")
async def feed_comment(
    post_id: int,
    body: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    p = session.get(MemberFeedPost, post_id)
    if not p or not p.is_active:
        raise HTTPException(404)
    if not body.strip():
        raise HTTPException(400, "Empty comment")
    session.add(MemberFeedComment(post_id=post_id, user_id=user.id, body=body.strip()))
    session.commit()
    return RedirectResponse("/member/feed", status_code=303)


@router.post("/member/feed/{post_id}/share")
async def feed_share(
    post_id: int,
    note: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Reshare another member's post within the same global church (new 24h window)."""
    orig = session.get(MemberFeedPost, post_id)
    if not orig or not orig.is_active:
        raise HTTPException(404, "Post not found or expired")
    gid = _global_root_id(session, user.church_id)
    if not gid or orig.global_church_id != gid:
        raise HTTPException(403, "Can only share within your global church")
    now = datetime.utcnow()
    m = _member(session, user)
    session.add(MemberFeedPost(
        global_church_id=gid,
        author_user_id=user.id,
        author_member_id=m.id if m else None,
        body=(note.strip() or None),
        image_path=None,
        shared_post_id=orig.id,
        is_active=True,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    ))
    session.commit()
    return RedirectResponse("/member/feed", status_code=303)


@router.post("/member/feed/{post_id}/delete")
async def feed_delete(
    post_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    p = session.get(MemberFeedPost, post_id)
    if not p:
        raise HTTPException(404)
    if p.author_user_id != user.id and role_val(user.role) not in ("church_admin", "general_admin"):
        raise HTTPException(403)
    p.is_active = False
    session.add(p)
    session.commit()
    return RedirectResponse("/member/feed", status_code=303)


@router.post("/focus-groups/{group_id}/request-join")
async def request_join_group(
    group_id: int,
    note: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    g = session.get(FocusGroup, group_id)
    if not g or not g.is_active:
        raise HTTPException(404, "Group not found")
    m = _member(session, user)
    if not m:
        raise HTTPException(400, "Member profile required")
    if session.exec(
        select(FocusGroupMember).where(
            FocusGroupMember.group_id == group_id, FocusGroupMember.member_id == m.id
        )
    ).first():
        return RedirectResponse(f"/focus-groups/{group_id}", status_code=303)
    existing = session.exec(
        select(FocusGroupJoinRequest).where(
            FocusGroupJoinRequest.group_id == group_id,
            FocusGroupJoinRequest.member_id == m.id,
            FocusGroupJoinRequest.status == "pending",
        )
    ).first()
    if existing:
        return RedirectResponse("/member/feed", status_code=303)
    session.add(FocusGroupJoinRequest(
        group_id=group_id,
        member_id=m.id,
        user_id=user.id,
        status="pending",
        note=note.strip() or None,
    ))
    session.commit()
    return RedirectResponse("/member/feed?joined=1", status_code=303)


@router.post("/focus-groups/{group_id}/approve-join/{request_id}")
async def approve_join(
    group_id: int,
    request_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if role_val(user.role) not in ("church_admin", "general_admin", "data_officer"):
        raise HTTPException(403)
    req = session.get(FocusGroupJoinRequest, request_id)
    if not req or req.group_id != group_id:
        raise HTTPException(404)
    req.status = "approved"
    req.resolved_at = datetime.utcnow()
    session.add(req)
    if not session.exec(
        select(FocusGroupMember).where(
            FocusGroupMember.group_id == group_id, FocusGroupMember.member_id == req.member_id
        )
    ).first():
        session.add(FocusGroupMember(group_id=group_id, member_id=req.member_id))
    session.commit()
    return RedirectResponse(f"/focus-groups/{group_id}", status_code=303)
