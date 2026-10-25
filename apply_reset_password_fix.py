from pathlib import Path
import os, smtplib, hashlib, hmac, shutil
from email.message import EmailMessage

ROOT = Path(__file__).resolve().parent
AUTH = ROOT / "app" / "routers" / "auth.py"
SRC_TEMPLATE = ROOT / "templates" / "auth" / "reset_password.html"
DST_TEMPLATE = ROOT / "app" / "templates" / "auth" / "reset_password.html"

if not AUTH.exists():
    raise SystemExit("Run this script from the OneChurchgate repository root.")

src = AUTH.read_text(encoding="utf-8")

if "import smtplib" not in src:
    marker = "from pathlib import Path\n"
    if marker not in src:
        raise SystemExit("Could not find the import section in app/routers/auth.py.")
    src = src.replace(marker, marker + "import os\nimport smtplib\nimport hashlib\nimport hmac\nfrom email.message import EmailMessage\n", 1)

block = r'''
# === KNOWSOFT PASSWORD RESET FIX BEGIN ===
def _reset_secret():
    secret = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET_KEY") or os.getenv("APP_SECRET_KEY") or ""
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured")
    return secret

def _reset_code(email):
    window = int(datetime.utcnow().timestamp() // 300)
    raw = f"churchgate-password-reset|{email.strip().lower()}|{window}".encode()
    digest = hmac.new(_reset_secret().encode(), raw, hashlib.sha256).hexdigest()
    return str(int(digest[:12], 16) % 1000000).zfill(6)

def _send_reset_code_email(email, code):
    host = os.getenv("SMTP_HOST") or os.getenv("MAIL_SERVER")
    port = int(os.getenv("SMTP_PORT") or os.getenv("MAIL_PORT") or "587")
    username = os.getenv("SMTP_USERNAME") or os.getenv("MAIL_USERNAME")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("MAIL_PASSWORD")
    sender = os.getenv("SMTP_FROM") or os.getenv("MAIL_FROM") or username
    if not host or not sender:
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["Subject"] = "Churchgate password reset code"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Your Churchgate password reset verification code is: {code}\n\nThis code expires in 5 minutes. If you did not request a password reset, ignore this email.")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() not in {"0","false","no"}
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls: smtp.starttls()
        if username and password: smtp.login(username, password)
        smtp.send_message(msg)

@router.get("/forgot", response_class=HTMLResponse)
async def forgot_password_page_compat(request: Request):
    return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": "", "error": None, "success": None})

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": "", "error": None, "success": None})

@router.post("/send-reset-code", response_class=HTMLResponse)
async def send_reset_code(request: Request, email: str = Form(...), session: Session = Depends(get_session)):
    email = (email or "").strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    generic = "If the email is registered, a verification code has been sent. Please check your inbox."
    if not user:
        return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": None, "success": generic})
    try:
        _send_reset_code_email(email, _reset_code(email))
    except Exception as exc:
        print(f"[Churchgate password reset] email send failed: {exc}")
        return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": "We could not send the verification code. Please try again later.", "success": None}, status_code=500)
    return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": None, "success": generic})

@router.post("/reset", response_class=HTMLResponse)
async def reset_password_submit_fixed(request: Request, email: str = Form(...), code: str = Form(...), password: str = Form(...), password2: str = Form(...), session: Session = Depends(get_session)):
    email = (email or "").strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not hmac.compare_digest((code or "").strip(), _reset_code(email)):
        return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": "Invalid or expired verification code. Please request a new code.", "success": None}, status_code=400)
    if password != password2:
        return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": "The two new passwords do not match.", "success": None}, status_code=400)
    strength_error = validate_password_strength(password)
    if strength_error:
        return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": email, "error": strength_error, "success": None}, status_code=400)
    db_user = session.get(User, user.id)
    db_user.hashed_password = get_password_hash(password)
    if hasattr(db_user, "session_version"):
        db_user.session_version = int(getattr(db_user, "session_version", 0) or 0) + 1
    session.add(db_user)
    session.commit()
    return RedirectResponse("/auth/login?reset=success", status_code=303)
# === KNOWSOFT PASSWORD RESET FIX END ===
'''

if "KNOWSOFT PASSWORD RESET FIX BEGIN" not in src:
    needle = '@router.get("/change-password", response_class=HTMLResponse)'
    if needle not in src:
        raise SystemExit("Could not find the change-password route.")
    src = src.replace(needle, block + "\n" + needle, 1)

old = "\n".join([
    '@router.get("/forgot-password", response_class=HTMLResponse)',
    'async def forgot_password_page(request: Request):',
    '    return RedirectResponse("/auth/forgot", status_code=303)',
    '',
    '@router.post("/forgot-password", response_class=HTMLResponse)',
    'async def forgot_password_submit(request: Request):',
    '    return RedirectResponse("/auth/forgot", status_code=303)',
    ''
])
if old in src:
    new = "\n".join([
        '@router.get("/forgot-password", response_class=HTMLResponse)',
        'async def forgot_password_page_fixed_alias(request: Request):',
        '    return templates.TemplateResponse("auth/reset_password.html", {"request": request, "email": "", "error": None, "success": None})',
        ''
    ])
    src = src.replace(old, new, 1)

AUTH.write_text(src, encoding="utf-8")
DST_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC_TEMPLATE, DST_TEMPLATE)
print("Password-reset fix applied.")
