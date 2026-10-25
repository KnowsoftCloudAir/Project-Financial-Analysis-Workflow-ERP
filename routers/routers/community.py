"""Focus groups, testimonies, Heart to Heart."""
from pathlib import Path
import shutil
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    User, UserRole, ChurchUnit, ChurchMember,
    FocusGroup, FocusGroupMember, FocusGroupMessage, FocusGroupMessageComment, FocusGroupMessageLike, FocusGroupMessageLike,
    Testimony, TestimonyLike, TestimonyComment,
    HeartNeed, HeartDonation, HeartDistribution,
)
from app.auth import require_user, require_roles, role_val, member_access_locked

router = APIRouter(tags=["community"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _member_for_user(session: Session, user: User) -> Optional[ChurchMember]:
    if user.member_id:
        return session.get(ChurchMember, user.member_id)
    return session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()


def _church_id(user: User) -> Optional[int]:
    return user.church_id


def _can_manage_groups(user: User) -> bool:
    rv = role_val(user.role)
    if rv in ("general_admin", "church_admin"):
        return True
    return bool(getattr(user, "can_manage_focus_groups", False))


def _is_group_member(session: Session, group_id: int, user: User) -> bool:
    m = _member_for_user(session, user)
    if not m:
        return False
    return session.exec(
        select(FocusGroupMember).where(
            FocusGroupMember.group_id == group_id,
            FocusGroupMember.member_id == m.id,
        )
    ).first() is not None



def _scope_ids(session: Session, user: User) -> list:
    cid = _church_id(user)
    if not cid:
        return []
    from app.routers.church import collect_descendant_ids
    if _can_manage_groups(user):
        return collect_descendant_ids(session, cid)
    return [cid]


def _members_in_scope(session: Session, user: User) -> list:
    ids = _scope_ids(session, user)
    if not ids:
        return []
    return list(session.exec(
        select(ChurchMember).where(
            ChurchMember.church_id.in_(ids),
            ChurchMember.approval_status == "approved",
        )
    ).all())

# ---------- Focus groups ----------
@router.get("/focus-groups", response_class=HTMLResponse)
async def focus_groups_list(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if member_access_locked(session, user):
        return RedirectResponse("/member/portal", status_code=303)
    cid = _church_id(user)
    if not cid:
        return templates.TemplateResponse("community/empty.html", {
            "request": request, "user": user,
            "empty_title": "No information to display",
            "empty_message": "Your account is not linked to a church yet.",
            "back_url": "/member/portal",
        })
    scope = _scope_ids(session, user) or [cid]
    groups = list(session.exec(
        select(FocusGroup).where(
            FocusGroup.church_id.in_(scope),
            FocusGroup.is_active == True,
        )
    ).all())
    # Members only see groups they belong to; admins see all in scope
    if not _can_manage_groups(user):
        m = _member_for_user(session, user)
        if not m:
            groups = []
        else:
            gids = {fm.group_id for fm in session.exec(
                select(FocusGroupMember).where(FocusGroupMember.member_id == m.id)
            ).all()}
            groups = [g for g in groups if g.id in gids]
    return templates.TemplateResponse("community/focus_list.html", {
        "request": request, "user": user, "groups": groups,
        "can_manage": _can_manage_groups(user),
    })


@router.get("/focus-groups/new", response_class=HTMLResponse)
async def focus_group_new(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _can_manage_groups(user):
        raise HTTPException(403, "Not allowed")
    cid = _church_id(user)
    members = _members_in_scope(session, user) if cid else []
    return templates.TemplateResponse("community/focus_form.html", {
        "request": request, "user": user, "members": members,
    })


@router.post("/focus-groups/new")
async def focus_group_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not _can_manage_groups(user):
        raise HTTPException(403, "Not allowed")
    cid = _church_id(user)
    if not cid:
        raise HTTPException(400, "No church")
    g = FocusGroup(
        church_id=cid, name=name.strip(), description=description.strip() or None,
        created_by=user.id, is_active=True,
    )
    session.add(g)
    session.commit()
    session.refresh(g)
    form = await request.form()
    raw = form.getlist("member_ids")
    for mid in raw:
        try:
            session.add(FocusGroupMember(group_id=g.id, member_id=int(mid)))
        except Exception:
            continue
    session.commit()
    return RedirectResponse(f"/focus-groups/{g.id}", status_code=303)


@router.get("/focus-groups/{group_id}", response_class=HTMLResponse)
async def focus_group_view(
    group_id: int,
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    g = session.get(FocusGroup, group_id)
    if not g or not g.is_active:
        raise HTTPException(404)
    can_manage = _can_manage_groups(user)
    if not can_manage and not _is_group_member(session, group_id, user):
        raise HTTPException(403, "You are not in this focus group")
    raw_msgs = list(session.exec(
        select(FocusGroupMessage).where(FocusGroupMessage.group_id == group_id)
        .order_by(FocusGroupMessage.created_at.desc())
    ).all())
    messages = []
    for msg in raw_msgs:
        sender = session.get(User, msg.sender_id)
        comments = list(session.exec(
            select(FocusGroupMessageComment).where(FocusGroupMessageComment.message_id == msg.id)
            .order_by(FocusGroupMessageComment.created_at)
        ).all())
        c_rows = []
        for c in comments:
            cu = session.get(User, c.user_id)
            c_rows.append({"user": cu.full_name if cu else "Member", "body": c.body, "at": c.created_at})
        likes = list(session.exec(
            select(FocusGroupMessageLike).where(FocusGroupMessageLike.message_id == msg.id)
        ).all())
        liked = any(L.user_id == user.id for L in likes)
        messages.append({
            "id": msg.id,
            "body": msg.body,
            "topic": getattr(msg, "topic", None),
            "image_path": getattr(msg, "image_path", None),
            "audio_path": getattr(msg, "audio_path", None),
            "sender": sender.full_name if sender else "Member",
            "at": msg.created_at,
            "comments": c_rows,
            "like_count": len(likes),
            "liked": liked,
        })
    member_rows = []
    for fm in session.exec(select(FocusGroupMember).where(FocusGroupMember.group_id == group_id)).all():
        mem = session.get(ChurchMember, fm.member_id)
        if mem:
            member_rows.append(mem)

    in_group_ids = {m.id for m in member_rows}
    available_members = []
    if can_manage:
        for m in _members_in_scope(session, user):
            if m.id not in in_group_ids:
                available_members.append(m)

    return templates.TemplateResponse("community/focus_view.html", {
        "request": request, "user": user, "group": g,
        "messages": messages, "members": member_rows,
        "can_manage": can_manage, "available_members": available_members,
    })


@router.post("/focus-groups/{group_id}/message")
async def focus_post_message(
    group_id: int,
    body: str = Form(""),
    topic: str = Form(""),
    image: UploadFile = File(None),
    audio: UploadFile = File(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Any focus-group member may start a topic thread with text, image, and <=30s audio."""
    import uuid
    g = session.get(FocusGroup, group_id)
    if not g:
        raise HTTPException(404)
    can_manage = _can_manage_groups(user) and g.church_id == user.church_id
    if not can_manage and not _is_group_member(session, group_id, user):
        raise HTTPException(403)
    body = (body or "").strip()
    topic = (topic or "").strip() or None
    if not body and not topic and not (image and image.filename) and not (audio and audio.filename):
        raise HTTPException(400, "Add a topic, message, photo, or short audio")
    img_path = None
    audio_path = None
    upload_root = Path("app/static/uploads/focus")
    upload_root.mkdir(parents=True, exist_ok=True)
    if image and image.filename:
        ext = (image.filename.rsplit(".", 1)[-1] or "jpg").lower()
        if ext in ("jpg", "jpeg", "png", "webp", "gif"):
            fname = f"fg_{group_id}_{uuid.uuid4().hex[:10]}.{ext}"
            dest = upload_root / fname
            with dest.open("wb") as f:
                shutil.copyfileobj(image.file, f)
            img_path = f"/static/uploads/focus/{fname}"
    if audio and audio.filename:
        ext = (audio.filename.rsplit(".", 1)[-1] or "webm").lower()
        if ext in ("webm", "mp3", "m4a", "ogg", "wav", "aac"):
            fname = f"fg_aud_{group_id}_{uuid.uuid4().hex[:10]}.{ext}"
            dest = upload_root / fname
            data = await audio.read()
            if len(data) > 2 * 1024 * 1024:
                raise HTTPException(400, "Audio too large — keep voice notes under 30 seconds")
            dest.write_bytes(data)
            audio_path = f"/static/uploads/focus/{fname}"
    session.add(FocusGroupMessage(
        group_id=group_id,
        sender_id=user.id,
        topic=topic,
        body=body or (topic or "Shared media"),
        image_path=img_path,
        audio_path=audio_path,
    ))
    session.commit()
    return RedirectResponse(f"/focus-groups/{group_id}", status_code=303)


@router.post("/focus-groups/messages/{message_id}/comment")
async def focus_comment(
    message_id: int,
    body: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    msg = session.get(FocusGroupMessage, message_id)
    if not msg:
        raise HTTPException(404)
    g = session.get(FocusGroup, msg.group_id)
    can_manage = g and _can_manage_groups(user) and g.church_id == user.church_id
    if not can_manage and not _is_group_member(session, msg.group_id, user):
        raise HTTPException(403)
    body = body.strip()
    if not body:
        raise HTTPException(400)
    session.add(FocusGroupMessageComment(message_id=message_id, user_id=user.id, body=body))
    session.commit()
    return RedirectResponse(f"/focus-groups/{msg.group_id}", status_code=303)




@router.post("/focus-groups/{group_id}/add-members")
async def focus_group_add_members(
    group_id: int,
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Admin / manager: add more members to an existing focus group."""
    g = session.get(FocusGroup, group_id)
    if not g or not g.is_active:
        raise HTTPException(404, "Group not found")
    if not _can_manage_groups(user):
        raise HTTPException(403, "Only admins can add members")
    # church_admin should manage groups in their scope
    scope = set(_scope_ids(session, user) or [])
    if role_val(user.role) != "general_admin" and g.church_id not in scope and g.church_id != user.church_id:
        raise HTTPException(403, "Group not in your church scope")

    form = await request.form()
    raw = form.getlist("member_ids")
    existing = {
        fm.member_id
        for fm in session.exec(
            select(FocusGroupMember).where(FocusGroupMember.group_id == group_id)
        ).all()
    }
    added = 0
    for mid in raw:
        try:
            mid_i = int(mid)
        except Exception:
            continue
        if mid_i in existing:
            continue
        # must be approved member in scope
        m = session.get(ChurchMember, mid_i)
        if not m or m.approval_status != "approved":
            continue
        if role_val(user.role) != "general_admin":
            if m.church_id not in scope and m.church_id != user.church_id:
                continue
        session.add(FocusGroupMember(group_id=group_id, member_id=mid_i))
        existing.add(mid_i)
        added += 1
    session.commit()
    return RedirectResponse(f"/focus-groups/{group_id}?added={added}", status_code=303)


@router.post("/focus-groups/{group_id}/remove-member")
async def focus_group_remove_member(
    group_id: int,
    member_id: int = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Admin / manager: remove a member from an existing focus group."""
    g = session.get(FocusGroup, group_id)
    if not g or not g.is_active:
        raise HTTPException(404)
    if not _can_manage_groups(user):
        raise HTTPException(403, "Only admins can remove members")
    scope = set(_scope_ids(session, user) or [])
    if role_val(user.role) != "general_admin" and g.church_id not in scope and g.church_id != user.church_id:
        raise HTTPException(403)
    fm = session.exec(
        select(FocusGroupMember).where(
            FocusGroupMember.group_id == group_id,
            FocusGroupMember.member_id == member_id,
        )
    ).first()
    if fm:
        session.delete(fm)
        session.commit()
    return RedirectResponse(f"/focus-groups/{group_id}", status_code=303)


@router.post("/focus-groups/{group_id}/privilege")
async def grant_focus_privilege(
    group_id: int,
    member_user_email: str = Form(""),
    enable: str = Form("yes"),
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    """Grant a member account permission to manage focus groups."""
    target = session.exec(select(User).where(User.email == member_user_email.strip().lower())).first()
    if not target:
        raise HTTPException(404, "User not found")
    target.can_manage_focus_groups = enable == "yes"
    session.add(target)
    session.commit()
    return RedirectResponse(f"/focus-groups/{group_id}", status_code=303)


# ---------- Testimonies ----------
@router.get("/testimonies", response_class=HTMLResponse)
async def testimonies_list(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        return templates.TemplateResponse("community/empty.html", {
            "request": request, "user": user,
            "empty_title": "No information to display",
            "empty_message": "Link to a church to share and read testimonies.",
            "back_url": "/member/portal",
        })
    rows = list(session.exec(
        select(Testimony).where(Testimony.church_id == cid, Testimony.is_active == True)
        .order_by(Testimony.created_at.desc())
    ).all())
    if not rows:
        return templates.TemplateResponse("community/testimonies.html", {
            "request": request, "user": user, "items": [],
        })
    items = []
    for t in rows:
        u = session.get(User, t.user_id)
        likes = list(session.exec(select(TestimonyLike).where(TestimonyLike.testimony_id == t.id)).all())
        comments = list(session.exec(
            select(TestimonyComment).where(TestimonyComment.testimony_id == t.id)
            .order_by(TestimonyComment.created_at)
        ).all())
        clist = []
        for c in comments:
            cu = session.get(User, c.user_id)
            clist.append({"id": c.id, "body": c.body, "user": cu.full_name if cu else "Member", "user_id": c.user_id})
        items.append({
            "t": t, "author": u.full_name if u else "Member",
            "likes": len(likes), "liked": any(l.user_id == user.id for l in likes),
            "comments": clist,
        })
    return templates.TemplateResponse("community/testimonies.html", {
        "request": request, "user": user, "items": items,
    })


@router.post("/testimonies")
async def testimony_create(
    title: str = Form(...),
    body: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        raise HTTPException(400, "No church")
    m = _member_for_user(session, user)
    session.add(Testimony(
        church_id=cid, member_id=m.id if m else None, user_id=user.id,
        title=title.strip(), body=body.strip(),
    ))
    session.commit()
    return RedirectResponse("/testimonies", status_code=303)


@router.post("/testimonies/{tid}/like")
async def testimony_like(
    tid: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    existing = session.exec(
        select(TestimonyLike).where(TestimonyLike.testimony_id == tid, TestimonyLike.user_id == user.id)
    ).first()
    if existing:
        session.delete(existing)
    else:
        session.add(TestimonyLike(testimony_id=tid, user_id=user.id))
    session.commit()
    return RedirectResponse("/testimonies", status_code=303)


@router.post("/testimonies/{tid}/comment")
async def testimony_comment(
    tid: int,
    body: str = Form(...),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    body = body.strip()
    if not body:
        raise HTTPException(400)
    session.add(TestimonyComment(testimony_id=tid, user_id=user.id, body=body))
    session.commit()
    return RedirectResponse("/testimonies", status_code=303)


# ---------- Heart to Heart ----------
@router.get("/heart-to-heart", response_class=HTMLResponse)
async def heart_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        return templates.TemplateResponse("community/empty.html", {
            "request": request, "user": user,
            "empty_title": "No information to display",
            "empty_message": "Heart to Heart is available when your account is linked to a district church.",
            "back_url": "/member/portal",
        })
    needs = list(session.exec(
        select(HeartNeed).where(HeartNeed.church_id == cid).order_by(HeartNeed.created_at.desc())
    ).all())
    donations = list(session.exec(
        select(HeartDonation).where(HeartDonation.church_id == cid).order_by(HeartDonation.created_at.desc())
    ).all())
    dists = list(session.exec(
        select(HeartDistribution).where(HeartDistribution.church_id == cid).order_by(HeartDistribution.created_at.desc())
    ).all())
    pool = sum(d.amount for d in donations if d.need_id is None)
    total_donated = sum(d.amount for d in donations)
    total_distributed = sum(d.amount for d in dists)
    need_rows = []
    for n in needs:
        author = session.get(User, n.user_id)
        need_rows.append({"n": n, "author": author.full_name if author else "Member"})
    dist_rows = []
    for d in dists:
        m = session.get(ChurchMember, d.beneficiary_member_id) if d.beneficiary_member_id else None
        dist_rows.append({"d": d, "beneficiary": m.full_name if m else "Member"})
    is_admin = role_val(user.role) in ("church_admin", "general_admin", "data_officer")
    members = list(session.exec(
        select(ChurchMember).where(ChurchMember.church_id == cid, ChurchMember.approval_status == "approved")
    ).all()) if is_admin else []
    return templates.TemplateResponse("community/heart.html", {
        "request": request, "user": user, "needs": need_rows,
        "pool": pool, "total_donated": total_donated, "total_distributed": total_distributed,
        "distributions": dist_rows, "is_admin": is_admin, "members": members,
    })


@router.post("/heart-to-heart/need")
async def heart_need(
    title: str = Form(...),
    situation: str = Form(...),
    amount_requested: float = Form(0),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        raise HTTPException(400)
    m = _member_for_user(session, user)
    session.add(HeartNeed(
        church_id=cid, member_id=m.id if m else None, user_id=user.id,
        title=title.strip(), situation=situation.strip(),
        amount_requested=float(amount_requested or 0),
    ))
    session.commit()
    return RedirectResponse("/heart-to-heart", status_code=303)


@router.post("/heart-to-heart/donate")
async def heart_donate(
    amount: float = Form(...),
    need_id: str = Form(""),
    note: str = Form(""),
    anonymous: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        raise HTTPException(400)
    amount = float(amount)
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    nid = int(need_id) if need_id.strip().isdigit() else None
    session.add(HeartDonation(
        church_id=cid, need_id=nid, donor_user_id=user.id,
        amount=amount, note=note.strip() or None, is_anonymous=anonymous == "yes",
    ))
    if nid:
        need = session.get(HeartNeed, nid)
        if need:
            need.amount_raised = (need.amount_raised or 0) + amount
            session.add(need)
    session.commit()
    return RedirectResponse("/heart-to-heart", status_code=303)


@router.post("/heart-to-heart/distribute")
async def heart_distribute(
    amount: float = Form(...),
    need_id: str = Form(""),
    beneficiary_member_id: str = Form(""),
    note: str = Form(""),
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    cid = _church_id(user)
    if not cid:
        raise HTTPException(400)
    amount = float(amount)
    if amount <= 0:
        raise HTTPException(400)
    nid = int(need_id) if need_id.strip().isdigit() else None
    bid = int(beneficiary_member_id) if beneficiary_member_id.strip().isdigit() else None
    session.add(HeartDistribution(
        church_id=cid, need_id=nid, beneficiary_member_id=bid,
        amount=amount, note=note.strip() or None, recorded_by=user.id,
    ))
    if nid:
        need = session.get(HeartNeed, nid)
        if need:
            need.status = "helped"
            session.add(need)
    session.commit()
    return RedirectResponse("/heart-to-heart", status_code=303)


@router.post("/heart-to-heart/distributions/{did}/affirm")
async def heart_affirm(
    did: int,
    note: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    d = session.get(HeartDistribution, did)
    if not d:
        raise HTTPException(404)
    m = _member_for_user(session, user)
    # Beneficiary or church admin may affirm
    is_admin = role_val(user.role) in ("church_admin", "general_admin")
    if not is_admin and (not m or m.id != d.beneficiary_member_id):
        raise HTTPException(403, "Only the beneficiary can affirm receipt")
    d.beneficiary_affirmed = True
    d.affirmed_at = datetime.utcnow()
    if note.strip():
        d.note = (d.note or "") + f" | Affirmed: {note.strip()}"
    session.add(d)
    # Also mark linked need
    if d.need_id:
        need = session.get(HeartNeed, d.need_id)
        if need and need.user_id == user.id:
            need.receipt_affirmed = True
            need.receipt_note = note.strip() or need.receipt_note
            session.add(need)
    session.commit()
    return RedirectResponse("/heart-to-heart", status_code=303)
