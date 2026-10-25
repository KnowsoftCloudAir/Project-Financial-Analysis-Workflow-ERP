# OneChurchgate — Reading Room Settings Button Fix

This fix changes the Reading Room so **all reading settings are available from one clear button** instead of being permanently exposed or mysteriously disappearing.

## What the button does

`⚙ Reading Settings` opens the complete existing `#panelTools` settings area. Clicking it again closes the area.

The existing settings are preserved:

1. Font and font size
2. Reading themes
3. Page-flip styles
4. Page navigation / page jump
5. Voice / read-aloud
6. Reading speed
7. Paragraph pauses
8. Background music
9. 3D scenes / ambience and Knowsoft clock controls
10. Full-screen reading

## Additional correction

The patch changes the old `toolsPanel` DOM lookup to `panelTools` so the floating-menu code targets the actual settings panel.

## Apply

From the root of the OneChurchgate project:

```bash
python apply_reading_room_settings_button.py
```

Then restart/redeploy the application and hard-refresh the Reading Room (`Ctrl+F5`).

The script is fail-safe: it stops if the expected `#panelTools` or document structure is missing.
