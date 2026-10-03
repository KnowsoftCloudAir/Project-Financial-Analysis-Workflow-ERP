# Apply OneChurchgate password reset & registration email to CONTRAconnect

This mirrors **KnowsoftCloudAir/OneChurchgate**:

| Feature | Churchgate behaviour | ERP after patch |
|--------|----------------------|-----------------|
| Mail transport | SMTP env (`MAIL_HOST`, `MAIL_USER`, `MAIL_PASSWORD`, `MAIL_FROM`) | Same via `auth_mail.py` |
| Branding | Dark HTML shell, teal button | Same |
| Reset request | Email required; error if not registered | Same message style |
| Reset payload | **6-digit code** + **link** with `?email=&code=` | Same |
| Code TTL | **5 minutes** | Same (`OTP_MINUTES`) |
| Reset form | email + new password + confirm + **code** | Same |
| After reset | Confirmation email; code/link one-time | Same |
| Registration | Confirm email with **link + token** (48h) | Same (`CONFIRM_HOURS`) |

---

## 1. Files to add

```
auth_mail.py          → project root (next to server.py)
```

Templates (add or replace):

```
templates/forgot_password.html
templates/reset_password.html
templates/confirm_registration.html   (new)
```

---

## 2. Env vars (Render / .env) — same names as OneChurchgate

```
MAIL_HOST=smtp.example.com
MAIL_PORT=587
MAIL_USER=your@knowsoft.org.uk
MAIL_PASSWORD=...
MAIL_FROM=noreply@knowsoft.org.uk
MAIL_FROM_NAME=CONTRAconnect
PUBLIC_BASE_URL=https://your-app.onrender.com
CONTACT_EMAIL=info@knowsoft.org.uk

# Optional
MAIL_DISABLED=1          # log only, do not send (local dev)
OTP_MINUTES=5
CONFIRM_HOURS=48
REQUIRE_EMAIL_OTP=0      # set 1 to require OTP after password login
```

---

## 3. Patch `server.py`

### 3a. Imports (near top)

```python
from auth_mail import (
    send_mail, branded, public_base, app_base_from_request,
    issue_challenge, check_challenge, register_email_challenge_model,
    send_password_reset_email, send_registration_confirm_email,
    send_password_reset_success_email, OTP_MINUTES, CONFIRM_HOURS,
)
```

### 3b. After `db = SQLAlchemy(app)` / models section

```python
EmailChallenge = register_email_challenge_model(db)
```

### 3c. Allow new routes in onboarding gate (`_before_request_init_db`)

Add to the skip list:

```python
'forgot_password', 'reset_password', 'confirm_registration', 'onboarding',
```

### 3d. Replace `forgot_password` and `reset_password`

