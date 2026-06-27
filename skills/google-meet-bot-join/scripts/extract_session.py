#!/usr/bin/env python3
"""Run this on a machine with normal Chrome installed (your own PC/Mac/Linux
desktop with a real display) — NOT the headless bot server.

Opens a real, anti-detection-flagged Chrome window, lets you sign in to
Google normally, auto-detects completion, and writes meet_auth.json.

This is the only auth method that reliably works — live sign-in directly
through the bot's own (Playwright-controlled) browser gets blocked by
Google's "This browser or app may not be secure" check, no matter what
flags you pass it. Signing in here works because the browser doing the
actual OAuth handshake genuinely isn't being remote-controlled at that
moment — you're driving it by hand.

Requires: pip install playwright && python -m playwright install chrome

After it finishes, copy meet_auth.json to the bot host at:
  $HERMES_HOME/workspace/meetings/auth.json
for every profile that needs to join meetings.
"""
from playwright.sync_api import sync_playwright

OUT = "meet_auth.json"

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=False,
        channel="chrome",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        ),
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    page = context.new_page()
    page.goto("https://accounts.google.com/", wait_until="domcontentloaded")

    print("Sign in to the Google account the bot should use to join meetings.")
    print("Waiting for sign-in to complete (up to 5 minutes)...")
    for _ in range(150):
        page.wait_for_timeout(2000)
        url = page.url
        if "accounts.google.com" not in url or "myaccount.google.com" in url:
            print("Detected sign-in completion, url:", url)
            break
    else:
        print("Timed out waiting for sign-in — re-run and sign in faster, "
              "or increase the loop count above.")

    context.storage_state(path=OUT)
    browser.close()

print(f"Saved {OUT}. Copy it to the bot host's "
      f"$HERMES_HOME/workspace/meetings/auth.json")
