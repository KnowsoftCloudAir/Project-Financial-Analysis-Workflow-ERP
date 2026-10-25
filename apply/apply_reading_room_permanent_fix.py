from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
# Run from repo root OR place this script in repo root.
if not (ROOT / 'app').exists():
    raise SystemExit('ERROR: Put this script in the OneChurchgate repository root (the folder containing app/).')

books = ROOT / 'app' / 'templates' / 'kwealth' / 'books.html'
reader = ROOT / 'app' / 'templates' / 'kwealth' / 'reading_room.html'
router = ROOT / 'app' / 'routers' / 'kwealth.py'

for p in (books, router):
    if not p.exists():
        raise SystemExit(f'ERROR: Expected file not found: {p}')

# The repository already has a dedicated Reading Room. Do not overwrite it.
if not reader.exists():
    raise SystemExit(
        'ERROR: app/templates/kwealth/reading_room.html is missing. '
        'This script deliberately refuses to manufacture a partial reader.'
    )

b = books.read_text(encoding='utf-8')
r = reader.read_text(encoding='utf-8')
rt = router.read_text(encoding='utf-8')

# 1) Fix the floating menu / settings panel ID mismatch everywhere in the two templates.
#    The real settings panel is panelTools.
b2 = b.replace('getElementById(\'toolsPanel\')', 'getElementById(\'panelTools\')')
b2 = b2.replace('getElementById("toolsPanel")', 'getElementById("panelTools")')
b2 = b2.replace('#toolsPanel', '#panelTools')

r2 = r.replace('getElementById(\'toolsPanel\')', 'getElementById(\'panelTools\')')
r2 = r2.replace('getElementById("toolsPanel")', 'getElementById("panelTools")')
r2 = r2.replace('#toolsPanel', '#panelTools')

# 2) Ensure the dedicated Reading Room has the required navigation links.
#    If they are already present, leave them alone.
if 'href="/member/kwealth/books"' not in r2 or '← Back to Book Library' not in r2:
    marker = '<div id="app">'
    nav = '''<div style="max-width:72rem;margin:0 auto;padding:12px 14px 0;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
    <div style="color:#f8fafc;font-family:Georgia,serif;font-size:15px;font-weight:800;">📖 Reading Room</div>
    <div class="reader-nav" style="margin:0;">
      <a href="/member/kwealth/books" class="reader-back">← Back to Book Library</a>
      <a href="/member/kwealth" class="reader-back secondary">← Kwealth</a>
    </div>
  </div>
</div>
'''
    if marker not in r2:
        raise SystemExit('ERROR: Could not find Reading Room app marker.')
    r2 = r2.replace(marker, nav + marker, 1)

# 3) Replace the unconditional "hide settings" initialization with a book-aware state.
old = '''    $('panelTools').style.display = 'none';
    $('panelTools').dataset.open = '0';
    var toolsBtn = $('btnTools');
    if (toolsBtn) { toolsBtn.classList.remove('on'); toolsBtn.setAttribute('aria-expanded', 'false'); }
'''
new = '''    // READING_ROOM_SETTINGS_PERMANENT_FIX:
    // The dedicated Reading Room must expose its settings when a book is open.
    // Keep the Settings button as a clean toggle so the panel can still be collapsed.
    (function initReadingSettings() {
      var panel = document.getElementById('panelTools');
      var toolsBtn = document.getElementById('btnTools');
      if (!panel) return;
      var hasBook = !!(state && state.bookId) || !!new URLSearchParams(window.location.search).get('book_id');
      if (hasBook) {
        panel.style.display = 'block';
        panel.dataset.open = '1';
        if (toolsBtn) {
          toolsBtn.classList.add('on');
          toolsBtn.setAttribute('aria-expanded', 'true');
        }
      } else {
        panel.style.display = 'none';
        panel.dataset.open = '0';
        if (toolsBtn) {
          toolsBtn.classList.remove('on');
          toolsBtn.setAttribute('aria-expanded', 'false');
        }
      }
    })();
'''
if old in r2:
    r2 = r2.replace(old, new, 1)
else:
    # If a prior patch changed the exact block, enforce the same behavior before the keyboard handler.
    if 'READING_ROOM_SETTINGS_PERMANENT_FIX' not in r2:
        needle = '    document.addEventListener(\'keydown\', function(ev){'
        if needle not in r2:
            raise SystemExit('ERROR: Could not find Reading Room settings initialization anchor.')
        r2 = r2.replace(needle, new + '\n' + needle, 1)

# 4) Add a final defensive initialization after the main render/init sequence.
#    This prevents later initialization code from accidentally hiding the panel.
defensive = '''
    // Final defensive check: keep Reading Settings available in a dedicated book view.
    (function keepReadingSettingsVisible() {
      var panel = document.getElementById('panelTools');
      var btn = document.getElementById('btnTools');
      var hasBook = !!(state && state.bookId) || !!new URLSearchParams(window.location.search).get('book_id');
      if (!panel || !hasBook) return;
      panel.style.display = 'block';
      panel.dataset.open = '1';
      if (btn) {
        btn.classList.add('on');
        btn.setAttribute('aria-expanded', 'true');
      }
    })();
'''
anchor = '    renderPage();\n    loadVoices();'
if 'keepReadingSettingsVisible' not in r2:
    if anchor not in r2:
        raise SystemExit('ERROR: Could not find Reading Room render initialization anchor.')
    r2 = r2.replace(anchor, '    renderPage();\n' + defensive + '    loadVoices();', 1)

# 5) Verify the backend route is already present. If it is absent, refuse rather than guessing imports.
route_pat = re.compile(r'@router\.get\([\"\']/member/kwealth/books/reading-room[\"\']')
if not route_pat.search(rt):
    raise SystemExit(
        'ERROR: The dedicated /member/kwealth/books/reading-room route is missing from app/routers/kwealth.py. '
        'This repository needs the backend route patch before deploying the Reading Room.'
    )

# 6) Make sure the dedicated template really contains the full settings IDs.
required_ids = ['panelTools', 'panelMusic', 'fontSize', 'fontFamily', 'flipStyle', 'jumpTo', 'voiceName', 'rate', 'paraPause', 'btnSceneFs']
missing = [x for x in required_ids if x not in r2]
if missing:
    raise SystemExit('ERROR: Reading Room template is missing expected controls: ' + ', '.join(missing))

books.write_text(b2, encoding='utf-8')
reader.write_text(r2, encoding='utf-8')

print('Reading Room permanent fix applied successfully.')
print('Backend route verified: /member/kwealth/books/reading-room')
print('Fixed ID: toolsPanel -> panelTools')
print('Settings: automatically OPEN when book_id is present; toggle remains functional.')
print('Navigation: Back to Book Library + Kwealth preserved/added.')
