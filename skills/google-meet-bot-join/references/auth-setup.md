# Auth setup — the only method that works

## Why `hermes meet auth` doesn't work

It opens a Playwright-controlled browser and asks you to sign in there. Google
detects the automation fingerprint (CDP/`navigator.webdriver`/the
"controlled by automated test software" flag) during the live sign-in flow
and blocks it with **"This browser or app may not be secure"** — every time,
regardless of:
- Real Chrome vs bundled Chromium (`channel="chrome"` doesn't fix this).
- The OS (tested on the bot's own Linux VPS *and* a fresh WSL2 Ubuntu install
  on a residential IP — both blocked identically).
- `--disable-blink-features=AutomationControlled` alone (helps with guest-join
  detection later, but Google still blocks the *sign-in* flow specifically).

We also tried copying an already-logged-in Chrome profile's cookies onto the
bot host — also fails, because modern Chrome's "app-bound encryption" ties
cookie decryption to the original profile path; a copy decrypts to nothing
and Meet just shows the sign-in screen again.

## What actually works

Sign in on a real, non-automated browser session — but inject the
anti-detection flags into *that* Playwright instance too, so the resulting
session cookies are exactly the kind Meet expects to see later:

```
pip install playwright
python -m playwright install chrome
python scripts/extract_session.py
```

A Chrome window opens. Sign in normally (password, 2FA, passkey — whatever
the account uses). The script polls the URL and auto-saves
`meet_auth.json` once you land back on `myaccount.google.com` or similar.
No "browser not secure" warning appears here, because you are the one
driving the sign-in interactively — Google's check is on automated sign-in
*flows*, not on the presence of automation flags in general.

Copy the result to the bot host:

```
scp meet_auth.json bot-host:$HERMES_HOME/workspace/meetings/auth.json
```

**Per-profile gotcha:** each Hermes profile has its own `$HERMES_HOME`
(e.g. `~/.hermes/profiles/<name>/`). Copying `auth.json` into one profile's
`workspace/meetings/` does nothing for another profile that also needs to
join meetings — copy it into each one.

## Session expiry

Google appears to invalidate this kind of extracted session after enough
rapid automated launches in a short window — observed failure after roughly
10-15 join attempts within an hour, surfacing as the bot's screenshot
showing a Google "Choose an account... **Signed out**" page instead of
actually joining. If joins that previously worked suddenly start failing
again with no useful error, re-run `extract_session.py` before debugging
anything else.

To confirm this is what's happening (vs. a code regression), take a
screenshot mid-join — see `references/troubleshooting.md` for how — and
look for the "Signed out" label under the account name.
