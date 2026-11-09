# Free online pilot: Render + Supabase

Source repository: https://github.com/morluna/ivy-league (SSH configured). No cloud project or deployment has been created. SQLite remains the default for `python3 -B server.py`.

## What is ready

`render.yaml` now selects **Render Free** and **Supabase storage** with no disk. `render-paid.yaml` retains the optional paid SQLite configuration; do not apply it for the free pilot.

Phones -> Render HTTPS -> Python/Gunicorn -> Supabase Data API -> Postgres.

- `pickleball/supabase.py`: standard-library HTTPS adapter; credentials stay server-side.
- `supabase/migrations/001_sessions.sql`: session table, RLS, restricted grants and an atomic revision-checking save function.
- `supabase/tests/001_sessions.sql`: real database permission/CAS checks, with rollback of test data.
- Explicit storage selection: incomplete Supabase configuration stops startup rather than falling back to ephemeral SQLite.
- Existing seed scheduling, permissions, timers and snapshot polling are unchanged. No Supabase Auth or Realtime subscription is required yet.

## Account setup and publishing

1. Create a **Free** Supabase project at https://supabase.com/dashboard . Keep its database password in your password manager; the app does not need that password.
2. In the project's SQL Editor, run `supabase/migrations/001_sessions.sql` once. Then run `supabase/tests/001_sessions.sql`; it must complete without errors. If the first migration already succeeded, do not reapply it. A failed migration rolls back as a unit.
3. Find the project HTTPS URL and create/copy a server **secret API key** (`sb_secret_...`). Do not use the publishable key or paste the secret into chat, GitHub, client JS, or the public URL. The adapter deliberately accepts the current secret-key format, not legacy JWT keys. See https://supabase.com/docs/guides/getting-started/api-keys .
4. Create a Render account at https://dashboard.render.com and connect the `morluna/ivy-league` GitHub repository. Create a **Blueprint** using `render.yaml`. Verify it shows `plan: free`, no disk and no paid database before creating resources.
5. Enter only these secret settings in Render:

   | Setting | Value |
   | --- | --- |
   | `SUPABASE_URL` | The project's HTTPS origin, such as `https://your-project.supabase.co` |
   | `SUPABASE_SECRET_KEY` | The server-only `sb_secret_...` key |

   `STORAGE_BACKEND=supabase` is in the Blueprint. The app takes its public HTTPS origin from Render's automatic `RENDER_EXTERNAL_URL`. A custom domain later requires setting `PUBLIC_ORIGIN` explicitly to the exact origin with no trailing slash. See https://render.com/docs/environment-variables .
6. Deploy and check `https://YOUR-SERVICE.onrender.com/healthz`: it must return `{"status":"ok"}`. The probe verifies table readability, not merely process liveness. Migration, permissions and writes must still pass the checks below.
7. Create a **fresh** session over HTTPS and join from a second browser or phone on mobile data. Start with four players; test pause/resume, late join, departure, reconnect and organizer restrictions. Restart Render and verify the same session survives. Local SQLite sessions and local browser identities do not automatically migrate to the new origin.

Git pushes do not automatically deploy: `autoDeployTrigger` is off. No deployment or account credentials have been configured by this code change.

## Local verification

```sh
python3 -B -m unittest discover -s tests -v
node tests/form-regression.mjs  # optional Node UI handler regression
```

36 Python tests pass. Supabase tests use an in-process simulated provider with real request encoding and headers, plus concurrent application writers. They cover stale saves, duplicate creation semantics, reconnect, permissions, timer pause/resume, timeout/private errors, no write retries, malformed/oversized responses, redirect refusal and invalid configuration. Memory and SQLite implement the same compare-and-swap save contract.

**Not yet verified:** the SQL migration and SQL permission tests against actual Postgres/Supabase, Docker/Gunicorn image execution, and live end-to-end hosting. This workspace has no Postgres, Docker or connected Supabase project. Browser visual QA is also pending. Do not treat the simulated provider tests as proof that a live project's permissions or configuration are correct.

For a local production image check when Docker is available, test SQLite in an isolated volume without cloud credentials:

```sh
docker build -t rally-pilot .
docker run --rm -p 8001:8000 -e PUBLIC_ORIGIN=https://rally.example -v rally-data:/data rally-pilot
curl http://localhost:8001/healthz
```

This HTTP endpoint is for health/static inspection only. Browser writes intentionally reject a localhost HTTP origin against the production HTTPS origin. Test the Supabase configuration in staging using secret settings, never secrets in command arguments.

