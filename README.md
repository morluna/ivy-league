# Rally — local pickleball sessions

A mobile-first, no-account doubles scheduler. Python 3.9+ is the only dependency. No package installation, API keys, cloud accounts, or deployment required.

Hosting preparation, paid/free choices and remaining deployment checks: [HOSTING.md](HOSTING.md). Nothing is deployed.

## Run

```sh
python3 -B server.py
```

Open http://localhost:8000. Session state persists in `sessions.sqlite3`; stopping and restarting the server preserves it. Organizer and participant capabilities live in that browser's localStorage. Share links contain only the session ID, never organizer permissions.

```sh
python3 -B -m unittest discover -s tests -v
```

An additional UI form regression check can be run with Node when available:

```sh
node tests/form-regression.mjs
```

It exercises the actual creation and settings handlers with a form collection whose built-in `length` property collides with the round-length field.

Tests use isolated memory repositories, temporary databases and an ephemeral loopback HTTP server. They never touch your normal session database. The suite covers scheduling across 0–24 players and multiple court counts, repeatability, equal playing time, partner diversity, validation, duplicate joins, concurrent joins, future-only changes, permission boundaries, snapshot isolation, timer transitions and reconnection, database restart and HTTP behavior.

To use several phones on the same trusted Wi-Fi:

```sh
python3 -B server.py --host 0.0.0.0
```

Open `http://YOUR-COMPUTER-LAN-IP:8000` on **all** devices, including the organizer, before creating/sharing a session. A localhost link only works on the host computer. Browser identity is scoped to the exact origin: switching from localhost to a LAN address does not transfer organizer rights. LAN mode is plain HTTP; use only a trusted network. Native share/clipboard support varies on HTTP; the app displays a copyable link if unavailable.

## Try it

1. Create a session and adjust courts, total minutes and round minutes.
2. Open the shared URL in separate browsers/private profiles to join as distinct people. Tabs in the same browser share an identity.
3. With at least four players, start a round from the organizer's browser.
4. Pause/resume and check the other clients. Disconnect one client, change the roster, and reconnect; it fetches the latest complete snapshot.
5. Remove or add a player during a round. That round is preserved; only future rounds change. A departed player's current court requires a manual substitution or early end.

## Architecture

- `pickleball/domain.py`: pure seeded scheduling and configuration validation. Explicit players, court count, round count, seed and historical rounds go in; rounds come out. No wall clock, persistence or global random state.
- `pickleball/application.py`: create/read/join/leave/settings/start/pause/resume/end use cases; capability permissions, validation, locking and future-only rescheduling.
- `pickleball/ports.py`: modest repository, clock and realtime protocols.
- `pickleball/adapters.py`: isolated memory repository, persistent SQLite repository, environment selection, system clock and snapshot realtime seam.
- `pickleball/supabase.py`: optional server-only Supabase REST adapter with atomic revision checks.
- `server.py`: HTTP transport and static files; standard-library threaded server.
- `static/`: responsive vanilla HTML/CSS/JS. No framework/build tool or third-party assets.

All mutations use a local application lock. Each adapter also compares the expected revision atomically before saving, preventing stale writers from overwriting newer state across processes. A conflict returns HTTP 409 and asks the client to refresh and retry. The pilot still runs one worker because rate limits are process-local.

### Scheduling contract

Every match has two teams of two distinct players. Each player occupies at most one court per round. Courts beyond the available full doubles groups stay unused. Fewer than four active players produces empty future rounds and prevents starting one. Settings accept 1–16 courts, 1–480 total minutes, positive integer round minutes no longer than the session, and at most 96 rounds. Rosters are capped at 64 identities, including departed players. Duration remainder is buffer time rather than a partial round.

Selection gives priority to players with fewer historical games. For an unchanged roster, playing counts differ by at most one after every round. Pairing then greedily minimizes repeated partners (weight 5) and opponents (weight 1), with seeded tie-breaking and bounded search. This improves diversity without promising a globally optimal social-golfer solution. With changing rosters, past games count toward future selection; late arrivals can receive consecutive games to catch up. Existing rounds are preserved byte-for-byte. Departed identities stay in history for names and auditability; names cannot be reused in that session.

### Time and reconnect contract

The authoritative timer stores `started_at`, `remaining` and state on the server. Clients estimate server offset from request midpoint and derive remaining time from timestamps; no shared decrement loop. Pause captures remaining seconds; resume assigns a new start timestamp. A full revisioned snapshot is polled every 1.5 seconds and refreshed on reconnect/foreground. Server restart preserves timer timestamps, so elapsed time continues while the server is down. At zero, the display clamps to zero; the organizer explicitly ends the round and starts the next. No automatic schedule advancement. A disconnected client retains its last view/timer and shows a connection warning; successful mutations require the server.

`SnapshotRealtime.publish` is deliberately a no-op: local clients pull durable snapshots, rather than depending on an ephemeral event queue. The port is a future notification seam, not an unnecessary local message broker.

### Local permission model and limits

Each browser receives an opaque random capability. Only the organizer can change settings or control rounds; participants can remove only themselves, and organizers can remove anyone. Public snapshots expose names and schedules, never capabilities. Durable capabilities are stored as SHA-256 digests; existing SQLite records migrate on startup. Names are normalized, length-limited and rendered using textContent. Joins with an existing capability are idempotent; conflicting names are rejected. Without the capability, a repeated name cannot claim an existing identity. Clearing browser storage loses that capability; recovery/account linking is deferred. This version does not transfer organizer rights, restore departed players, store scores, book courts, or provide native lock-screen Live Activities.

The HTTP adapter rejects cross-origin browser writes and limits JSON body size. It is a local development server, not an Internet-facing production service. The local default has no telemetry or outbound requests. Selecting Supabase explicitly enables server-side provider requests; its secret is never sent to the browser. No payment flows or booking calls exist.

## Phased integrations — nothing provisioned

1. **Local acceptance:** verify the mobile UI on real phones, tune fairness using realistic group rosters, and settle session lifecycle and organizer recovery. Keep pure domain/application tests as the acceptance suite. Browser automation is the next testing addition when a browser runtime is available.
2. **Supabase persistence (implemented, not provisioned):** optional REST repository, SQL migration, service-role-only permissions, compare-and-swap RPC and offline provider contract tests. Apply and verify SQL in a real project before publishing. Memory/SQLite remain local defaults. Optional accounts remain deferred.
3. **Supabase realtime:** implement publish/subscription notifications that trigger snapshot refetches. Retain polling fallback and reconnect reconciliation. Test duplicate/out-of-order notifications and stale revisions. Keep authoritative server timestamps and validate clock drift.
4. **Hosting:** package the HTTP/application layer for the selected host, add HTTPS, secure capability handling, monitoring, backups, rate limits and environment configuration. Test staging explicitly before any production release. Hosting choice and service limits should be verified at integration time; this MVP has no service costs.
5. **CourtReserve:** first verify supported API access, venue permissions and booking terms with the provider. Start with venue links/manual booking metadata. Add a separate booking adapter only when supported access is established. Model availability, booking conflicts, timeouts, retries, idempotency, cancellation and explicit booking confirmation independently of scheduling. Do not scrape credentials or assume a public booking API exists.
6. **Native activity support:** evaluate a native wrapper and platform-specific push/activity services separately. The current mobile web timer works while the page is active; background execution and lock-screen updates are not guaranteed.

## Validation in this workspace

29 Python tests and the JavaScript form regression check passed, including an actual local HTTP create/join/reconnect flow. Browser visual/interaction checks could not run because the browser access host was unavailable. No external services were deployed or provisioned.
