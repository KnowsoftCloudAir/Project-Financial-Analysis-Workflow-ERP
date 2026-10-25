# Deploy code without losing subscriber data

Uploading a new ZIP / pushing to GitHub **only changes application code**.
It does **not** wipe your database **if**:

1. Render (or your host) uses a **persistent database** (`DATABASE_URL` → PostgreSQL).
2. You do **not** clear the database, delete the Render Postgres instance, or force a full restore from an old empty backup.
3. You avoid running destructive scripts that drop tables.

## Safe deploy steps
1. Commit/push the upgraded code (this zip’s `OneChurchgate-main` contents).
2. On Render: **Manual Deploy** → latest commit.
3. Keep the same **DATABASE_URL** env var.
4. New columns (`promo_code`, `ReferralCashout`, etc.) are added with `create_db_and_tables` / migrations — existing rows stay.

## What members notice
- New **Invite & earn** panel and rewards page.
- Existing logins, churches, subscriptions, and member profiles remain.
- Existing users get a promo code on first visit to rewards (no re-registration).

## Risky actions (avoid)
- Deleting the Render PostgreSQL addon
- Changing `DATABASE_URL` to empty/sqlite ephemeral disk without backup
- Forcing `restore_bundled_backup(force=True)` in a way that overwrites live data with sample data (check `bundled_restore` behaviour on boot)

## Before deploy (recommended)
Download a backup from **Admin → Backup and restore** and keep the JSON offline.
