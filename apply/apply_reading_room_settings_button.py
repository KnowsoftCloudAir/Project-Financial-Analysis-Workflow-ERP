from pathlib import Path
import re

ROOT = Path('.')
path = ROOT / 'app/templates/kwealth/reading_room.html'
if not path.exists():
    raise SystemExit('ERROR: app/templates/kwealth/reading_room.html not found. Run this from the OneChurchgate project root.')

text = path.read_text(encoding='utf-8')
original = text

# 1) Correct the floating-menu ID typo wherever the old ID is used.
text = text.replace("getElementById('toolsPanel')", "getElementById('panelTools')")
text = text.replace('getElementById("toolsPanel")', 'getElementById("panelTools")')

# 2) Add a clean, dedicated launcher button immediately before the complete settings panel.
button_marker = 'id="readingSettingsLauncher"'
if button_marker not in text:
    m = re.search(r'(?m)^(\s*)<[^>]*\bid=[\"\']panelTools[\"\'][^>]*>', text)
    if not m:
        raise SystemExit('ERROR: Could not find #panelTools in reading_room.html. No changes made.')
    indent = m.group(1)
    button = f'''{indent}<button id="readingSettingsLauncher" type="button" class="chip reading-settings-launcher" aria-controls="panelTools" aria-expanded="false" title="Show or hide all Reading Room settings">⚙ Reading Settings</button>\n'''
    text = text[:m.start()] + button + text[m.start():]

# 3) Add dedicated launcher styling once.
css_marker = '/* ONECHURCHGATE_READING_SETTINGS_BUTTON */'
if css_marker not in text:
    css = '''\n    /* ONECHURCHGATE_READING_SETTINGS_BUTTON */\n    .reading-settings-launcher {\n      display: inline-flex !important;\n      align-items: center;\n      justify-content: center;\n      gap: 7px;\n      min-height: 38px;\n      padding: 8px 14px;\n      margin: 8px 0;\n      font-size: 13px;\n      font-weight: 800;\n      cursor: pointer;\n      position: relative;\n      z-index: 10001;\n    }\n    #panelTools.reading-settings-hidden { display: none !important; }\n    #panelTools.reading-settings-visible { display: block !important; visibility: visible !important; opacity: 1 !important; }\n'''
    pos = text.find('</style>')
    if pos < 0:
        raise SystemExit('ERROR: Could not find </style>. No changes made.')
    text = text[:pos] + css + text[pos:]

# 4) Add robust toggle logic immediately before </body>.
js_marker = '/* ONECHURCHGATE_READING_SETTINGS_TOGGLE */'
if js_marker not in text:
    js = r'''\n<script>\n/* ONECHURCHGATE_READING_SETTINGS_TOGGLE */\n(function(){\n  function setupReadingSettingsButton(){\n    var panel = document.getElementById('panelTools');\n    var launcher = document.getElementById('readingSettingsLauncher');\n    if(!panel || !launcher) return;\n\n    function setOpen(open){\n      panel.classList.toggle('reading-settings-visible', !!open);\n      panel.classList.toggle('reading-settings-hidden', !open);\n      panel.style.display = open ? 'block' : 'none';\n      panel.dataset.open = open ? '1' : '0';\n      launcher.setAttribute('aria-expanded', open ? 'true' : 'false');\n      launcher.classList.toggle('on', !!open);\n      launcher.textContent = open ? '⚙ Hide Reading Settings' : '⚙ Reading Settings';\n    }\n\n    launcher.onclick = function(e){\n      e.preventDefault();\n      e.stopPropagation();\n      setOpen(panel.dataset.open !== '1');\n    };\n\n    // The dedicated Reading Room starts clean: settings are available from one button.\n    // Other code may manipulate panelTools, so establish a stable closed state after load.\n    setOpen(false);\n\n    // Protect the panel from legacy code that uses the old toolsPanel ID.\n    var legacy = document.getElementById('toolsPanel');\n    if(legacy && legacy !== panel) legacy.id = 'panelTools';\n  }\n\n  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupReadingSettingsButton);\n  else setupReadingSettingsButton();\n})();\n</script>\n'''
    pos = text.lower().rfind('</body>')
    if pos < 0:
        raise SystemExit('ERROR: Could not find </body>. No changes made.')
    text = text[:pos] + js + text[pos:]

if text == original:
    print('No changes needed; the settings button fix is already present.')
else:
    path.write_text(text, encoding='utf-8')
    print('UPDATED:', path)
