# Troubleshooting — match the exact symptom

## "host denied admission" within a few seconds (not a real 5-minute wait)

`meet_status` shows `error: "host denied admission"` almost immediately
after `joinAttemptedAt`. This is `_detect_denied()` matching one of:
"You can't join this video call", "You were removed from the meeting",
"No one responded to your request to join" — and the first of those is
exactly what Google shows when it's blocking the browser itself, not a
real human denial. Causes, in order of likelihood:

1. `auth.json` isn't actually being used for this join. Check
   `$HERMES_HOME/workspace/meetings/auth.json` exists for the **profile**
   that's joining (see auth-setup.md's per-profile gotcha), and that
   `tools.py`'s `handle_meet_join` has the auth_state patch applied
   (`install_patches.py` patch #5 — confirm with
   `grep auth_state tools.py`).
2. The session in `auth.json` was invalidated (see auth-setup.md's
   session-expiry note). Take a debug screenshot (below) — look for
   "Signed out" under the account name.
3. Anti-detection flags missing from the actual join flow (`meet_bot.py`,
   not just `cli.py`) — `channel="chrome"` and the `navigator.webdriver`
   override must both be on the `meet_bot.py` launch path, since that's
   what `meet_join` actually runs. It's easy to patch only `cli.py` (used
   by `hermes meet auth`) and forget `meet_bot.py` (used by the real join) —
   they're separate launch call sites.

## Genuine 5-minute lobby timeout, but the host never saw a knock notification

`leaveReason: "lobby_timeout"` after the full `HERMES_MEET_LOBBY_TIMEOUT`
(default 300s) — this part is actually working correctly: the bot reached
"Ask to join" and is waiting like a normal guest. If the host genuinely
never saw a knock:

- Confirm the host is looking at the **People panel** (participant icon,
  top right) — Meet sometimes flags automated-looking joins as
  "With potential risks" and only shows a "Deny" button directly in the
  toast, with **Admit hidden behind the kebab (⋮) menu** next to the name.
  This is easy to miss.
- Confirm the meeting wasn't created by a *different* identity than the one
  in `auth.json` and already ended/emptied — "No one else is here" on
  reload means the room is stale.

## Bot reports `captioning: true` but never actually joins (no error, no knock, runs until lobby timeout)

This was the actual root cause behind most early failures: `_click_join`
ran immediately after `page.goto(..., wait_until="domcontentloaded")`, but
Meet shows a **"Getting ready... You'll be able to join in just a moment"**
loading screen for a few seconds first. Neither "Join now" nor "Ask to
join" exists yet, so the click silently no-ops — and `captioning: true`
gets set unconditionally right after the click *attempt* regardless of
whether it actually found a button, so the status looks fine while nothing
happened.

Fixed by `install_patches.py`'s `_click_join` retry loop (patch #4). To
verify it's applied: `grep "Getting ready" meet_bot.py` should find
nothing (that's the Meet UI text, not our code) but
`grep "deadline = _time.time() + 20" meet_bot.py` should match.

To diagnose a *new* instance of this same failure mode (e.g. after a Meet
UI change breaks the button-text match), add a temporary unconditional
screenshot right after `_click_join(page, state)`:

```python
page.screenshot(path=str(out_dir / "debug.png"))
```

Pull it with `scp` and look at what's actually on screen — this is how the
original bug, the "Signed out" session expiry, and the calendar
organizer-identity confusion were all found. Don't guess from status.json
alone; the status fields can be misleading by construction (see above).

## Calendar event has no Meet link

`google-workspace`'s `calendar create` doesn't attach a Meet link by
default — there's no `conferenceData` in the request body. You must use
the `--meet` flag added by this skill's installer (patch #11). If you ran
`calendar create` before installing this skill's patches, the event exists
but has no Meet link; delete it and recreate with `--meet`, or add
conference data to it via a separate `events.patch` call (not currently
scripted here).

## Meet says the meeting is fine but `meet_chat` doesn't post anything

`meet_chat` is best-effort — `_send_chat_message` swallows all exceptions
and returns `False` silently if Meet's chat DOM doesn't match the
selectors (`textarea[aria-label*="Send a message" i]` etc.). Google
changes Meet's markup occasionally. If chat stops working after a Hermes
or Chrome update, take a screenshot after opening the chat panel manually
and update the selectors in `_send_chat_message`.

## General debug technique

Most of the above were diagnosed by adding a temporary screenshot call and
actually looking at the page, not by reasoning from `status.json` fields.
The status fields (`captioning`, `lobbyWaiting`, etc.) get set
optimistically at several points and don't always reflect ground truth.
When something is stuck or silently failing, screenshot first.
