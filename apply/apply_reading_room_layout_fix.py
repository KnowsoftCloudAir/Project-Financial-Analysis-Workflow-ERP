from pathlib import Path

path=Path('app/templates/kwealth/reading_room.html')
if not path.exists():
    raise SystemExit('ERROR: app/templates/kwealth/reading_room.html not found. Run this from the OneChurchgate project root.')
text=path.read_text(encoding='utf-8')

css='''\n    /* Reading Room layout fix: keep the settings controls clear of the book. */\n    body.reader-mode #panelTools {\n      position: relative !important;\n      z-index: 50 !important;\n      margin-bottom: 18px !important;\n      background: rgba(15,23,42,.96);\n      border-radius: 12px;\n      box-shadow: 0 10px 30px rgba(0,0,0,.24);\n    }\n    body.reader-mode main {\n      position: relative !important;\n      z-index: 1 !important;\n      padding-top: 34px !important;\n    }\n    body.reader-mode #stage {\n      margin-top: 18px !important;\n    }\n    @media (min-width: 1000px) {\n      body.reader-mode #panelTools {\n        max-width: 64rem !important;\n        padding-left: 18px !important;\n        padding-right: 18px !important;\n      }\n      body.reader-mode main {\n        max-width: 58rem !important;\n        padding-top: 44px !important;\n      }\n      body.reader-mode #stage {\n        margin-top: 24px !important;\n      }\n    }\n    @media (max-width: 650px) {\n      body.reader-mode main { padding-top: 22px !important; }\n      body.reader-mode #stage { margin-top: 10px !important; }\n    }\n'''
needle='''    .reader-heading .reader-author{margin:5px 0 0;color:#94a3b8;font-size:12px}\n'''
if 'body.reader-mode #stage {\n      margin-top: 18px' not in text:
    if needle not in text:
        raise SystemExit('ERROR: expected reader-heading CSS anchor not found.')
    text=text.replace(needle, needle+css, 1)
path.write_text(text,encoding='utf-8')
print('Applied Reading Room layout fix:', path)
