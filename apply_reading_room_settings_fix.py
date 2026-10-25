from pathlib import Path
import re

path=Path('app/templates/kwealth/reading_room.html')
if not path.exists():
    raise SystemExit('ERROR: app/templates/kwealth/reading_room.html not found. Run this from the OneChurchgate project root.')
text=path.read_text(encoding='utf-8')
old="""    $('panelTools').style.display = 'none';
    $('panelTools').dataset.open = '0';
    var toolsBtn = $('btnTools');
    if (toolsBtn) { toolsBtn.classList.remove('on'); toolsBtn.setAttribute('aria-expanded', 'false'); }"""
new="""    // Reading Room: show the complete reading settings by default when a book is open.
    // The settings button still toggles the panel closed/open.
    var toolsPanel = $('panelTools');
    var toolsBtn = $('btnTools');
    if (toolsPanel) {
      toolsPanel.style.display = 'block';
      toolsPanel.dataset.open = '1';
    }
    if (toolsBtn) {
      toolsBtn.classList.add('on');
      toolsBtn.setAttribute('aria-expanded', 'true');
    }"""
if old not in text:
    raise SystemExit('ERROR: Expected Reading Settings initialization block was not found. No changes made.')
text=text.replace(old,new,1)
# Also make the initialization resilient against later inline hiding before book state is established.
marker="""    #panelTools, .bar { position: sticky; top: 0; z-index: 40; }"""
if marker in text and 'body.reader-mode #panelTools:not([data-open="0"])' not in text:
    text=text.replace(marker, marker+"\n    /* Open settings automatically in the dedicated Reading Room; data-open=0 still permits closing. */\n    body.reader-mode #panelTools:not([data-open=\"0\"]){display:block!important;}",1)
# Final safety initialization immediately after the panel exists, only for a real book URL.
needle="""var tools=document.getElementById("panelTools");
   if(tools && !/book_id=/.test(location.search)) tools.style.display="none";"""
replacement="""var tools=document.getElementById("panelTools");
   if(tools && /book_id=/.test(location.search)){ tools.style.display="block"; tools.dataset.open="1"; var tb=document.getElementById("btnTools"); if(tb){ tb.classList.add("on"); tb.setAttribute("aria-expanded","true"); } }
   if(tools && !/book_id=/.test(location.search)) tools.style.display="none";"""
if needle not in text:
    raise SystemExit('ERROR: Final panelTools URL-state block was not found. No changes made.')
text=text.replace(needle,replacement,1)
path.write_text(text,encoding='utf-8')
print('FIXED:',path)
