# What survives a GitHub / Render code upgrade

## YouTube links
- Approved active links are stored in the **database** and mirrored to `data/persistent/youtube_home.json`.
- On boot the app **restores missing rows** from that JSON. It does **not** delete existing YouTube rows.
- Links disappear only if an admin **deletes/rejects** them, or if the **database disk is wiped** (free Render without Postgres + no persistent disk).

**Required for real safety:** Render **PostgreSQL** (`DATABASE_URL`) and, if you use the JSON mirror, a **persistent disk** mounted so `data/persistent/` is not erased when the instance sleeps.

Backup: Admin backup download includes `youtubechannellink` (same idea as music links).

## Background music
- Files live under `app/static/uploads/kwealth_bgm/` (and similar).
- Code deploy does **not** delete those folders unless you delete them.
- On **ephemeral** Render disk they can vanish when the service is rebuilt. Use persistent disk or object storage for production.

## Admin / member passwords
Startup used to **force-reset** General Admin to `Knowsoft#GA2026!` on every boot. That is **disabled**.
- If `admin@knowsoft.com` **already exists**, the hash is **left alone**.
- Bundled restore **skips** `hashed_password` on existing users.
- Sample account `angel@churchgate.com` may still be reset to the demo password (demo only).

After this deploy: change GA password once in-app; later GitHub pushes should **not** revert it.

## Still wipe data if you
- Reset the Render database
- Delete persistent disk
- Run a seed script that deletes tables
- Restore an old backup over new data