```python
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('This email is not registered with CONTRAconnect.', 'danger')
            return render_template('forgot_password.html', email=email, sent=False)
        code = issue_challenge(db, EmailChallenge, email, 'reset', user_id=user.id)
        mailed = send_password_reset_email(email, code, request=request)
        if not mailed:
            # Dev fallback: still show code/link when SMTP missing
            base = app_base_from_request(request)
            link = f"{base}/reset-password?email={email}&code={code}"
            flash(
                'Email could not be sent (check MAIL_HOST). '
                f'Dev fallback — code: {code} · link: {link}',
                'warning',
            )
        else:
            flash(
                f'If mail is configured, a reset code was sent to {email}. '
                f'The code expires in {OTP_MINUTES} minutes.',
                'success',
            )
        try:
            log_activity('password_reset_request', email, user=user)
        except Exception:
            pass
        return render_template('forgot_password.html', email=email, sent=True)
    return render_template('forgot_password.html', email='', sent=False)


@app.route('/reset-password', methods=['GET', 'POST'])
@app.route('/reset-password/<token>', methods=['GET', 'POST'])  # legacy token URL
def reset_password(token=None):
    """Churchgate-style: email + code + new password (+ optional legacy path token)."""
    email = (request.args.get('email') or request.form.get('email') or '').strip().lower()
    code = (request.args.get('code') or request.form.get('code') or '').strip()

    # Legacy: long token in path still works once
    if token and not code:
        prt = PasswordResetToken.query.filter_by(token=token, used=False).first()
        if prt and prt.expires_at >= datetime.utcnow():
            user = db.session.get(User, prt.user_id)
            if user:
                email = user.email

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        code = request.form.get('code', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('confirm_password') or request.form.get('password2', '')

        if password != password2:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', email=email, code=code)

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('This email is not registered with CONTRAconnect.', 'danger')
            return render_template('reset_password.html', email=email, code=code)

        strong = _is_admin_role(user.role)
        ok, msg = validate_password_strength(
            password, min_length=10 if strong else 8, require_strong=strong
        )
        if not ok:
            flash(msg, 'danger')
            return render_template('reset_password.html', email=email, code=code)

        row = check_challenge(db, EmailChallenge, email, 'reset', code)
        # Legacy token fallback
        if not row and token:
            prt = PasswordResetToken.query.filter_by(token=token, used=False).first()
            if prt and prt.expires_at >= datetime.utcnow() and prt.user_id == user.id:
                prt.used = True
                row = prt

        if not row:
            flash(
                f'Invalid or expired code. Codes expire in {OTP_MINUTES} minutes. '
                'Request a new link.',
                'danger',
            )
            return render_template('reset_password.html', email=email, code='')

        user.set_password(password)
        user.password_changed_at = datetime.utcnow()
        db.session.commit()
        try:
            send_password_reset_success_email(email)
            log_activity('password_reset_complete', email, user=user)
        except Exception:
            pass
        flash('Your password has been reset. You can sign in now.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', email=email, code=code)


@app.route('/confirm-registration', methods=['GET', 'POST'])
def confirm_registration():
    email = (request.args.get('email') or request.form.get('email') or '').strip().lower()
    token = (request.args.get('token') or request.form.get('token') or '').strip()
    if not email or not token:
        flash('Invalid confirmation link.', 'danger')
        return render_template('confirm_registration.html', ok=False, message='Missing email or token.')
    row = check_challenge(db, EmailChallenge, email, 'register_confirm', token)
    if not row:
        flash('This confirmation link is invalid or has expired.', 'danger')
        return render_template(
            'confirm_registration.html', ok=False,
            message='Link expired or already used. Register again or contact support.',
        )
    user = User.query.filter_by(email=email).first()
    if not user:
        return render_template(
            'confirm_registration.html', ok=False,
            message='Account not found.',
        )
    # Mark email confirmed; keep is_active for admin approval if that is your policy
    if hasattr(user, 'onboarding_status'):
        if user.onboarding_status in (None, 'pending_profile', 'pending_approval'):
            pass  # still needs admin activation
    # Optional flag if you add email_verified column later
    try:
        if hasattr(user, 'email_verified'):
            user.email_verified = True
        db.session.commit()
    except Exception:
        db.session.rollback()
    return render_template(
        'confirm_registration.html', ok=True,
        message=(
            'Email confirmed. An administrator will activate your account if required. '
            'You may try signing in.'
        ),
    )
```

### 3e. Inside `register()` after successful `db.session.commit()`

```python
            token = issue_challenge(
                db, EmailChallenge, email, 'register_confirm', user_id=user.id
            )
            mailed = send_registration_confirm_email(
                email, full_name, token, request=request
            )
            if mailed:
                flash(
                    'Registration submitted. Check your email to confirm, '
                    'then an administrator will activate your account.',
                    'success',
                )
            else:
                flash(
                    'Registration submitted. Confirmation email could not be sent '
                    '(check MAIL_*). An administrator will activate your account.',
                    'warning',
                )
            return redirect(url_for('login'))
```

---

## 4. Template requirements

### `forgot_password.html`
- Form POST email
- Show “sent” state when `sent` is true
- Link to login

### `reset_password.html`
- Fields: **email**, **code**, **password**, **confirm_password**
- Prefill `email` and `code` from query string when opened from the email link

### `confirm_registration.html`
- Show success or error from `ok` / `message`

---

## 5. Behaviour summary (user-facing)

**Forgot password**

1. User enters email → if not registered: *“This email is not registered with CONTRAconnect.”*
2. If registered: email with **6-digit code** + button/link to `/reset-password?email=…&code=…`
3. Code expires in **5 minutes**
4. Form: email, new password, confirm, code → submit → success email → login

**Registration**

1. User registers → account created (often pending admin activation)
2. Email: *Confirm your CONTRAconnect registration* with link valid **48 hours**
3. User opens `/confirm-registration?email=…&token=…` → confirmation page

This matches OneChurchgate’s email, link, and code model.
