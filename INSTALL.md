# Churchgate Hero Animation — Home + Login + Member Social

Plays the **voice-note animation** on:

1. **Home page** — always (even when video links exist; can sit above or replace the video block)
2. **Login page** — replaces the video area
3. **Member page social media area** — strip at the top of the social/feed section

Does **not** delete uploads, books, or database data. Only adds static files + template includes.

---

## 1. Copy static files

```
static/churchgate-default-hero.html
static/Churchgate_Marketing_VoiceNote.mp3
```

Both must be in `static/` (same folder).

---

## 2. Copy partials (optional but recommended)

```
templates/partials/churchgate_hero.html
templates/partials/churchgate_hero_login.html
templates/partials/churchgate_hero_social.html
```

---

## 3. Home page — always show animation

Open your home template (often `templates/home.html`, `templates/index.html`, or `templates/public/home.html`).

**A) Prefer animation over video (recommended)**  
Find the video / iframe block and **replace** it with:

```html
{% include "partials/churchgate_hero.html" %}
```

**B) Keep video links AND show animation above them**

```html
{% include "partials/churchgate_hero.html" %}
{# existing video block can stay below if you still want it #}
```

So the animation plays **even when** home has video links.

---

## 4. Login page — replace video

Open login template (often `templates/auth/login.html`, `templates/login.html`, or `templates/member/login.html`).

Find any `<video>`, YouTube iframe, or “promo video” block and **replace** with:

```html
{% include "partials/churchgate_hero_login.html" %}
```

If there is no video, paste that include near the top of the login card / hero column.

---

## 5. Member social media area

Open the member dashboard / social template (often `templates/member/home.html`, `templates/member/social.html`, or `templates/member/dashboard.html`).

At the **top of the social / feed / posts** section, add:

```html
{% include "partials/churchgate_hero_social.html" %}
```

Example:

```html
<section class="social-feed">
  {% include "partials/churchgate_hero_social.html" %}
  {# existing posts / social widgets #}
</section>
```

---

## 6. Deploy (GitHub → Render)

```bash
git add static/churchgate-default-hero.html \
        static/Churchgate_Marketing_VoiceNote.mp3 \
        templates/partials/churchgate_hero.html \
        templates/partials/churchgate_hero_login.html \
        templates/partials/churchgate_hero_social.html
# plus the 3 templates you edited (home, login, member social)
git commit -m "Add Churchgate hero animation to home, login, and member social"
git push
```

Render will redeploy. No migration, no data wipe.

---

## 7. Verify

| Page | What you should see |
|------|---------------------|
| Home | Animation + voice (with or without other video links) |
| Login | Animation instead of old video |
| Member → social area | Animation strip above the feed |

Direct URL check:  
`https://YOUR-APP.onrender.com/static/churchgate-default-hero.html`

---

## Notes

- Mobile browsers may require one tap on ▶ before audio plays.
- To hide the animation later, remove the `{% include %}` lines only; leave static files if you want.
