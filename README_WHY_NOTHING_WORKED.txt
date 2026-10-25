
WHY NOTHING WORKED AFTER DEPLOY
================================

1) app/routers/confirm_registration.py on GitHub was a STUB:
   Only the comment: "# See previous ... zip for full module"
   → Confirm route never ran the real logic.

2) main.py never registered these routers:
   - confirm_registration
   - angel_resources_admin
   Files can sit in the repo forever and do nothing until:
     app.include_router(...router)

3) You must REPLACE these files and REDEPLOY Render:

   main.py                          ← wires the routers (CRITICAL)
   app/routers/confirm_registration.py   ← full code, not stub
   app/routers/angel_resources_admin.py

4) After Render shows "Live":
   - Hard refresh browser (Ctrl+Shift+R)
   - Admin social stream: /admin/social-stream (must be logged in as General Admin)
   - Angel room: /admin/angel-resources
   - Confirm: only NEW registration emails work with new token hasher

5) Duplicate folders (app/ vs routers/) do not matter if main imports app.routers.*
