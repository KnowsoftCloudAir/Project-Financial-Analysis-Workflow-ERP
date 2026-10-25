# If animation is not displaying

## 1. Check static files exist on the server
Open in browser:
- https://YOUR-APP.onrender.com/static/churchgate-default-hero.html
- https://YOUR-APP.onrender.com/static/Churchgate_Marketing_VoiceNote.mp3

If either 404s, files were not copied into `static/` or static mounting is wrong.

## 2. FastAPI static mount
In main.py you should have something like:
```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```
Files must live in the project `static/` folder that Render deploys.

## 3. Template include
Home / login / member must include:
```html
{% include "partials/churchgate_hero.html" %}
```
(or login/social partial). If the include path is wrong, Jinja will error or skip.

## 4. iframe blocked?
Some CSP headers block iframes. Temporarily open the hero URL directly (step 1).

## 5. Hard refresh
Ctrl+Shift+R after deploy so old cached HTML is not used.
