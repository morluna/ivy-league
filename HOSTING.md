# Online pilot preparation

No hosting account, external database, billable resource, or deployment has been created. Local operation remains `python3 -B server.py`.

## Two options

**Lowest implementation effort:** Render Starter plus a persistent disk, using the included `render.yaml`. This is a PAID configuration: approximately $7/month compute plus $0.25/month for a 1 GB disk, before tax and usage overages. Hobby currently includes 5 GB/month outbound bandwidth. Verify pricing in the account before purchasing: https://render.com/pricing and https://render.com/docs/outbound-bandwidth .

**Free pilot:** Render Free plus Supabase Free for persistent data. Render Free supplies 750 instance-hours per workspace/month, sleeps after 15 minutes without traffic, and cannot attach a disk. Supabase Free currently includes a 500 MB database and 5 GB egress, and can pause after a week of low activity. See https://render.com/docs/free and https://supabase.com/pricing . This option requires a Supabase repository adapter and transactional concurrency tests before publishing. It is NOT enabled in the current source. Do not change the included Blueprint to `plan: free` while keeping SQLite: local files are ephemeral and sessions would be lost.

The user is considering the free route; do not apply the paid Blueprint without a deliberate paid-hosting choice.

## Prepared production setup

Phones -> HTTPS managed by host -> Gunicorn -> shared application layer -> SQLite on `/data`.

The Docker image uses Python 3.12 and a pinned Gunicorn version. It initializes persistent directory ownership, then drops root privileges before starting the server. It runs exactly one worker process and eight request threads; **do not increase instances or workers** while using the in-process mutation lock. Persistent disks also mean brief restart downtime during deploys on Render.

Set `PUBLIC_ORIGIN` to the exact public origin, such as `https://rally-example.onrender.com`, with no trailing slash. The app fails closed without it in production. Cross-origin writes are rejected. TLS terminates at the host; the internal HTTP listener must not be exposed independently. Do not trust client-supplied forwarding headers as authentication or client identity. Current limits use the direct peer IP; behind a shared reverse proxy, limits may apply to a group of visitors together. This conservative limit is suitable only for the small pilot; tune at the trusted host edge before broader use.

Protections included:

- Capability hashes in durable state. Existing SQLite plaintext tokens are automatically migrated without changing browser identities. Legacy snapshots/backups can still contain old plaintext values: restrict and rotate those backups appropriately.
- Server-side organizer/self-removal authorization, bounded bodies, JSON-only writes, static asset allowlist and private errors.
- Per-peer limits: 1,200 requests, 120 writes and 10 session creations per minute. In-process limits reset after a server restart. Not a distributed abuse protection system.
- CSP, HTTPS HSTS, anti-framing, no-referrer headers; API snapshots are not cached. Access logs do not disclose session links.
- `/healthz` checks storage readability and returns no session data.

Browser capabilities remain in localStorage. CSP reduces injection risks, but this does not provide HttpOnly-cookie protection or account recovery. A session URL permits viewing and joining; treat the URL as a group invitation. No existing local database is uploaded by the Docker build.

## Local checks

```sh
python3 -B -m unittest discover -s tests -v
node tests/form-regression.mjs  # optional Node runtime for UI handler regression
```

The Python suite includes the production WSGI gateway directly, HTTPS-origin behavior, authorization, capability migration, rate-limit expiry, health checks, malformed/oversized requests, backup/restore, plus scheduling/application/HTTP tests.

With Docker installed, check the actual image before deployment:

```sh
docker build -t rally-pilot .
docker run --rm -p 8001:8000 -e PUBLIC_ORIGIN=https://rally.example -v rally-data:/data rally-pilot
curl http://localhost:8001/healthz
```

The HTTP test address above is for local inspection of health/static content. Browser mutations intentionally reject an HTTP localhost Origin against the configured HTTPS production origin. An end-to-end production check must use the real HTTPS origin. Docker and the production Gunicorn runtime were unavailable in this workspace, so image execution is still a required pre-deployment check. Browser visual QA remains pending because the browser access host was unavailable.

## Publishing the paid option, if selected later

1. Put the source in a private Git repository, excluding SQLite, backups, browser tokens and local environments. Git credentials/hosting account are not currently connected in this workspace.
2. In Render, connect that repository and review `render.yaml`. It provisions a paid Starter service with one 1 GB disk at `/data`. Automatic deploys are off.
3. Set `PUBLIC_ORIGIN` to the actual generated HTTPS origin; `DATABASE_PATH` is already `/data/sessions.sqlite3`. Confirm the service and disk cost before activating billing.
4. Deploy, check `/healthz`, create a fresh test session and join from a second device over mobile data. Confirm pause/resume/reconnect. Restart the service and verify the same session and permissions survive.
5. Test a controlled backup/restore before the group relies on it. Keep the prior image/commit for code rollback; code rollback does not restore database state.

## Backups

```sh
python3 -B scripts/backup.py /data/sessions.sqlite3 /data/rally-backup-YYYY-MM-DD.sqlite3
```

This uses SQLite's consistent online backup API and integrity checking. Use a fresh filename and copy backups off the hosting disk into restricted storage. The helper is manual; no recurring backups or retention jobs have been provisioned. On paid Render, provider disk snapshots are an additional layer, not a substitute for a tested application backup.

To restore: stop the only app instance, preserve the current database, replace it with a verified backup, set ownership for the application user, then restart and check `/healthz` and session access. Never overwrite an active SQLite database. Schedule and monitor backups before treating this as durable production service.
