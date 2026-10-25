from pathlib import Path
import re, shutil

ROOT = Path(__file__).resolve().parent
ROUTER = ROOT / 'app' / 'routers' / 'kwealth.py'
BOOKS = ROOT / 'app' / 'templates' / 'kwealth' / 'books.html'
READER = ROOT / 'app' / 'templates' / 'kwealth' / 'reading_room.html'

if not ROUTER.exists():
    raise SystemExit(f'ERROR: {ROUTER} not found. Run this script from the OneChurchgate project root (or place the script there).')
if not BOOKS.exists() or not READER.exists():
    raise SystemExit('ERROR: Required Kwealth book templates are missing.')

text = ROUTER.read_text(encoding='utf-8')
backup = ROUTER.with_suffix('.py.reading-room-backup')
if not backup.exists():
    shutil.copy2(ROUTER, backup)

# Find the existing member books route and give the SAME handler a second URL.
pat = re.compile(r'(?m)^(\s*@router\.get\(\s*[\"\'])(/member/kwealth/books)([\"\'][^\n]*\)\s*)$')
m = pat.search(text)
if not m:
    # Some versions use a router prefix and a shorter route.
    pat = re.compile(r'(?m)^(\s*@router\.get\(\s*[\"\'])(/kwealth/books)([\"\'][^\n]*\)\s*)$')
    m = pat.search(text)
if not m:
    raise SystemExit('ERROR: Could not locate the existing Kwealth books GET route. No router changes made.')

route_line = m.group(0)
indent = m.group(1)[:-len(m.group(1).lstrip())] if m.group(1).strip() else ''
# Preserve response_class/dependencies/etc. from the existing route while changing only the path.
new_route = route_line.replace(m.group(2), m.group(2) + '/reading-room', 1)
if new_route not in text:
    text = text[:m.start()] + route_line + new_route + text[m.end():]

# Make the existing handler render the dedicated template only for the dedicated path.
old = 'templates.TemplateResponse("kwealth/books.html"'
if old not in text:
    old = "templates.TemplateResponse('kwealth/books.html'"
if old not in text:
    raise SystemExit('ERROR: Could not locate the books TemplateResponse in the existing handler. Router route was not safely completed.')
quote = '"' if 'templates.TemplateResponse("kwealth/books.html"' in text else "'"
expr = f'templates.TemplateResponse("kwealth/reading_room.html" if request.url.path.rstrip("/").endswith("/reading-room") else "kwealth/books.html"'
if quote == "'":
    expr = "templates.TemplateResponse('kwealth/reading_room.html' if request.url.path.rstrip('/').endswith('/reading-room') else 'kwealth/books.html'"
text = text.replace(old, expr, 1)
ROUTER.write_text(text,encoding='utf-8')
print('Applied dedicated Reading Room route and template selection.')
print(f'Backup: {backup}')
