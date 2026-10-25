"""General Admin full backup/restore + church CSV/PDF export and CSV upload."""
from pathlib import Path
from typing import Optional, List, Any
from datetime import datetime, date
import json
import csv
import io

from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, SQLModel

from app.database import get_session, engine
from app.models import (
    User, UserRole, ChurchUnit, ChurchMember, WeeklyStat, SpecialProgram,
    ProgramPhoto, MusicLink, YoutubeChannelLink, PastorMessage, FocusGroup, FocusGroupMember,
    FocusGroupMessage, MemberSubscription, SubscriptionSettings, DistrictMessage,
    SystemAnnouncement, AppConfig,
)
from app.auth import require_roles, require_user, role_val
from app.activity import log_activity
from app.routers.church import collect_descendant_ids

router = APIRouter(tags=["backup"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Tables to dump (order matters for restore roughly)
BACKUP_MODELS = [
    ("churchunit", ChurchUnit),
    ("user", User),
    ("churchmember", ChurchMember),
    ("weeklystat", WeeklyStat),
    ("specialprogram", SpecialProgram),
    ("programphoto", ProgramPhoto),
    ("musiclink", MusicLink),
    ("youtubechannellink", YoutubeChannelLink),  # home + login YouTube videos
    ("pastormessage", PastorMessage),
    ("focusgroup", FocusGroup),
    ("focusgroupmember", FocusGroupMember),
    ("focusgroupmessage", FocusGroupMessage),
    ("membersubscription", MemberSubscription),
    ("subscriptionsettings", SubscriptionSettings),
    ("districtmessage", DistrictMessage),
    ("systemannouncement", SystemAnnouncement),
    ("appconfig", AppConfig),
]


def _serialize(obj) -> dict:
    d = {}
    for k, v in obj.__dict__.items():
        if k.startswith("_"):
            continue
        if isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
        elif hasattr(v, "value"):
            d[k] = v.value
        else:
            try:
                json.dumps(v)
                d[k] = v
            except Exception:
                d[k] = str(v) if v is not None else None
    return d


@router.get("/admin/backup", response_class=HTMLResponse)
async def backup_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse("admin/backup.html", {"request": request, "user": user})


@router.get("/admin/backup/download")
async def backup_download(
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    payload = {
        "version": 1,
        "created_at": datetime.utcnow().isoformat(),
        "tables": {},
    }
    for name, model in BACKUP_MODELS:
        rows = list(session.exec(select(model)).all())
        payload["tables"][name] = [_serialize(r) for r in rows]
    data = json.dumps(payload, indent=2, default=str).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="churchgate-backup-{datetime.utcnow().strftime("%Y%m%d-%H%M")}.json"'
        },
    )


@router.post("/admin/backup/restore")
async def backup_restore(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid backup file")
    tables = payload.get("tables") or {}
    # Simple restore: upsert by id when present
    model_map = {n: m for n, m in BACKUP_MODELS}
    restored = 0
    for name, rows in tables.items():
        model = model_map.get(name)
        if not model or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            pk = row.get("id")
            obj = session.get(model, pk) if pk is not None else None
            if obj:
                for k, v in row.items():
                    if k == "id":
                        continue
                    if hasattr(obj, k):
                        try:
                            setattr(obj, k, v)
                        except Exception:
                            pass
                session.add(obj)
            else:
                try:
                    # strip unknown keys
                    fields = {c: row[c] for c in row if hasattr(model, c)}
                    session.add(model(**fields))
                except Exception as e:
                    print("restore row", name, e)
                    continue
            restored += 1
        session.commit()
    return RedirectResponse(f"/admin/backup?restored={restored}", status_code=303)


def _church_scope(user: User, session: Session) -> List[int]:
    if not user.church_id:
        return []
    return collect_descendant_ids(session, user.church_id)


@router.get("/church/export/csv")
async def church_export_csv(
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    ids = _church_scope(user, session)
    if not ids and role_val(user.role) != "general_admin":
        raise HTTPException(400, "No church linked")
    if role_val(user.role) == "general_admin" and not ids:
        members = list(session.exec(select(ChurchMember)).all())
    else:
        members = list(session.exec(select(ChurchMember).where(ChurchMember.church_id.in_(ids))).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "id", "full_name", "email", "phone", "whatsapp", "sex", "age_category",
        "confession", "status", "worker_type", "leader_type", "approval_status",
        "church_id", "address", "member_since", "prayer_request",
    ])
    for m in members:
        w.writerow([
            m.id, m.full_name, m.email, m.phone, m.whatsapp, m.sex, m.age_category,
            m.confession, m.status, m.worker_type, m.leader_type, m.approval_status,
            m.church_id, m.address, m.member_since, (m.prayer_request or "")[:200],
        ])
    data = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="church-members.csv"'},
    )


@router.get("/church/export/pdf")
async def church_export_pdf(
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    ids = _church_scope(user, session)
    if not ids:
        raise HTTPException(400, "No church linked")
    members = list(session.exec(
        select(ChurchMember).where(ChurchMember.church_id.in_(ids)).order_by(ChurchMember.full_name)
    ).all())
    church = session.get(ChurchUnit, user.church_id)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    w, h = landscape(A4)
    y = h - 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, y, f"Church database — {church.name if church else 'Church'}")
    y -= 8 * mm
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, y, f"Exported {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC · {len(members)} members")
    y -= 10 * mm
    headers = ["Name", "Email", "Phone", "Status", "Approval", "Sex"]
    xs = [15, 55, 100, 130, 150, 175]
    c.setFont("Helvetica-Bold", 8)
    for i, hd in enumerate(headers):
        c.drawString(xs[i] * mm, y, hd)
    y -= 5 * mm
    c.setFont("Helvetica", 7)
    for m in members:
        if y < 15 * mm:
            c.showPage()
            y = h - 20 * mm
            c.setFont("Helvetica", 7)
        vals = [m.full_name or "", (m.email or "")[:28], m.phone or "", m.status or "", m.approval_status or "", m.sex or ""]
        for i, v in enumerate(vals):
            c.drawString(xs[i] * mm, y, str(v)[:32])
        y -= 4.5 * mm
    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="church-members.pdf"'},
    )


