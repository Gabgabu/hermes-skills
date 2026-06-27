# google-meet-bot-join

Makes [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s bundled
`google_meet` plugin actually work — joining, chatting in, and summarizing
Google Meet calls reliably — and adds a `meet_chat` tool the stock plugin
doesn't ship with.

This file is the detailed human-readable writeup. For the Hermes-facing
install manifest (frontmatter, the version `hermes skills install` reads),
see [`SKILL.md`](SKILL.md).

## Why this skill exists

The stock `google_meet` plugin (`meet_join`, `meet_status`, `meet_transcript`,
`meet_leave`, `meet_say`) is a solid design on paper — Playwright drives a
real browser into a Meet call and scrapes live captions into a transcript.
In practice, as shipped, it fails in three independent ways that all had to
be found by actually watching the browser, not by reading status output:

1. **Google blocks the live sign-in flow.** `hermes meet auth` opens a
   Playwright-controlled browser and asks you to sign in there. Google
   detects the automation fingerprint during that live OAuth handshake and
   shows "This browser or app may not be secure" — every time, regardless
   of OS, IP, or whether it's real Chrome vs. bundled Chromium.
2. **`_click_join` races the page load.** It runs immediately after
   `page.goto(...)`, but Meet shows a "Getting ready..." loading screen for
   a few seconds first. Neither "Join now" nor "Ask to join" exists yet, so
   the click is a silent no-op — forever, with no error. Worse, the status
   field `captioning: true` gets set unconditionally right after the click
   *attempt*, so it looks like progress happened when nothing did.
3. **The agent-facing tool never loads the auth session.** `hermes meet
   join` (the CLI command) correctly wires `auth.json` into the join call.
   The `meet_join` *tool* — what your bot actually calls when a user asks it
   to join a meeting — does not. It was simply missing from that code path.
   Every agent-driven join ran fully unauthenticated, with no warning.

None of these produce a clear error. They all produce a bot that looks
like it's working (alive, no exceptions, plausible-looking status fields)
while never actually joining anything. The only way any of them got found
was by patching in a `page.screenshot()` call and looking at what was
literally on screen at the moment of failure — see
[`references/troubleshooting.md`](references/troubleshooting.md) for the
exact technique and every other failure mode hit along the way.

## What this skill adds

- **`channel="chrome"`** (real installed Chrome, not Playwright's bundled
  Chromium) on both the auth flow and the actual join flow — these are two
  separate launch call sites in the plugin; patching only one is a common
  mistake.
- **A `navigator.webdriver` override** via `context.add_init_script`, so
  the join session doesn't carry the most basic automation tell.
- **A retry loop in `_click_join`** (up to 20s) so it actually waits out
  the "Getting ready..." screen instead of racing it.
- **`auth_state` wired into the agent tool path**, so `meet_join` calls
  made by the bot itself behave the same as `hermes meet join` from a
  terminal.
- **A new `meet_chat` tool** — posts a message into Meet's in-call text
  chat panel (visible to everyone in the call), distinct from `meet_say`
  which speaks audio and requires realtime mode. `meet_chat` works in
  either mode.
- **A `--meet` flag for `google-workspace`'s `calendar create`** (only
  patched if that skill is also installed) — without it, Calendar events
  created through that skill have no Meet link attached at all; Google's
  Calendar API doesn't add one by default.

## What this skill does *not* solve

- **It cannot make Google allow a live sign-in through the bot's browser.**
  There is no flag combination that fixes this — it's a deliberate Google
  anti-automation check on the sign-in flow specifically. Authentication
  has to happen by exporting a session from a real, interactively-driven
  browser instead. See [`references/auth-setup.md`](references/auth-setup.md).
- **It cannot grant the bot host/admit authority over a meeting it didn't
  create.** Google Meet's organizer is whoever's Calendar created the
  event — not an attendee, not whoever has "guest can modify" rights. If
  someone else creates the meeting, a human has to manually admit the bot
  from the lobby every single time; there's no way around this. See
  [`references/calendar-meet-setup.md`](references/calendar-meet-setup.md).
- **It does not summarize anything automatically.** There's no built-in
  summarize tool, by design — `meet_transcript` returns the scraped
  caption text, and the agent is expected to read it and write the summary
  itself using its normal reasoning, then deliver it however the user
  expects (chat reply, email, etc.).
- **Session longevity isn't guaranteed.** The exported auth session
  appears to get invalidated by Google after enough rapid automated
  launches in a short window (observed failure after roughly 10-15 join
  attempts within an hour). When joins that used to work suddenly start
  failing with no clear error, re-exporting the session is the first thing
  to try, before assuming a code regression.

## Install

```
python3 scripts/install_patches.py
hermes plugins enable google_meet
hermes meet install
systemctl --user restart hermes-gateway-<profile>.service
```

`install_patches.py` is idempotent — every patch checks for its own marker
string before applying, so it's safe to run repeatedly, including against
an already-patched install (it'll just report `[skip]` for everything).
It locates the installed `google_meet` plugin automatically; pass a path
explicitly if it can't find it:

```
python3 scripts/install_patches.py /path/to/plugins/google_meet
```

Then authenticate — see [`references/auth-setup.md`](references/auth-setup.md),
this is the part that actually takes effort and cannot be skipped or
automated through the bot itself.

## File layout

```
google-meet-bot-join/
  SKILL.md                          — Hermes install manifest + condensed usage docs
  README.md                         — this file
  scripts/
    install_patches.py              — idempotent patcher, run on the bot host
    extract_session.py              — run on a machine with a real desktop to produce auth.json
  references/
    auth-setup.md                   — the only auth method that works, step by step
    troubleshooting.md              — every failure mode, by exact symptom
    calendar-meet-setup.md          — organizer identity, lobby behavior, why "the bot scheduled it" ≠ "the bot is host"
```

## Usage once installed

```python
# 1. Create a meeting the bot can join without manual admission
#    (must be created via the bot's own Calendar so it's the organizer)
google_api.py calendar create --summary "..." --start ... --end ... --meet

# 2. Join
meet_join(url="https://meet.google.com/xxx-xxxx-xxx", mode="transcribe")

# 3. Chat in the call
meet_chat(text="...")

# 4. Read the transcript and summarize it yourself
meet_transcript(last=200)
meet_leave()
```

Full detail on each step, including what to do when the bot *isn't* the
organizer, is in [`SKILL.md`](SKILL.md).

## Tested against

- Hermes Agent v0.17.0, Ubuntu 24.04 (bot host), Google Chrome (real, not
  bundled Chromium).
- Verified end-to-end: bot created a Calendar event with `--meet`, joined
  it as organizer with no manual admission required, appeared in the
  participant list, `meet_status` reported `inCall: true`.
- `meet_chat` was added and registered successfully; live verification
  against an active call is still pending re-authentication (see the
  session-longevity note above) — treat it as best-effort until you've
  confirmed it against your own Meet UI version.

## Contributing fixes back

If a future Meet UI change breaks `_click_join`'s button-text matching or
`_send_chat_message`'s selectors, the fix pattern is the same one used to
find every bug here: add a temporary unconditional `page.screenshot()`
call at the point of failure, pull it, and look. Don't trust the status
JSON fields in isolation — several of them get set optimistically and can
look fine while nothing actually happened.
