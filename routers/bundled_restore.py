"""Restore from bundled backup JSON once (or when forced), then keep GA password."""
from pathlib import Path
from datetime import datetime, date
import json
from sqlmodel import Session, select
from app.database import engine
from app.models import (
    User, UserRole, ChurchUnit, ChurchMember, WeeklyStat, SpecialProgram,
    ProgramPhoto, MusicLink, PastorMessage, FocusGroup, FocusGroupMember,
    FocusGroupMessage, MemberSubscription, SubscriptionSettings, DistrictMessage,
    SystemAnnouncement, AppConfig,
)
from app.auth import get_password_hash

BUNDLE = Path(__file__).resolve().parent / "data" / "bundled_backup.json"
MARKER = Path(__file__).resolve().parent / "data" / ".bundled_restored"

MODEL_MAP = {
    "churchunit": ChurchUnit,
    "user": User,
    "churchmember": ChurchMember,
    "weeklystat": WeeklyStat,
    "specialprogram": SpecialProgram,
    "programphoto": ProgramPhoto,
    "musiclink": MusicLink,
    "pastormessage": PastorMessage,
    "focusgroup": FocusGroup,
    "focusgroupmember": FocusGroupMember,
    "focusgroupmessage": FocusGroupMessage,
    "membersubscription": MemberSubscription,
    "subscriptionsettings": SubscriptionSettings,
    "districtmessage": DistrictMessage,
    "systemannouncement": SystemAnnouncement,
    "appconfig": AppConfig,
}

GA_EMAIL = "admin@knowsoft.com"
GA_PASSWORD = "Knowsoft#GA2026!"


def _parse_val(v):
    if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and ("T" in v or len(v) == 10):
        try:
            if "T" in v:
                return datetime.fromisoformat(v.replace("Z", ""))
            return date.fromisoformat(v[:10])
        except Exception:
            return v
    return v

def _coerce(model, row: dict) -> dict:
    fields = {}
    for k, v in row.items():
        if not hasattr(model, k):
            continue
        fields[k] = _parse_val(v)
    return fields


def restore_bundled_backup(force: bool = False) -> int:
    if not BUNDLE.exists():
        print("ℹ️ No bundled backup file")
        return 0
    if MARKER.exists() and not force:
        print("ℹ️ Bundled backup already applied (marker present)")
        return 0
    try:
        payload = json.loads(BUNDLE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ Bundled backup read failed: {e}")
        return 0
    tables = payload.get("tables") or {}
    restored = 0
    with Session(engine) as session:
        for name, rows in tables.items():
            model = MODEL_MAP.get(name)
            if not model or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    pk = row.get("id")
                    obj = session.get(model, pk) if pk is not None else None
                    data = _coerce(model, row)
                    if obj:
                        for k, v in data.items():
                            if k == "id":
                                continue
                            try:
                                setattr(obj, k, v)
                            except Exception:
                                pass
                        session.add(obj)
                    else:
                        session.add(model(**data))
                    restored += 1
                except Exception as e:
                    print(f"restore skip {name}: {e}")
            try:
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"commit {name}: {e}")
        # ALWAYS privileged General Admin login after restore
        admin = session.exec(select(User).where(User.email == GA_EMAIL)).first()
        if not admin:
            admin = User(
                email=GA_EMAIL,
                hashed_password=get_password_hash(GA_PASSWORD),
                full_name="Knowsoft General Admin",
                role=UserRole.general_admin,
                is_active=True,
            )
        else:
            admin.hashed_password = get_password_hash(GA_PASSWORD)
            admin.role = UserRole.general_admin
            admin.is_active = True
            if hasattr(admin, "must_change_password"):
                admin.must_change_password = False
        session.add(admin)
        session.commit()
        print(f"✅ Bundled backup restored ({restored} rows)")
        print(f"✅ SPECIAL General Admin: {GA_EMAIL} / {GA_PASSWORD}")
    try:
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(datetime.utcnow().isoformat())
    except Exception:
        pass
    return restored


def force_general_admin_password():
    """Call on every boot so GA always works with the privileged password."""
    with Session(engine) as session:
        admin = session.exec(select(User).where(User.email == GA_EMAIL)).first()
        if not admin:
            admin = User(
                email=GA_EMAIL,
                hashed_password=get_password_hash(GA_PASSWORD),
                full_name="Knowsoft General Admin",
                role=UserRole.general_admin,
                is_active=True,
            )
        else:
            admin.hashed_password = get_password_hash(GA_PASSWORD)
            admin.role = UserRole.general_admin
            admin.is_active = True
            if hasattr(admin, "must_change_password"):
                admin.must_change_password = False
        session.add(admin)
        session.commit()
        print(f"✅ Privileged GA login ready: {GA_EMAIL} / {GA_PASSWORD}")
