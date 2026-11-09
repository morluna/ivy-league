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
6. Deploy and check `https://YOUR-SERVICE.onrender.com/healthz`: it must return `{"status":"ok"}`. The probe verifies table readability, not merely process liveness, with a 30-second successful-probe cache (5 seconds on failure). Migration, permissions and writes must still pass the checks below.
7. Create a **fresh** session over HTTPS and join from a second browser or phone on mobile data. Start with four players; test pause/resume, late join, departure, reconnect and organizer restrictions. Restart Render and verify the same session survives. Local SQLite sessions and local browser identities do not automatically migrate to the new origin.

Git pushes do not automatically deploy: `autoDeployTrigger` is off. No deployment or account credentials have been configured by this code change.

## Local verification

```sh
python3 -B -m unittest discover -s tests -v
node tests/form-regression.mjs  # optional Node UI handler regression
```

71 Python tests pass. Supabase tests use an in-process simulated provider with real request encoding and headers, plus concurrent application writers. They cover stale saves, duplicate creation semantics, reconnect, permissions, timer pause/resume, timeout/private errors, no write retries, malformed/oversized responses, redirect refusal and invalid configuration. Memory and SQLite implement the same compare-and-swap save contract.

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

Visible browsers poll every 3 seconds during active/paused rounds and every 5 seconds otherwise. Hidden tabs and ended sessions stop polling; failed requests back off to 30 seconds. A bounded, process-local 3-second read cache coalesces viewers of the same session. Mutations bypass this cache, use CAS, then immediately refresh cached state; conflicts/uncertain writes invalidate it. Other-process changes can take up to the cache TTL plus the next browser poll to appear. Unchanged revisions return HTTP 304 with an authoritative timestamp, saving Render-to-browser payloads; this does not itself reduce Supabase traffic. The server cache does reduce Supabase reads/egress. Monitor usage rather than assuming the roster cap is a capacity guarantee. Supabase Realtime remains deferred.

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
node tests/polling-regression.mjs
```

## Traffic optimization review (local only)

The supplied 100-entry log export contained 73 successful session reads, 26 health reads, and one dashboard request over approximately 106 seconds. Session-read median spacing was about 1.49 seconds; health-read median spacing was 5 seconds. Logs contain no response-byte totals, so this sample does not establish a bill or monthly egress. Current pricing includes unlimited API requests on Free, with 5 GB uncached egress: https://supabase.com/pricing . REST gateway logs are not Supabase Realtime message events.

For 12 continuously visible clients over two hours, old 1.5-second polling implies 57,600 session reads. The new 3-second shared server cache caps unchanged-session polling at roughly 2,400 database reads per process over that interval, independent of viewer count, plus reads/writes for edits and health checks. This is an estimate from configured intervals, not a measured production saving. Ordinary single-viewer active polling falls from 40 to 20 requests/minute; health database probes fall from roughly 12 to 2 per minute. Cache entries are capped at 128 and never serve expired data after a failed refresh.

All these changes remain local pending the user's review. The timer still derives time from server timestamps; it sends no timer-tick events. No additional provider or background service is introduced.

## Manual round mode (local review)

Round minutes are optional. Null/omitted round length selects manual mode: the authoritative `started_at` drives a count-up clock, and the organizer advances with **Next round**. Numeric round lengths keep the existing countdown controls. The manual preview starts with 12 rounds and grows one at a time past that preview, capped at 96 rounds; organizers end sessions explicitly. No SQL migration or provider configuration change is needed. Existing numeric-length sessions continue to work. Run `node tests/manual-rounds-regression.mjs` for the new UI handler check.

## Court labels (local review)

Organizers can edit one name per court in **Court names**, before or during play. Blank labels fall back to Court 1, Court 2, etc.; names must be distinct and at most 40 characters. Saving names updates labels across the displayed schedule, including historical rounds, without changing any court slot, teams, round index or timer. Closed sessions are read-only. Court count remains locked after play starts; before play, resizing preserves existing labels and gives new slots defaults.

Numeric court slots remain stable internal identifiers, separate from editable names. This leaves room to attach venue/provider court IDs in a later CourtReserve integration without making names into identifiers. Existing sessions receive default labels automatically, and no database migration is required.

## Singles and doubles (local review)

Choose **Format** when creating a session: **Singles** needs two players per match (one on each side), and **Doubles** needs four (two on each side). Extra courts stay unused if there are not enough players to fill another match. Both formats support timed countdowns or manual count-up rounds, organizer roster edits, court labels and future-only rescheduling. Format can be changed in settings before the first round starts; it is locked afterward so existing match assignments remain consistent. Existing sessions default to doubles and need no migration.

Singles rotations prioritize balanced game counts and varied opponents; doubles also optimize partner variety. The stable court slots and provider-storage format are unchanged. Run `node tests/singles-regression.mjs` for format-selection and singles match rendering checks.