## Consistency and failure behavior

A session snapshot is saved only if the database's current revision matches the revision read by the application. SQL performs this check and update in one transaction. Stale writers return HTTP 409 and must refresh/retry; they cannot erase the winning update. No blind upserts exist in the cloud adapter. The local SQLite adapter uses a write transaction for the same guarantee.

Requests have a five-second provider timeout. Provider failures return a generic 503 without logging provider payloads or credentials. Writes are **not** automatically retried: a timeout may mean the save committed but its response was lost. Refresh before retrying. A lost create/join response can leave an orphan session or reserved name because request-level idempotency/recovery is not implemented yet. Already-identified participants can repeat joins with their existing browser capability.

The pilot retains one Gunicorn worker/eight threads. CAS protects database integrity across writers, but rate limits and notification hooks are process-local. Do not add replicas without shared abuse controls. The app stores authoritative timer timestamps; it does not depend on the server staying awake to decrement counters.

## Free limits and tradeoffs

Render Free: 750 instance-hours per workspace/month, sleeps after 15 idle minutes and has no persistent disk. The first visit after sleep can take longer and clients may need to retry. See https://render.com/docs/free .

Supabase Free: currently 500 MB database, 5 GB egress and potential pausing after a week of low activity. See https://supabase.com/pricing . Limits are shared with other projects/services as described by the providers; verify account quotas before launch.

Every active browser currently polls a full snapshot every 1.5 seconds, and every poll reads Supabase. Database outbound traffic therefore counts against quotas; monitor usage during the pilot rather than assuming the roster cap is a capacity guarantee. Push notifications, conditional reads and snapshot caching are later optimizations.

## Security and backups

Session capabilities are hashed before storage. Public snapshots exclude those hashes. RLS and revoked table/function grants prohibit direct browser-role access; only Render's secret key can call the storage API. The Python application enforces organizer and participant permissions before saving. Secret keys bypass RLS and must stay under server control.

The gateway includes body limits, JSON-only writes, an asset allowlist, same-origin write checks, CSP, HSTS, anti-framing and no-referrer headers. Browser capabilities still live in localStorage, with no account recovery or HttpOnly-cookie protection. A session link allows viewing and joining, so share it with the group deliberately.

Per-peer limits are 1,200 requests, 120 writes and 10 creates/minute. They reset on restart and may aggregate multiple users behind the hosting proxy because untrusted forwarding headers are not used. This is a small pilot, not a fully hardened public service.

No scheduled backup job is enabled. Before relying on Supabase for important history, configure restricted external exports and test restore; do not assume the Free plan supplies managed backups. Existing SQLite backups remain available through `python3 -B scripts/backup.py SOURCE DESTINATION`. Do not upload the local SQLite file or tokens to Git. For a code rollback, use a prior commit/image; code rollback does not roll back database contents. This migration creates new tables/functions without altering the local database.

## End sessions: organizer and app owner

After deploying this version, an organizer sees **End session** alongside the round controls, including before the first round starts. Ending a round still advances normal play; ending the session stops all play immediately. A confirmation appears before closing.

For your independent owner kill switch:

1. Generate a long random key in your own Terminal, and keep it in your password manager:

   ```sh
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. In Render -> service -> Environment, add `SESSION_ADMIN_KEY` with that value. Save and deploy the latest commit. Never paste this key into chat or Git. The Blueprint does not require it: when unset, owner termination is disabled. An explicitly configured key must have at least 32 characters.
3. Open `https://rally-pickleball.onrender.com/admin`. Paste a session link (or ID), enter your owner key, and confirm **End session for everyone**. This works even when you do not have that session's organizer credential. It handles one session at a time; there is no public session directory or bulk close action.

Owner and organizer closure share the same persisted lifecycle: stop the timer, record the closing time and authority, and block all further joins, departures, settings changes or timer controls. Repeated authorized end requests are idempotent. Existing naturally completed sessions also become read-only. Session history is retained; this is not deletion. Every connected client sees closure on its next successful poll; disconnected devices update on reconnect. A stale concurrent save returns 409 instead of reopening the session. The owner key cannot be used as an organizer/participant identity and is not saved in browser storage or sent in URLs.

No database migration is needed for these additions: the existing JSON snapshot stores the closure metadata. The owner-page and organizer UI handlers have automated regression checks:

```sh
node tests/form-regression.mjs
node tests/admin-regression.mjs
```
