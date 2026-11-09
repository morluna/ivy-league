# Ivy League — pickleball sessions

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
5. As organizer, use **Add a player**, **Remove**, or **Add back** to manage the roster during a round. That round is preserved; only future rounds change. A departed player's current court requires a manual substitution or early end.

## Architecture

- `pickleball/domain.py`: pure seeded scheduling and configuration validation. Explicit players, court count, round count, seed and historical rounds go in; rounds come out. No wall clock, persistence or global random state.
- `pickleball/application.py`: create/read/join/leave/settings/start/pause/resume/end-round/end-session use cases; capability permissions, validation, locking and future-only rescheduling.
- `pickleball/ports.py`: modest repository, clock and realtime protocols.
- `pickleball/adapters.py`: isolated memory repository, persistent SQLite repository, environment selection, system clock and snapshot realtime seam.
- `pickleball/supabase.py`: optional server-only Supabase REST adapter with atomic revision checks.
- `server.py`: HTTP transport and static files; standard-library threaded server.
- `static/`: responsive vanilla HTML/CSS/JS. No framework/build tool or third-party assets.

All mutations use a local application lock. Each adapter also compares the expected revision atomically before saving, preventing stale writers from overwriting newer state across processes. A conflict returns HTTP 409 and asks the client to refresh and retry. The pilot still runs one worker because rate limits are process-local.

### Scheduling contract

Every match has two sides: one distinct player per side in singles, or two per side in doubles. Each player occupies at most one court per round. Courts beyond the available full doubles groups stay unused. Fewer than two active players in singles, or four in doubles, produces empty future rounds and prevents starting one. Settings accept 1–16 courts, 1–480 total minutes, optional round minutes (positive whole minutes no longer than the session when supplied), and at most 96 rounds. Leaving round minutes blank selects manual rounds with a shared count-up clock. Rosters are capped at 64 identities, including departed players. For timed rounds, duration remainder is buffer time rather than a partial round. Manual mode initially previews 12 rounds and extends the schedule as needed, up to the same 96-round cap; booking duration is informational and does not end play automatically.

Selection gives priority to players with fewer historical games. For an unchanged roster, playing counts differ by at most one after every round. Pairing then greedily minimizes repeated partners (weight 5) and opponents (weight 1), with seeded tie-breaking and bounded search. This improves diversity without promising a globally optimal social-golfer solution. With changing rosters, past games count toward future selection; late arrivals can receive consecutive games to catch up. Existing rounds are preserved byte-for-byte. Departed identities stay in history for names and auditability. Organizers can restore a departed name with **Add back**, preserving its identity and history; active names cannot be duplicated. Organizer-added roster places do not issue a new browser identity or replace the organizer’s access. Players can view the shared session without joining again.

### Time and reconnect contract

The authoritative timer stores `started_at`, `remaining` and state on the server. Clients estimate server offset from request midpoint and derive remaining time from timestamps; no shared decrement loop. Pause captures remaining seconds; resume assigns a new start timestamp. Visible clients check every 3 seconds during running/paused rounds and every 5 seconds otherwise. Hidden tabs and closed sessions stop polling; failures back off up to 30 seconds. Reconnect/foreground triggers an immediate refresh. Unchanged revisions use an empty 304 response, with a server timestamp for clock synchronization. The HTTP adapters share public reads through a bounded 3-second server cache; mutations always read durable state and refresh the cache after saving. Server restart preserves timer timestamps, so elapsed time continues while the server is down. At zero, the display clamps to zero; the organizer explicitly ends the round and starts the next. Organizers can also end the whole session early. App owners can independently close any session through `/admin` using a separately configured `SESSION_ADMIN_KEY`. Closed sessions stop their timer and become read-only; history remains visible. No automatic schedule advancement. Storage health checks reuse successful probes for 30 seconds and failed probes for 5 seconds. A disconnected client retains its last view/timer and shows a connection warning; successful mutations require the server.

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

71 Python tests and the JavaScript form regression check passed, including an actual local HTTP create/join/reconnect flow. Browser visual/interaction checks could not run because the browser access host was unavailable. No external services were deployed or provisioned.

## Local review: organizer roster management

The title, header, owner page and share title now use **Ivy League**. The existing browser-storage key is retained so current local organizer access survives the rename. Hosting URLs and database names are unchanged.

In the organizer’s browser, the lineup includes an **Add a player** form, **Remove** controls and **Add back** for departed players. Only organizers can add/restore another player; participants can still leave themselves. Closed sessions remain read-only. Roster changes recompute only rounds that have never started. Completed rounds, the active round (including while paused or showing zero time), the round index and timer timestamps are preserved. Between rounds, the last completed round also remains frozen.

For local review, create a session, add at least four names, start/end round 1, start round 2, then add/remove a name. Rounds 1 and 2 must keep their assignments while round 3 onward changes. Removing a player during the active round still requires a manual substitution or ending that round early; the app deliberately does not rewrite an in-progress assignment.

## Optional round timer

Leave **Round minutes** blank when creating a session for manual play. **Start round** starts a synchronized elapsed clock at `00:00`. **Next round** atomically completes the current round, starts the next, and resets the count-up clock. All clients derive elapsed time from the server timestamp, including after reconnect. Roster edits preserve the current elapsed clock and all started rounds. **End session** stops the clock and retains the elapsed time of the final round.

Entering a number retains the timed countdown and pause/resume/end-round controls. Timer mode can be changed in settings before the first round starts; existing sessions retain their original mode. Manual mode balances game counts and pair diversity, but cannot promise equal actual minutes when games take different amounts of time. Next-round advancement requires four active players and organizer access; a failed advance leaves the current clock/round unchanged.

`node tests/manual-rounds-regression.mjs` verifies optional field parsing, elapsed display, organizer Next round controls, clock reset and closure. No database migration is required; null round length is supported by the existing JSON snapshot storage.

## Court labels (local review)

Organizers can edit one name per court in **Court names**, before or during play. Blank labels fall back to Court 1, Court 2, etc.; names must be distinct and at most 40 characters. Saving names updates labels across the displayed schedule, including historical rounds, without changing any court slot, teams, round index or timer. Closed sessions are read-only. Court count remains locked after play starts; before play, resizing preserves existing labels and gives new slots defaults.

Numeric court slots remain stable internal identifiers, separate from editable names. This leaves room to attach venue/provider court IDs in a later CourtReserve integration without making names into identifiers. Existing sessions receive default labels automatically, and no database migration is required.

## Singles and doubles (local review)

Choose **Format** when creating a session: **Singles** needs two players per match (one on each side), and **Doubles** needs four (two on each side). Extra courts stay unused if there are not enough players to fill another match. Both formats support timed countdowns or manual count-up rounds, organizer roster edits, court labels and future-only rescheduling. Format can be changed in settings before the first round starts; it is locked afterward so existing match assignments remain consistent. Existing sessions default to doubles and need no migration.

Singles rotations prioritize balanced game counts and varied opponents; doubles also optimize partner variety. The stable court slots and provider-storage format are unchanged. Run `node tests/singles-regression.mjs` for format-selection and singles match rendering checks.
