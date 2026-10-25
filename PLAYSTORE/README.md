# Churchgate on Play Store + knowsoft.org.uk

Public site: **https://knowsoft.org.uk**  
Privacy URL (must stay live): **https://knowsoft.org.uk/privacy**

## Three-way sign-in

1. Password  
2. Email OTP (12 minutes)  
3. Backup code (saved codes, or second emailed code on first use)

Sample accounts (`is_sample_account`) skip OTP so demos still work.

Set on the host:

```
PUBLIC_BASE_URL=https://knowsoft.org.uk
MAIL_HOST=...
MAIL_PORT=587
MAIL_USER=...
MAIL_PASSWORD=...
MAIL_FROM=noreply@knowsoft.org.uk
MAIL_FROM_NAME=Churchgate
REQUIRE_EMAIL_OTP=1
COOKIE_SECURE=1
```

Admin mail to members: `/auth/admin-mail`  
Forgot password: `/auth/forgot`

## Play listing

- App name: Churchgate  
- Package: `com.knowsoft.churchgate`  
- Keep **your current store icon** if it already reads as Churchgate. Domain change to knowsoft.org.uk does **not** require a new icon. Only replace the icon if the old one still says Render / Contract Connect / a different product.  
- Feature graphic 1024×500, 512 icon, 2–8 screenshots from the live site.  
- Data safety: email, name, photos, app activity.  
- Payments: until Play Billing is wired, keep the Play build free or sell off-store.

## Deploy without data loss

Postgres + persistent disk. Do not wipe the database. Admin passwords are not reset on boot.
