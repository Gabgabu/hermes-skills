---
name: google-meet-bot-join
description: "Reliable Google Meet join, in-call chat, and post-call summarization for Hermes Agent — patches the bundled google_meet plugin's automation-detection, race-condition, and auth-wiring bugs, and adds a meet_chat tool."
version: 1.0.0
author: Guy Abou
license: MIT
platforms: [linux, macos]
required_credential_files:
  - path: workspace/meetings/auth.json
    description: Playwright storage_state with a real, already-authenticated Google session (see references/auth-setup.md — live sign-in through the bot's own browser is blocked by Google).
metadata:
  hermes:
    tags: [Google, Meet, Calendar, Playwright, Transcription, Summarization]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [google-workspace]
---

# Google Meet Bot Join, Chat & Summarize

Makes the bundled `google_meet` plugin (Playwright-based: `meet_join`, `meet_status`, `meet_transcript`, `meet_leave`, `meet_say`) actually work end-to-end, and adds a `meet_chat` tool it doesn't ship with. Without these patches, the stock plugin reliably fails in three ways:

1. Google blocks any live sign-in attempt through the bot's own browser with "This browser or app may not be secure" — this is Playwright's automation fingerprint, not the OS, IP, or Chrome branding.
2. Even once authenticated, `_click_join` runs immediately after page load and silently does nothing if Meet is still showing "Getting ready..." — the bot sits forever with no error and no visible knock.
3. The agent-facing `meet_join` tool (what your bot actually calls) never wires the auth session into the join call — only the `hermes meet join` CLI path does. Tool-driven joins run fully unauthenticated even when `auth.json` exists.

This skill's installer patches all three, plus adds `meet_chat`.

## Install

Run once per Hermes install (idempotent — safe to re-run, skips already-applied patches):

```
python3 scripts/install_patches.py
```

It patches `plugins/google_meet/{cli.py,meet_bot.py,tools.py,process_manager.py,__init__.py,plugin.yaml}` inside the active `hermes-agent` package, and (if the `google-workspace` skill is also installed) adds a `--meet` flag to its `calendar create` command so Calendar events actually get a Meet link attached — they don't by default.

Then enable the plugin and install its system deps as usual:

```
hermes plugins enable google_meet
hermes meet install
```

Restart the bot's gateway service afterward so the running process picks up the new `meet_chat` tool:

```
systemctl --user restart hermes-gateway-<profile>.service
```

## Authentication (read this before joining anything)

`hermes meet auth` will NOT work — Google blocks the live sign-in flow through any Playwright-controlled browser, full stop, regardless of which patches are applied. See `references/auth-setup.md` for the actual working method: sign in once in a normal anti-detection-flagged browser on your own machine, export the session, copy it to the server.

The exported file must land at `$HERMES_HOME/workspace/meetings/auth.json` for **every** profile that needs to join meetings (each Hermes profile has its own `$HERMES_HOME` — copying it to one profile does not cover another).

Sessions get invalidated by Google if reused across many rapid automated launches in a short window (observed after ~10-15 join attempts in under an hour). Re-run the export when `hermes meet status` shows a "Choose an account... Signed out" page in a debug screenshot, or joins start failing instantly again.

## Usage workflow

### 1. Create a meeting the bot can join without manual admission

The bot's own Google account is the one that authenticated `auth.json` (check whose session you exported). For the bot to skip the lobby entirely, it must be the **organizer** — which means the meeting has to be created from its own Calendar, not yours.

```
python3 google-workspace/scripts/google_api.py calendar create \
  --summary "Meeting title" \
  --start 2026-01-01T10:00:00+00:00 \
  --end   2026-01-01T10:30:00+00:00 \
  --attendees someone@example.com \
  --meet
```

This returns a `meetLink`. Joining that link as the same authenticated account lands the bot directly in the call — no admit needed.

If instead you create the meeting yourself (in your own Calendar/Meet) and just send the bot the link, it will need an actual human to admit it from the lobby every time — there is no way around this for non-organizer joins.

### 2. Join

```python
meet_join(url="https://meet.google.com/xxx-xxxx-xxx", mode="transcribe")
```

`mode="realtime"` additionally enables spoken audio via OpenAI Realtime (costs per audio-minute) — only use it if the user actually wants the bot to talk.

Poll with `meet_status()` until `inCall: true`. If it's not the organizer, the meeting's host must manually click Admit (gabot should tell the user "I'm waiting in the lobby — please admit me" and not assume success).

### 3. Chat (new tool this skill adds)

```python
meet_chat(text="Noted — I'll follow up on that after the call.")
```

Posts to Meet's in-call text chat panel, visible to everyone. Works in either mode. Best-effort — Meet's chat DOM isn't a stable public API, so this can silently no-op if Google changes the markup; verify with a live test after any Hermes/Chrome upgrade.

### 4. Summarize

There is no built-in summarize tool. Read the transcript and write the summary yourself:

```python
meet_transcript(last=200)   # or omit `last` for the whole thing
```

Then compose the summary as you normally would and send it wherever the user expects it (chat reply, email, etc.). `meet_leave()` first if you want a clean exit and a finalized transcript file.

## References

- `references/auth-setup.md` — the only authentication method that actually works, step by step.
- `references/troubleshooting.md` — every failure mode hit while building this, with the exact symptom to match against.
- `references/calendar-meet-setup.md` — why `--meet` is required and how organizer/host identity works in Google Meet.

## Scripts

- `scripts/install_patches.py` — idempotent patcher for the `google_meet` plugin and (optionally) `google-workspace`'s Calendar script. Run on the Hermes Agent host.
- `scripts/extract_session.py` — run on a machine with normal Chrome installed (NOT the bot host, unless it has a real desktop) to produce `auth.json`.
