from pathlib import Path

p = Path('app/templates/kwealth/reading_room.html')
if not p.exists():
    raise SystemExit('ERROR: app/templates/kwealth/reading_room.html was not found. Run this script from the Churchgate project root.')
s = p.read_text(encoding='utf-8')
old = """    $('panelTools').style.display = 'none';
    $('panelTools').dataset.open = '0';
    var toolsBtn = $('btnTools');
    if (toolsBtn) { toolsBtn.classList.remove('on'); toolsBtn.setAttribute('aria-expanded', 'false'); }
"""
new = """    // Reading Room: keep the complete reading settings visible by default.
    // This exposes font/font size, themes, page-flip, page jump, voice,
    // reading speed and paragraph pauses as soon as a book is opened.
    var toolsPanel = $('panelTools');
    var toolsBtn = $('btnTools');
    if (toolsPanel) {
      toolsPanel.style.display = 'block';
      toolsPanel.dataset.open = '1';
    }
    if (toolsBtn) {
      toolsBtn.classList.add('on');
      toolsBtn.setAttribute('aria-expanded', 'true');
    }
"""
if old not in s:
    raise SystemExit('ERROR: expected Reading Settings initialization block was not found; repository version may differ.')
s = s.replace(old, new, 1)
# Ensure the later guard does not hide the panel when a book_id is present.
old2 = """  var tools=document.getElementById(\"panelTools\");
  if(tools && !/book_id=/.test(location.search)) tools.style.display=\"none\";
"""
new2 = """  var tools=document.getElementById(\"panelTools\");
  if(tools && /book_id=/.test(location.search)) {
    tools.style.display=\"block\";
    tools.dataset.open=\"1\";
    var tb=document.getElementById(\"btnTools\");
    if(tb){ tb.classList.add(\"on\"); tb.setAttribute(\"aria-expanded\",\"true\"); }
  }
"""
if old2 in s:
    s = s.replace(old2, new2, 1)
else:
    raise SystemExit('ERROR: final Reading Room visibility guard was not found; repository version may differ.')
p.write_text(s, encoding='utf-8')
print('Corrected:', p)
