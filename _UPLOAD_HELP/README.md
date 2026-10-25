# Registration confirm email + reset link + Contact Knowsoft

## Behaviour

### New registration
1. User submits `/join`
2. Email sent **From: info@knowsoft.org.uk** (when MAIL_* is set):
   > You are receiving this email because you have sent a registration request with Knowsoft Churchgate.
   > Click the link below to confirm your registration.
3. User clicks link → `/auth/confirm-registration?email=…&token=…`
4. **Non-affiliate or Knowsoft church** → email confirmed **and** `approval_status=approved` → can log in with password
5. **Any other church** → email confirmed; membership stays **pending** until church admin approves

### Password reset
- `/auth/forgot` sends code (5 min) + **Open password reset form** link → `/auth/reset?email=…`

### Contact
- Home page floating **Contact Knowsoft**
- Login page **Contact Knowsoft — info@knowsoft.org.uk**

## Files
- app/routers/mail_auth.py
- app/routers/members.py
- templates/auth/confirm_registration.html
- templates/auth/login.html
- templates/members/join.html
- templates/members/pending.html
- templates/index.html

Requires MAIL_* env on Render.
