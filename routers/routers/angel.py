"""
Conversational Angel guide — uses built-in topics PLUS resources uploaded by General Admin.
"""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlmodel import Session, select

from app.database import get_session
from app.models import User, UserRole, AngelResource
from app.auth import require_roles, role_val

router = APIRouter(prefix="/angel", tags=["angel"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Category keys that match admin uploads and built-in topics
CATEGORY_MAP = {
    "revelation": ["revelation", "daniel", "prophecy", "end times"],
    "antichrist": ["antichrist", "beast", "man of sin"],
    "paul": ["paul", "gospel", "justification", "epistles"],
    "hell": ["hell", "lake of fire", "judgment", "second death"],
    "angels": ["angels", "angel", "michael", "gabriel"],
    "heaven_sin": ["heaven", "holiness", "perfect"],
    "resurrection": ["resurrection", "rapture", "incorruption"],
    "pray": ["prayer", "pray"],
    "overcome": ["overcome", "sin", "sanctification", "holiness walk"],
    "holy_spirit": ["holy spirit", "spirit", "baptism"],
    "salvation_ask": ["salvation", "gospel", "saved", "repentance"],
    "general": ["general", "teaching", "other"],
}


def builtin_topics() -> Dict[str, dict]:
    return {
        "start": {
            "title": "Welcome",
            "angel": (
                "Peace to you. I am here as a guide — a servant-voice pointing you to the Word of God, "
                "not to myself. The Scriptures testify of Jesus Christ (John 5:39).\n\n"
                "I also share teachings and notes your church leaders have placed in the library for you.\n\n"
                "What would you like us to walk through together?"
            ),
            "choices": [
                {"id": "revelation", "label": "The book of Revelation & Daniel"},
                {"id": "antichrist", "label": "The antichrist"},
                {"id": "paul", "label": "The teachings of Paul"},
                {"id": "hell", "label": "Hell & the lake of fire"},
                {"id": "angels", "label": "Angels — who they are"},
                {"id": "heaven_sin", "label": "Why saints cannot sin in heaven"},
                {"id": "resurrection", "label": "Resurrection & no more death"},
                {"id": "pray", "label": "How to pray"},
                {"id": "overcome", "label": "How to overcome sin"},
                {"id": "holy_spirit", "label": "The Holy Spirit"},
                {"id": "library", "label": "Browse all admin library resources"},
                {"id": "salvation_ask", "label": "I want to know God / be saved"},
            ],
        },
        "revelation": {
            "title": "Revelation & Daniel",
            "angel": (
                "Come, let us look together. Revelation is an unveiling — God gave it to Jesus Christ, "
                "and He signified it by His angel to John (Revelation 1:1).\n\n"
                "Daniel saw kingdoms, a little horn against the most High, and one like the Son of man with the clouds of heaven (Daniel 7). "
                "Revelation opens that sealed vision: the beast, the measured times, the return of the King, and a new creation.\n\n"
                "Would you like me to take you deeper — or open notes your leaders uploaded on this subject?"
            ),
            "choices": [
                {"id": "rev_deeper_beast", "label": "Yes — the beast & Daniel’s little horn"},
                {"id": "rev_deeper_times", "label": "Yes — the times (1,260 days / 42 months)"},
                {"id": "rev_deeper_future", "label": "Yes — past, present & future"},
                {"id": "res:revelation", "label": "Show admin library on Revelation / prophecy"},
                {"id": "start", "label": "Choose another topic"},
                {"id": "closing_love", "label": "I’m ready to finish for now"},
            ],
        },
        "rev_deeper_beast": {
            "title": "The beast & the little horn",
            "angel": (
                "Daniel saw a fourth beast with ten horns, and a little horn that spoke great words against the most High "
                "and made war with the saints (Daniel 7:7–8, 21, 25). "
                "John saw a beast from the sea; the dragon gave him power; he blasphemed and made war with the saints (Revelation 13:1–7).\n\n"
                "The end of that line is not victory for evil — the Lord destroys the Wicked with the brightness of His coming (2 Thessalonians 2:8), "
                "and the beast is cast into the lake of fire (Revelation 19:20)."
            ),
            "choices": [
                {"id": "antichrist", "label": "Connect this to the antichrist"},
                {"id": "res:antichrist", "label": "Admin library: antichrist / beast"},
                {"id": "revelation", "label": "Back to Revelation overview"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "rev_deeper_times": {
            "title": "The measured times",
            "angel": (
                "Daniel: a time, times, and the dividing of time (Daniel 7:25; 12:7). "
                "Revelation: a time, times, and half a time (Revelation 12:14); forty-two months (Revelation 11:2; 13:5); "
                "1,260 days (Revelation 11:3; 12:6).\n\n"
                "Trouble is real — but numbered. The Ancient of days still rules the clock."
            ),
            "choices": [
                {"id": "rev_deeper_future", "label": "Past, present & future"},
                {"id": "res:revelation", "label": "Admin library on prophecy"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "rev_deeper_future": {
            "title": "Past, present & future",
            "angel": (
                "Past: Daniel’s empires (Daniel 2; 7); the seven churches as real congregations (Revelation 2–3).\n"
                "Present: Christ among the candlesticks (Revelation 1:20); the spirit of antichrist already at work (1 John 4:3).\n"
                "Future: man of sin (2 Thessalonians 2), tribulation, Christ’s return (Revelation 19), judgment, new creation (Revelation 21–22).\n\n"
                "Would you like library notes from your leaders, or the way to know God yourself?"
            ),
            "choices": [
                {"id": "res:revelation", "label": "Open admin prophecy resources"},
                {"id": "salvation_ask", "label": "I want to know God through Christ"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "antichrist": {
            "title": "The antichrist",
            "angel": (
                "John: antichrist shall come — and even now there are many antichrists (1 John 2:18). "
                "Denying the Father and the Son is antichrist (1 John 2:22). "
                "The spirit that denies Jesus Christ come in the flesh is already in the world (1 John 4:3).\n\n"
                "Paul: a falling away, then the man of sin who exalts himself as God (2 Thessalonians 2:3–4); "
                "destroyed by the brightness of Christ’s coming (2:8).\n\n"
                "Shall we open what your leaders uploaded on this, or go deeper in the Word?"
            ),
            "choices": [
                {"id": "rev_deeper_beast", "label": "Link to the beast in Revelation"},
                {"id": "res:antichrist", "label": "Admin library on antichrist"},
                {"id": "salvation_ask", "label": "I need Christ, not only knowledge"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "paul": {
            "title": "Paul’s teaching",
            "angel": (
                "All have sinned (Romans 3:23). Justified freely by grace through Christ (Romans 3:24). "
                "Saved by grace through faith — not of works (Ephesians 2:8–9). "
                "Christ died for our sins and rose again (1 Corinthians 15:3–4).\n\n"
                "Walk: a living sacrifice (Romans 12:1–2); fruit of the Spirit (Galatians 5:22–23).\n"
                "Hope: the Lord descends; the dead rise; the living are caught up (1 Thessalonians 4:16–17)."
            ),
            "choices": [
                {"id": "salvation_ask", "label": "How do I receive this salvation?"},
                {"id": "res:paul", "label": "Admin library: Paul / gospel"},
                {"id": "overcome", "label": "How do I overcome sin?"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "hell": {
            "title": "Hell & the lake of fire",
            "angel": (
                "Jesus warned of unquenched fire (Mark 9:43–44). The rich man was in torments (Luke 16:23).\n\n"
                "Revelation’s lake of fire is the second death: beast and false prophet (Revelation 19:20), "
                "the devil (20:10), death and hell cast in (20:14), and whoever is not in the book of life (20:15).\n\n"
                "The greater word: Christ saves those who come to God by Him (Hebrews 7:25)."
            ),
            "choices": [
                {"id": "res:hell", "label": "Admin library on judgment"},
                {"id": "salvation_ask", "label": "Show me the way of life"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "angels": {
            "title": "Angels",
            "angel": (
                "We are created spirits (Psalm 148:5), ministering spirits for heirs of salvation (Hebrews 1:14). "
                "We do His commandments (Psalm 103:20). Worship God only (Revelation 22:8–9).\n\n"
                "Michael the archangel (Jude 9). Gabriel who stands in God’s presence (Luke 1:19). "
                "Some angels left their estate (Jude 6; 2 Peter 2:4). Holy angels kept their place.\n\n"
                "Our joy is that you look to the Lamb — not to us."
            ),
            "choices": [
                {"id": "heaven_sin", "label": "Why don’t holy angels sin?"},
                {"id": "res:angels", "label": "Admin library on angels"},
                {"id": "salvation_ask", "label": "I want to know the Lamb"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "heaven_sin": {
            "title": "No sin in heaven",
            "angel": (
                "Nothing that defiles enters (Revelation 21:27). No more curse; His servants see His face (Revelation 22:3–4). "
                "Spirits of just men made perfect (Hebrews 12:23). We shall be like Him (1 John 3:2).\n\n"
                "Sin is lawlessness (1 John 3:4). In that perfect likeness, sin has no place — grace finished, curse gone."
            ),
            "choices": [
                {"id": "resurrection", "label": "Resurrection bodies"},
                {"id": "res:heaven", "label": "Admin library: heaven / holiness"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "resurrection": {
            "title": "Resurrection & no more death",
            "angel": (
                "Sown in corruption; raised in incorruption (1 Corinthians 15:42). "
                "Changed in a moment at the last trump (15:51–54). "
                "Dead in Christ rise; living caught up (1 Thessalonians 4:16–17). "
                "Children of the resurrection cannot die any more (Luke 20:36). "
                "Christ dieth no more (Romans 6:9). No more death (Revelation 21:4)."
            ),
            "choices": [
                {"id": "salvation_ask", "label": "How do I get into Christ?"},
                {"id": "res:resurrection", "label": "Admin library: resurrection / hope"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "pray": {
            "title": "How to pray",
            "angel": (
                "Our Father which art in heaven… (Matthew 6:9–13). "
                "Come boldly to the throne of grace (Hebrews 4:16). "
                "If we confess our sins, He is faithful and just to forgive (1 John 1:9).\n\n"
                "Simple prayer: “Father, I come in Jesus’ name. Forgive me. Teach me. Fill me with Your Spirit. Amen.”\n"
                "Ask, seek, knock (Matthew 7:7)."
            ),
            "choices": [
                {"id": "salvation_ask", "label": "Begin with salvation first"},
                {"id": "res:pray", "label": "Admin library on prayer"},
                {"id": "holy_spirit", "label": "The Holy Spirit"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "overcome": {
            "title": "Overcome sin",
            "angel": (
                "Grace teaches us to deny ungodliness (Titus 2:11–12). "
                "Walk in the Spirit (Galatians 5:16). Hide the Word in your heart (Psalm 119:11). "
                "Confess and be forgiven (1 John 1:9). Reckon yourself alive to God (Romans 6:11). "
                "Shield of faith and sword of the Spirit (Ephesians 6:16–17)."
            ),
            "choices": [
                {"id": "holy_spirit", "label": "I need the Holy Spirit’s help"},
                {"id": "res:overcome", "label": "Admin library: holiness / overcome"},
                {"id": "pray", "label": "Help me pray"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "holy_spirit": {
            "title": "The Holy Spirit",
            "angel": (
                "The Comforter (John 14:16–26). He convicts (John 16:8). "
                "By one Spirit baptized into one body (1 Corinthians 12:13). "
                "Power when the Holy Ghost is come upon you (Acts 1:8). "
                "Ask the Father (Luke 11:13). Be filled (Ephesians 5:18). Fruit of the Spirit (Galatians 5:22–23)."
            ),
            "choices": [
                {"id": "salvation_ask", "label": "I need to be saved first"},
                {"id": "res:holy_spirit", "label": "Admin library: Holy Spirit"},
                {"id": "overcome", "label": "Overcoming sin with His help"},
                {"id": "start", "label": "Another topic"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
        "library": {
            "title": "Admin resource library",
            "angel": (
                "Here are categories where General Admin can place teachings, notes, and scripture helps. "
                "Choose a shelf — or ask Admin to upload more under Admin → Angel resources."
            ),
            "choices": [
                {"id": "res:revelation", "label": "Revelation / prophecy"},
                {"id": "res:antichrist", "label": "Antichrist / beast"},
                {"id": "res:paul", "label": "Paul / gospel"},
                {"id": "res:hell", "label": "Judgment / hell"},
                {"id": "res:angels", "label": "Angels"},
                {"id": "res:pray", "label": "Prayer"},
                {"id": "res:holy_spirit", "label": "Holy Spirit"},
                {"id": "res:salvation", "label": "Salvation"},
                {"id": "res:overcome", "label": "Overcome sin / holiness"},
                {"id": "res:general", "label": "General teachings"},
                {"id": "start", "label": "Back to main topics"},
            ],
        },
        "salvation_ask": {
            "title": "A relationship with the Father",
            "angel": (
                "God so loved the world that He gave His only begotten Son (John 3:16). "
                "One mediator: Christ Jesus (1 Timothy 2:5). "
                "Confess the Lord Jesus, believe God raised Him from the dead, and you shall be saved (Romans 10:9).\n\n"
                "Do you wish to enter a relationship with the Father through Jesus Christ?"
            ),
            "choices": [
                {"id": "salvation_yes", "label": "Yes"},
                {"id": "salvation_no", "label": "No"},
                {"id": "res:salvation", "label": "Read admin notes on salvation first"},
            ],
        },
        "salvation_no": {
            "title": "Another time",
            "angel": (
                "Maybe some other time. God bless you. "
                "His hand remains open. When you are ready, return — Christ still receives sinners (Luke 15:2)."
            ),
            "choices": [
                {"id": "start", "label": "Continue learning"},
                {"id": "salvation_ask", "label": "I changed my mind"},
                {"id": "closing_love", "label": "End here"},
            ],
        },
        "salvation_yes": {
            "title": "The way of salvation",
            "angel": (
                "1. Admit you have sinned (Romans 3:23; 6:23).\n"
                "2. Believe Jesus died and rose for you (1 Corinthians 15:3–4; Romans 10:9).\n"
                "3. Turn to God — repentance (Acts 3:19).\n"
                "4. Call on His name; receive Him (Romans 10:13; John 1:12).\n\n"
                "Pray: “Lord Jesus, I am a sinner. I believe You died for me and rose again. "
                "I turn from my sin and receive You as Lord and Saviour. Forgive me, make me Yours, fill me with Your Spirit. Amen.”\n\n"
                "Then: read the Word, pray, join a Bible-believing fellowship, be baptized when you can (Acts 2:38–42), "
                "ask for the Spirit’s filling (Luke 11:13; Ephesians 5:18)."
            ),
            "choices": [
                {"id": "pray", "label": "Guide me further in prayer"},
                {"id": "holy_spirit", "label": "Holy Spirit"},
                {"id": "overcome", "label": "Stay free from sin"},
                {"id": "res:salvation", "label": "More admin salvation resources"},
                {"id": "closing_love", "label": "Close with God’s love"},
            ],
        },
        "closing_love": {
            "title": "God’s love for you",
            "angel": (
                "God loves you. He is ever ready to forgive you, keep you, and hold you in righteousness "
                "and communion with Himself through Jesus Christ (Romans 5:8; 1 John 1:9; Jude 24).\n\n"
                "Nothing shall separate us from the love of God in Christ Jesus (Romans 8:38–39).\n\n"
                "Grace be with you. Amen."
            ),
            "choices": [
                {"id": "start", "label": "Begin again"},
                {"id": "salvation_ask", "label": "Respond to God now"},
            ],
        },
        "resource_empty": {
            "title": "No library item yet",
            "angel": (
                "There is no active resource in that shelf yet. "
                "General Admin can add teachings under Admin → Angel resources. "
                "Meanwhile, we can stay in the Scriptures together."
            ),
            "choices": [
                {"id": "library", "label": "Browse other shelves"},
                {"id": "start", "label": "Main topics"},
                {"id": "closing_love", "label": "Finish for now"},
            ],
        },
    }


def load_admin_resources(session: Session, category: Optional[str] = None) -> List[AngelResource]:
    q = select(AngelResource).where(AngelResource.is_active == True)
    if category and category != "general":
        # match category case-insensitive
        rows = session.exec(q.order_by(AngelResource.sort_order, AngelResource.id)).all()
        cat = category.lower().strip()
        filtered = [r for r in rows if (r.category or "general").lower() == cat
                    or cat in (r.category or "").lower()
                    or cat in (r.title or "").lower()]
        if filtered:
            return filtered
        # fallback: any active
        return list(rows)[:20]
    return list(session.exec(q.order_by(AngelResource.sort_order, AngelResource.id)).all())


def format_resource_message(resources: List[AngelResource], shelf: str) -> str:
    if not resources:
        return ""
    parts = [
        f"From your church library (uploaded by General Admin) — shelf: {shelf}:\n"
    ]
    for i, r in enumerate(resources[:8], 1):
        parts.append(f"—— {i}. {r.title} ——")
        if r.summary:
            parts.append(r.summary.strip())
        body = (r.body or "").strip()
        if len(body) > 1200:
            body = body[:1200] + "…"
        if body:
            parts.append(body)
        if r.scripture_refs:
            parts.append(f"Scripture: {r.scripture_refs}")
        if r.source_note:
            parts.append(f"Source: {r.source_note}")
        parts.append("")
    parts.append("These notes support the Word; they do not replace it. Test everything by the Scriptures (Acts 17:11).")
    return "\n".join(parts).strip()


def build_resource_node(session: Session, shelf: str) -> dict:
    resources = load_admin_resources(session, shelf)
    if not resources:
        return builtin_topics()["resource_empty"]
    msg = format_resource_message(resources, shelf)
    choices = [
        {"id": "library", "label": "Other library shelves"},
        {"id": "start", "label": "Main topics"},
        {"id": "salvation_ask", "label": "I want to know God"},
        {"id": "closing_love", "label": "Finish for now"},
    ]
    # deep links to open a single resource
    for r in resources[:6]:
        choices.insert(0, {"id": f"rid:{r.id}", "label": f"Focus: {r.title[:40]}"})
    return {
        "title": f"Library — {shelf}",
        "angel": msg,
        "choices": choices,
    }


def build_single_resource(session: Session, rid: int) -> dict:
    r = session.get(AngelResource, rid)
    if not r or not r.is_active:
        return builtin_topics()["resource_empty"]
    parts = [f"—— {r.title} ——"]
    if r.summary:
        parts.append(r.summary)
    parts.append((r.body or "").strip())
    if r.scripture_refs:
        parts.append(f"Scripture: {r.scripture_refs}")
    if r.source_note:
        parts.append(f"Source: {r.source_note}")
    parts.append("\nWould you like another library item, or shall we return to the Scriptures path?")
    return {
        "title": r.title,
        "angel": "\n\n".join(parts),
        "choices": [
            {"id": f"res:{(r.category or 'general')}", "label": "More in this shelf"},
            {"id": "library", "label": "All shelves"},
            {"id": "start", "label": "Main topics"},
            {"id": "closing_love", "label": "Finish for now"},
        ],
    }


def resolve_topic(session: Session, topic: str) -> dict:
    topics = builtin_topics()
    if topic.startswith("res:"):
        shelf = topic.split(":", 1)[1].strip() or "general"
        return build_resource_node(session, shelf)
    if topic.startswith("rid:"):
        try:
            rid = int(topic.split(":", 1)[1])
        except ValueError:
            return topics["resource_empty"]
        return build_single_resource(session, rid)
    if topic in topics:
        node = dict(topics[topic])
        # Append admin resources teaser into message when available for matching category
        if topic in ("revelation", "antichrist", "paul", "hell", "angels", "pray", "overcome", "holy_spirit", "salvation_ask", "resurrection", "heaven_sin"):
            shelf = {
                "revelation": "revelation",
                "rev_deeper_beast": "antichrist",
                "antichrist": "antichrist",
                "paul": "paul",
                "hell": "hell",
                "angels": "angels",
                "pray": "pray",
                "overcome": "overcome",
                "holy_spirit": "holy_spirit",
                "salvation_ask": "salvation",
                "resurrection": "resurrection",
                "heaven_sin": "heaven",
            }.get(topic, topic)
            extra = load_admin_resources(session, shelf)
            if extra:
                node["angel"] = node["angel"] + (
                    f"\n\n—\nThere are {len(extra)} library note(s) from General Admin on this subject. "
                    f"Choose “Admin library…” below to read them."
                )
        return node
    return topics["start"]


@router.get("/", response_class=HTMLResponse)
async def angel_home(
    request: Request,
    topic: Optional[str] = None,
    session: Session = Depends(get_session),
):
    tid = topic or "start"
    node = resolve_topic(session, tid)
    # count library
    lib_count = len(session.exec(select(AngelResource).where(AngelResource.is_active == True)).all())
    return templates.TemplateResponse(
        "angel/converse.html",
        {
            "request": request,
            "topic_id": tid,
            "title": node.get("title") or "Guide",
            "angel_message": node.get("angel") or "",
            "choices": node.get("choices") or [],
            "library_count": lib_count,
        },
    )


@router.post("/go", response_class=HTMLResponse)
async def angel_go(request: Request, next_topic: str = Form("start")):
    tid = (next_topic or "start").strip()
    return RedirectResponse(url=f"/angel/?topic={tid}", status_code=303)


# ----- General Admin: Angel resources CRUD -----
@router.get("/admin/resources", response_class=HTMLResponse)
async def admin_angel_resources(
    request: Request,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(AngelResource).order_by(AngelResource.sort_order, AngelResource.id.desc())).all()
    return templates.TemplateResponse(
        "admin/angel_resources.html",
        {"request": request, "user": user, "resources": rows},
    )


@router.post("/admin/resources/add")
async def admin_angel_add(
    request: Request,
    title: str = Form(...),
    category: str = Form("general"),
    summary: str = Form(""),
    body: str = Form(""),
    scripture_refs: str = Form(""),
    source_note: str = Form(""),
    sort_order: int = Form(0),
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    r = AngelResource(
        title=title.strip(),
        category=(category or "general").strip().lower(),
        summary=summary.strip() or None,
        body=body.strip(),
        scripture_refs=scripture_refs.strip() or None,
        source_note=source_note.strip() or None,
        sort_order=sort_order or 0,
        is_active=True,
        created_by=user.id,
        updated_at=datetime.utcnow(),
    )
    session.add(r)
    session.commit()
    return RedirectResponse("/angel/admin/resources", status_code=303)


@router.post("/admin/resources/{rid}/toggle")
async def admin_angel_toggle(
    rid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    r = session.get(AngelResource, rid)
    if not r:
        raise HTTPException(404)
    r.is_active = not r.is_active
    r.updated_at = datetime.utcnow()
    session.add(r)
    session.commit()
    return RedirectResponse("/angel/admin/resources", status_code=303)


@router.post("/admin/resources/{rid}/delete")
async def admin_angel_delete(
    rid: int,
    user: User = Depends(require_roles(UserRole.general_admin)),
    session: Session = Depends(get_session),
):
    r = session.get(AngelResource, rid)
    if r:
        session.delete(r)
        session.commit()
    return RedirectResponse("/angel/admin/resources", status_code=303)


# ---------- Always-on Angel answer API (portal voice + library + lead words) ----------
LEAD_WORDS = """
abaddon abomination abraham adoption adultery advocate affliction afterlife altar amen angels anointing apostles ark ascension atonement authority awakening assurance antichrist armageddon baptism beatitudes belief bible blasphemy blessing blood born-again bread bride brotherhood atonement baptism belief christ christian church circumcision commandments communion confession conscience consecration covenant creation creator cross crucifixion crown conversion conviction comforter daniel david death deacon deliverance demons discipleship discipline doctrine dominion doubt dreams election elijah emmanuel end-times eternal-life evangelism exodus faith faithfulness fall father fasting fear fellowship forgiveness free-will fruit gabriel gentiles glory gospel grace great-commission tribulation god godhead shepherd gifts genealogy gehenna hades hell heaven hebrew holiness hope hosanna humility healing heresy high-priest immanuel incarnation iniquity inspiration intercession israel idolatry indwelling inheritance isaiah jehovah jerusalem jesus jews judgment justification jubilee joy kingdom king knowledge lamb law leviticus life light lord love lucifer last-days messiah moses manna marriage mercy miracles ministry melchisedec millennium mediator name nazarene new-birth new-covenant new-jerusalem noah obedience offering omnipotence original-sin overcoming passover pentecost prayer praise predestination prophecy prophet priest propitiation purity providence psalms paul peter paradise parables persecution patience peace promise rapture redemption regener regeneration repentance resurrection revelation righteousness sabbath sacrifice salvation sanctification sanctuary satan scripture second-coming serpent sin son spirit spiritual-gifts stewardship saints shepherd sermon sinai saviour sovereignty tabernacle temple tithes torah transfiguration trinity tribulation truth thanksgiving temptation teacher tongues tree trumpets unbelief unclean unity virgin victory vine vision vow walk warfare watchfulness word worship wrath wisdom wilderness will yahweh yoke zeal zion
""".split()

def _match_resources(session: Session, q: str, limit: int = 5):
    qn = (q or "").lower()
    rows = session.exec(select(AngelResource).where(AngelResource.is_active == True)).all()
    scored = []
    for r in rows:
        blob = " ".join([
            r.title or "", r.category or "", r.summary or "",
            (r.body or "")[:500], r.scripture_refs or "", r.source_note or ""
        ]).lower()
        score = 0
        for token in qn.replace(",", " ").split():
            if len(token) < 3:
                continue
            if token in blob:
                score += 2
            if token in (r.title or "").lower():
                score += 3
            if token in (r.category or "").lower():
                score += 2
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def _lead_hits(q: str):
    qn = (q or "").lower()
    hits = []
    for w in LEAD_WORDS:
        w2 = w.replace("-", " ")
        if w2 in qn or w.replace("-", "") in qn.replace(" ", ""):
            hits.append(w)
    return hits[:12]


@router.post("/api/answer")
async def angel_answer_api(request: Request, session: Session = Depends(get_session)):
    """JSON body: { "text": "user utterance after angel wake" }"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = (data.get("text") or "").strip()
    if not text:
        return {"ok": True, "mode": "idle", "speech": "", "chunks": []}

    low = text.lower().strip()
    # quit phrases handled client-side mostly
    hits = _lead_hits(low)
    resources = _match_resources(session, low)

    parts = []
    if resources:
        parts.append("From your church library:")
        for r in resources[:3]:
            piece = (r.summary or r.body or r.title or "").strip()
            if len(piece) > 500:
                piece = piece[:500] + "…"
            parts.append(f"{r.title}. {piece}")
            if r.scripture_refs:
                parts.append(f"Scripture: {r.scripture_refs}")
    if hits and not resources:
        parts.append(
            f"You asked about {', '.join(hits[:5])}. "
            "Search the Scriptures; they testify of Christ (John 5:39). "
            "Hold the Word as your light (Psalm 119:105)."
        )
    if hits and resources:
        parts.append(f"Lead themes heard: {', '.join(hits[:6])}.")

    # gentle gospel tether for salvation-ish words
    if any(x in low for x in ("saved", "salvation", "jesus", "repent", "born again", "gospel")):
        parts.append(
            "The gospel: Christ died for our sins, was buried, and rose again (1 Corinthians 15:3-4). "
            "If you confess the Lord Jesus and believe God raised Him from the dead, you shall be saved (Romans 10:9)."
        )

    if not parts:
        parts.append(
            "I am listening. Ask using a clear Bible topic after saying Angel — "
            "for example faith, prayer, holiness, resurrection, or a book like John chapter three. "
            "You can also open the Bible panel and say explain."
        )

    full = " ".join(parts)
    # chunk for ~60 second speech segments (approx 12-14 words/sec spoken slower ~140 wpm => ~140 words/min => ~140 words per 60s)
    words = full.split()
    chunk_size = 130
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i + chunk_size]))
    return {
        "ok": True,
        "mode": "answer",
        "speech": full,
        "chunks": chunks or [full],
        "lead_hits": hits,
        "resource_count": len(resources),
    }