@router.get("/church/export", response_class=HTMLResponse)
async def church_export_page(
    request: Request,
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
):
    return templates.TemplateResponse("church/export.html", {"request": request, "user": user})


@router.post("/church/export/upload-csv")
async def church_upload_csv(
    file: UploadFile = File(...),
    user: User = Depends(require_roles(UserRole.church_admin, UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    if not user.church_id and role_val(user.role) != "general_admin":
        raise HTTPException(400, "No church")
    raw = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(raw))
    n = 0
    for row in reader:
        email = (row.get("email") or "").strip()
        name = (row.get("full_name") or "").strip()
        if not name:
            continue
        mid = row.get("id")
        m = None
        if mid and str(mid).isdigit():
            m = session.get(ChurchMember, int(mid))
        if not m and email:
            m = session.exec(select(ChurchMember).where(ChurchMember.email == email)).first()
        if m:
            for field in ("full_name", "phone", "whatsapp", "sex", "age_category", "confession",
                          "status", "worker_type", "leader_type", "approval_status", "address"):
                if row.get(field):
                    setattr(m, field, row.get(field))
            session.add(m)
        else:
            session.add(ChurchMember(
                church_id=user.church_id or int(row.get("church_id") or 0) or user.church_id,
                full_name=name,
                email=email or None,
                phone=row.get("phone"),
                whatsapp=row.get("whatsapp"),
                sex=row.get("sex"),
                age_category=row.get("age_category"),
                confession=row.get("confession"),
                status=row.get("status") or "member",
                approval_status=row.get("approval_status") or "pending",
                address=row.get("address"),
            ))
        n += 1
    session.commit()
    return RedirectResponse(f"/church/export?uploaded={n}", status_code=303)


@router.get("/member/certificate/newborn")
async def newborn_certificate(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Beautiful New Born in Christ certificate PDF with Knowsoft logo."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader

    member = session.get(ChurchMember, user.member_id) if user.member_id else None
    if not member:
        member = session.exec(select(ChurchMember).where(ChurchMember.email == user.email)).first()
    name = (member.full_name if member else None) or user.full_name or user.email
    today = datetime.utcnow().strftime("%d %B %Y")
    if member:
        member.confession = "saved"
        session.add(member)
        session.commit()
    try:
        log_activity(session, user=user, action="certificate", detail="Downloaded New Born in Christ certificate")
    except Exception:
        pass

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    w, h = landscape(A4)

    # Deep navy background
    c.setFillColor(HexColor("#0b1220"))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Gold outer frame
    c.setStrokeColor(HexColor("#d4a017"))
    c.setLineWidth(5)
    c.roundRect(10 * mm, 10 * mm, w - 20 * mm, h - 20 * mm, 6 * mm, fill=0, stroke=1)
    c.setStrokeColor(HexColor("#f5e6a8"))
    c.setLineWidth(1.5)
    c.roundRect(14 * mm, 14 * mm, w - 28 * mm, h - 28 * mm, 4 * mm, fill=0, stroke=1)

    # Logo
    logo_paths = [
        Path("app/static/img/knowsoft-logo.png"),
        Path("app/static/icons/icon-512.png"),
        Path("app/static/icons/icon-192.png"),
    ]
    logo = next((p for p in logo_paths if p.exists()), None)
    if logo:
        try:
            img = ImageReader(str(logo))
            c.drawImage(img, w / 2 - 18 * mm, h - 42 * mm, width=36 * mm, height=36 * mm,
                        mask="auto", preserveAspectRatio=True, anchor="c")
        except Exception as e:
            print("logo draw", e)

    # Title - bold display style
    c.setFillColor(HexColor("#fbbf24"))
    c.setFont("Times-Bold", 26)
    c.drawCentredString(w / 2, h - 52 * mm, "NEW BORN IN CHRIST")
    c.setFont("Times-Bold", 18)
    c.drawCentredString(w / 2, h - 62 * mm, "CERTIFICATE")

    c.setFillColor(HexColor("#93c5fd"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w / 2, h - 72 * mm, "KNOWSOFT CHURCHGATE")

    c.setFillColor(HexColor("#e2e8f0"))
    c.setFont("Times-Italic", 13)
    c.drawCentredString(w / 2, h - 88 * mm, "This is to certify that")

    # Name - large bold
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Times-Bold", 24)
    # underline name
    c.drawCentredString(w / 2, h - 105 * mm, name)
    c.setStrokeColor(HexColor("#fbbf24"))
    c.setLineWidth(1.2)
    tw = c.stringWidth(name, "Times-Bold", 24)
    c.line(w / 2 - tw / 2 - 5, h - 108 * mm, w / 2 + tw / 2 + 5, h - 108 * mm)

    c.setFillColor(HexColor("#cbd5e1"))
    c.setFont("Times-Roman", 13)
    line1 = f"on this day, {today},"
    line2 = "accepted Jesus Christ as Lord and personal Saviour."
    c.drawCentredString(w / 2, h - 122 * mm, line1)
    c.drawCentredString(w / 2, h - 130 * mm, line2)

    c.setFillColor(HexColor("#34d399"))
    c.setFont("Times-Bold", 16)
    c.drawCentredString(w / 2, h - 148 * mm, "Congratulations — you are saved!")

    c.setFillColor(HexColor("#94a3b8"))
    c.setFont("Times-Italic", 9)
    c.drawCentredString(w / 2, 28 * mm, '"Therefore if any man be in Christ, he is a new creature." — 2 Corinthians 5:17')
    c.setFont("Helvetica", 8)
    c.drawCentredString(w / 2, 22 * mm, "John 1:12  ·  Knowsoft Churchgate")

    c.save()
    buf.seek(0)
    safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="NewBorn-in-Christ-{safe}.pdf"'},
    )
