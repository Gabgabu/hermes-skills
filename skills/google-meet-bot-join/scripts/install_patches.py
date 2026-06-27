#!/usr/bin/env python3
"""Idempotent patcher for Hermes Agent's bundled google_meet plugin.

Fixes (see SKILL.md for why each is needed):
  1. Real Chrome instead of bundled Chromium (channel="chrome") in both
     the auth CLI command and the actual join flow.
  2. navigator.webdriver override on the join context.
  3. _click_join retry loop (handles Meet's "Getting ready..." race).
  4. auth_state actually wired into the agent-facing meet_join tool.
  5. New meet_chat tool (schema + handler + registration + bot-side
     queue drain that types into Meet's chat panel).
  6. Optional: --meet flag on google-workspace's `calendar create` so
     Calendar events actually get a Meet link attached.

Safe to re-run — every patch checks for its own marker before applying.
Run with the same Python that runs `hermes` (so imports resolve), e.g.:
  /usr/local/lib/hermes-agent/venv/bin/python3 install_patches.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def find_plugin_root() -> Path:
    """Locate the installed google_meet plugin directory."""
    candidates = [
        Path("/usr/local/lib/hermes-agent/plugins/google_meet"),
    ]
    try:
        import importlib.util
        spec = importlib.util.find_spec("plugins.google_meet")
        if spec and spec.origin:
            candidates.insert(0, Path(spec.origin).parent)
    except Exception:
        pass
    for c in candidates:
        if c.is_dir():
            return c
    sys.exit("Could not locate the google_meet plugin directory. Pass it explicitly: "
             "install_patches.py /path/to/plugins/google_meet")


def find_google_workspace_script(hermes_home_guess: Path | None) -> Path | None:
    """Best-effort search for google-workspace's google_api.py (optional patch)."""
    search_roots = []
    if hermes_home_guess:
        search_roots.append(hermes_home_guess)
    search_roots += [Path.home() / ".hermes", Path("/root/.hermes")]
    for root in search_roots:
        if not root.is_dir():
            continue
        hits = list(root.rglob("google-workspace/scripts/google_api.py"))
        if hits:
            return hits[0]
    return None


def apply(path: Path, label: str, marker: str, old: str, new: str, *, required: bool = True) -> None:
    s = path.read_text(encoding="utf-8")
    if marker in s:
        print(f"  [skip]  {label} — already applied")
        return
    if old not in s:
        msg = f"  [WARN]  {label} — expected pattern not found, skipping (file may have changed upstream)"
        print(msg)
        if required:
            print(f"          inspect manually: {path}")
        return
    s = s.replace(old, new, 1)
    path.write_text(s, encoding="utf-8")
    print(f"  [done]  {label}")


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else find_plugin_root()
    print(f"Patching google_meet plugin at: {root}\n")

    cli_py = root / "cli.py"
    meet_bot_py = root / "meet_bot.py"
    tools_py = root / "tools.py"
    process_manager_py = root / "process_manager.py"
    init_py = root / "__init__.py"
    plugin_yaml = root / "plugin.yaml"

    # 1. cli.py — real Chrome for the (mostly unusable, but still patch it) auth command.
    apply(
        cli_py, "cli.py: channel=chrome for hermes meet auth",
        marker='channel="chrome"',
        old='browser = pw.chromium.launch(headless=False)',
        new='browser = pw.chromium.launch(headless=False, channel="chrome")',
    )

    # 2. meet_bot.py — real Chrome for the actual join flow.
    apply(
        meet_bot_py, "meet_bot.py: channel=chrome for join flow",
        marker='channel="chrome"',
        old='browser = pw.chromium.launch(\n                headless=not headed,\n                args=chrome_args,\n            )',
        new='browser = pw.chromium.launch(\n                headless=not headed,\n                channel="chrome",\n                args=chrome_args,\n            )',
    )

    # 3. meet_bot.py — navigator.webdriver override.
    apply(
        meet_bot_py, "meet_bot.py: navigator.webdriver override",
        marker="Object.defineProperty(navigator, 'webdriver'",
        old="context = browser.new_context(**context_args)\n            page = context.new_page()",
        new=(
            "context = browser.new_context(**context_args)\n"
            "            context.add_init_script(\"Object.defineProperty(navigator, 'webdriver', "
            "{get: () => undefined});\")\n"
            "            page = context.new_page()"
        ),
    )

    # 4. meet_bot.py — _click_join retry loop.
    old_click_join = (
        'def _click_join(page, state: _BotState) -> None:\n'
        '    """Click \'Join now\' or \'Ask to join\' if either button is visible.\n'
        '\n'
        '    Flags ``lobby_waiting`` when we hit the "waiting for host to admit you"\n'
        '    state so the agent can surface that in status.\n'
        '    """\n'
        '    for label in ("Join now", "Ask to join"):\n'
        '        try:\n'
        '            btn = page.get_by_role("button", name=label, exact=False).first\n'
        '            if btn.count() and btn.is_visible():\n'
        '                btn.click(timeout=3_000)\n'
        '                if label == "Ask to join":\n'
        '                    state.set(lobby_waiting=True)\n'
        '                break\n'
        '        except Exception:\n'
        '            continue'
    )
    new_click_join = (
        'def _click_join(page, state: _BotState) -> None:\n'
        '    """Click \'Join now\' or \'Ask to join\' if either button is visible.\n'
        '\n'
        '    Retries for up to ~20s since the page often shows a "Getting ready..."\n'
        '    loading state for a few seconds before either button exists.\n'
        '\n'
        '    Flags ``lobby_waiting`` when we hit the "waiting for host to admit you"\n'
        '    state so the agent can surface that in status.\n'
        '    """\n'
        '    import time as _time\n'
        '    deadline = _time.time() + 20\n'
        '    while _time.time() < deadline:\n'
        '        clicked = False\n'
        '        for label in ("Join now", "Ask to join"):\n'
        '            try:\n'
        '                btn = page.get_by_role("button", name=label, exact=False).first\n'
        '                if btn.count() and btn.is_visible():\n'
        '                    btn.click(timeout=3_000)\n'
        '                    if label == "Ask to join":\n'
        '                        state.set(lobby_waiting=True)\n'
        '                    clicked = True\n'
        '                    break\n'
        '            except Exception:\n'
        '                continue\n'
        '        if clicked:\n'
        '            return\n'
        '        page.wait_for_timeout(1000)'
    )
    apply(
        meet_bot_py, "meet_bot.py: _click_join retry loop",
        marker="Retries for up to ~20s",
        old=old_click_join,
        new=new_click_join,
    )

    # 5. tools.py — wire auth_state into the agent-facing meet_join tool.
    old_pm_start = (
        '    res = pm.start(\n'
        '        url=url,\n'
        '        headed=bool(args.get("headed", False)),\n'
        '        guest_name=str(args.get("guest_name") or "Hermes Agent"),\n'
        '        duration=str(args.get("duration")) if args.get("duration") else None,\n'
        '        mode=mode,\n'
        '    )'
    )
    new_pm_start = (
        '    from pathlib import Path as _Path\n'
        '    from hermes_constants import get_hermes_home as _ghh\n'
        '    _auth = _Path(_ghh()) / "workspace" / "meetings" / "auth.json"\n'
        '    res = pm.start(\n'
        '        url=url,\n'
        '        headed=bool(args.get("headed", False)),\n'
        '        guest_name=str(args.get("guest_name") or "Hermes Agent"),\n'
        '        duration=str(args.get("duration")) if args.get("duration") else None,\n'
        '        mode=mode,\n'
        '        auth_state=str(_auth) if _auth.is_file() else None,\n'
        '    )'
    )
    apply(
        tools_py, "tools.py: wire auth_state into handle_meet_join",
        marker="_ghh()) / \"workspace\" / \"meetings\" / \"auth.json\"",
        old=old_pm_start,
        new=new_pm_start,
    )

    # 6. meet_bot.py — chat queue filename + helper + drain loop.
    apply(
        meet_bot_py, "meet_bot.py: CHAT_QUEUE_FILENAME constant",
        marker='CHAT_QUEUE_FILENAME = "chat_queue.jsonl"',
        old='SAY_QUEUE_FILENAME = "say_queue.jsonl"\nSAY_PCM_FILENAME = "speaker.pcm"',
        new=(
            'SAY_QUEUE_FILENAME = "say_queue.jsonl"\n'
            'SAY_PCM_FILENAME = "speaker.pcm"\n'
            'CHAT_QUEUE_FILENAME = "chat_queue.jsonl"'
        ),
    )
    helper = (
        'def _send_chat_message(page, text: str) -> bool:\n'
        '    """Open Meet\'s in-call chat panel (if needed) and send *text*.\n'
        '\n'
        '    Best-effort: tries a few selector variants since Meet\'s chat DOM\n'
        '    structure isn\'t a stable public API. Returns True on a successful\n'
        '    send, False otherwise (never raises).\n'
        '    """\n'
        '    try:\n'
        '        input_sel = (\n'
        '            \'textarea[aria-label*="Send a message" i], \'\n'
        '            \'div[aria-label*="Send a message" i][contenteditable="true"], \'\n'
        '            \'textarea[aria-label*="message" i]\'\n'
        '        )\n'
        '        box = page.locator(input_sel).first\n'
        '        if not (box.count() and box.is_visible()):\n'
        '            chat_btn = page.get_by_role(\n'
        '                "button", name=re.compile("chat", re.I)\n'
        '            ).first\n'
        '            if chat_btn.count():\n'
        '                chat_btn.click(timeout=3_000)\n'
        '                page.wait_for_timeout(700)\n'
        '            box = page.locator(input_sel).first\n'
        '        if not (box.count() and box.is_visible()):\n'
        '            return False\n'
        '        box.click(timeout=3_000)\n'
        '        box.fill(text)\n'
        '        page.keyboard.press("Enter")\n'
        '        return True\n'
        '    except Exception:\n'
        '        return False\n'
        '\n'
        '\n'
        'def _click_join(page, state: _BotState) -> None:'
    )
    apply(
        meet_bot_py, "meet_bot.py: _send_chat_message helper",
        marker="def _send_chat_message(page, text: str) -> bool:",
        old="def _click_join(page, state: _BotState) -> None:",
        new=helper,
    )
    old_loop_tail = (
        '                if rt["session"] is not None:\n'
        '                    state.set(\n'
        '                        audio_bytes_out=getattr(rt["session"], "audio_bytes_out", 0),\n'
        '                        last_audio_out_at=getattr(rt["session"], "last_audio_out_at", None),\n'
        '                    )\n'
        '\n'
        '                time.sleep(1.0)'
    )
    new_loop_tail = (
        '                if rt["session"] is not None:\n'
        '                    state.set(\n'
        '                        audio_bytes_out=getattr(rt["session"], "audio_bytes_out", 0),\n'
        '                        last_audio_out_at=getattr(rt["session"], "last_audio_out_at", None),\n'
        '                    )\n'
        '\n'
        '                chat_queue_path = out_dir / CHAT_QUEUE_FILENAME\n'
        '                if chat_queue_path.is_file():\n'
        '                    try:\n'
        '                        lines = chat_queue_path.read_text(encoding="utf-8").splitlines()\n'
        '                    except Exception:\n'
        '                        lines = []\n'
        '                    if lines:\n'
        '                        for line in lines:\n'
        '                            line = line.strip()\n'
        '                            if not line:\n'
        '                                continue\n'
        '                            try:\n'
        '                                entry = json.loads(line)\n'
        '                            except Exception:\n'
        '                                continue\n'
        '                            text = str(entry.get("text", "")).strip()\n'
        '                            if not text:\n'
        '                                continue\n'
        '                            _send_chat_message(page, text)\n'
        '                        try:\n'
        '                            chat_queue_path.unlink()\n'
        '                        except Exception:\n'
        '                            pass\n'
        '\n'
        '                time.sleep(1.0)'
    )
    apply(
        meet_bot_py, "meet_bot.py: chat-queue drain in main loop",
        marker="Drain any queued chat messages",
        old=old_loop_tail,
        new=new_loop_tail,
    )

    # 7. process_manager.py — enqueue_chat.
    pm_new_func = (
        'def enqueue_chat(text: str) -> dict:\n'
        '    """Append a chat-send request to the active bot\'s JSONL queue.\n'
        '\n'
        '    Works in either transcribe or realtime mode (chat is a DOM action,\n'
        '    not audio). Returns ``{"ok": False, "reason": ...}`` when no meeting\n'
        '    is active.\n'
        '    """\n'
        '    import uuid\n'
        '\n'
        '    text = (text or "").strip()\n'
        '    if not text:\n'
        '        return {"ok": False, "reason": "text is required"}\n'
        '\n'
        '    active = _read_active()\n'
        '    if not active:\n'
        '        return {"ok": False, "reason": "no active meeting"}\n'
        '\n'
        '    out_dir = Path(active.get("out_dir", ""))\n'
        '    if not out_dir.is_dir():\n'
        '        return {"ok": False, "reason": f"out_dir missing: {out_dir}"}\n'
        '\n'
        '    queue_path = out_dir / "chat_queue.jsonl"\n'
        '    entry = {"id": uuid.uuid4().hex[:12], "text": text}\n'
        '    with queue_path.open("a", encoding="utf-8") as f:\n'
        '        f.write(json.dumps(entry) + "\\n")\n'
        '    return {\n'
        '        "ok": True,\n'
        '        "meetingId": active.get("meeting_id"),\n'
        '        "enqueued_id": entry["id"],\n'
        '        "queue_path": str(queue_path),\n'
        '    }\n'
        '\n'
        '\n'
        'def enqueue_say(text: str) -> dict:'
    )
    apply(
        process_manager_py, "process_manager.py: enqueue_chat",
        marker="def enqueue_chat(text: str)",
        old='def enqueue_say(text: str) -> Dict[str, Any]:',
        new=pm_new_func.replace('-> dict:', '-> Dict[str, Any]:'),
    )

    # 8. tools.py — MEET_CHAT_SCHEMA + handle_meet_chat.
    anchor_schema = (
        'MEET_SAY_SCHEMA: Dict[str, Any] = {\n'
        '    "name": "meet_say",\n'
        '    "description": (\n'
        '        "Speak text into the active Meet call. Requires the active meeting "\n'
        '        "to have been joined with mode=\'realtime\'. The text is queued to "\n'
        '        "the bot\'s OpenAI Realtime session; the generated audio is streamed "\n'
        '        "into Chrome\'s fake microphone via a virtual audio device "\n'
        '        "(PulseAudio null-sink on Linux, BlackHole on macOS). Returns "\n'
        '        "immediately — the actual speech lags by a couple of seconds."\n'
        '    ),\n'
        '    "parameters": {\n'
        '        "type": "object",\n'
        '        "properties": {\n'
        '            "text": {"type": "string", "description": "Text to speak."},\n'
        '            "node": {"type": "string"},\n'
        '        },\n'
        '        "required": ["text"],\n'
        '        "additionalProperties": False,\n'
        '    },\n'
        '}'
    )
    chat_schema = (
        '\n\n\n'
        'MEET_CHAT_SCHEMA: Dict[str, Any] = {\n'
        '    "name": "meet_chat",\n'
        '    "description": (\n'
        '        "Post a text message into the active Meet call\'s in-call chat "\n'
        '        "panel (visible to all participants in the meeting\'s Chat sidebar). "\n'
        '        "Works in either transcribe or realtime mode — this types into "\n'
        '        "Meet\'s chat box, it does not speak audio. Returns immediately; "\n'
        '        "the message is sent on the next status-poll cycle (within ~1s)."\n'
        '    ),\n'
        '    "parameters": {\n'
        '        "type": "object",\n'
        '        "properties": {\n'
        '            "text": {"type": "string", "description": "Text to post in chat."},\n'
        '            "node": {"type": "string"},\n'
        '        },\n'
        '        "required": ["text"],\n'
        '        "additionalProperties": False,\n'
        '    },\n'
        '}'
    )
    apply(
        tools_py, "tools.py: MEET_CHAT_SCHEMA",
        marker='"name": "meet_chat"',
        old=anchor_schema,
        new=anchor_schema + chat_schema,
    )
    anchor_handler = (
        '    res = pm.enqueue_say(text)\n'
        '    return _json({"success": bool(res.get("ok")), **res})'
    )
    chat_handler = (
        '\n\n\n'
        'def handle_meet_chat(args: Dict[str, Any], **_kw) -> str:\n'
        '    text = (args.get("text") or "").strip()\n'
        '    if not text:\n'
        '        return _err("text is required")\n'
        '    try:\n'
        '        client, node_name = _resolve_node_client(args.get("node"))\n'
        '    except RuntimeError as e:\n'
        '        return _err(str(e))\n'
        '    if client is not None:\n'
        '        return _err("meet_chat is not yet supported on remote nodes", node=node_name)\n'
        '    res = pm.enqueue_chat(text)\n'
        '    return _json({"success": bool(res.get("ok")), **res})'
    )
    apply(
        tools_py, "tools.py: handle_meet_chat",
        marker="def handle_meet_chat(args",
        old=anchor_handler,
        new=anchor_handler + chat_handler,
    )

    # 9. __init__.py — register meet_chat.
    s = init_py.read_text(encoding="utf-8")
    if "MEET_CHAT_SCHEMA" in s:
        print("  [skip]  __init__.py: meet_chat already registered")
    else:
        s = s.replace(
            "    MEET_SAY_SCHEMA,\n    MEET_STATUS_SCHEMA,",
            "    MEET_CHAT_SCHEMA,\n    MEET_SAY_SCHEMA,\n    MEET_STATUS_SCHEMA,",
        )
        s = s.replace(
            "    handle_meet_say,\n    handle_meet_status,",
            "    handle_meet_chat,\n    handle_meet_say,\n    handle_meet_status,",
        )
        s = s.replace(
            '    ("meet_say",        MEET_SAY_SCHEMA,        handle_meet_say,        "\U0001F5E3️"),\n)',
            '    ("meet_say",        MEET_SAY_SCHEMA,        handle_meet_say,        "\U0001F5E3️"),\n'
            '    ("meet_chat",       MEET_CHAT_SCHEMA,       handle_meet_chat,       "\U0001F4AC"),\n)',
        )
        init_py.write_text(s, encoding="utf-8")
        print("  [done]  __init__.py: registered meet_chat")

    # 10. plugin.yaml — document the new tool.
    s = plugin_yaml.read_text(encoding="utf-8")
    if "meet_chat" in s:
        print("  [skip]  plugin.yaml: meet_chat already listed")
    else:
        s = s.replace("  - meet_say\n", "  - meet_say\n  - meet_chat\n")
        plugin_yaml.write_text(s, encoding="utf-8")
        print("  [done]  plugin.yaml: added meet_chat")

    # 11. Optional — google-workspace's calendar create --meet flag.
    print()
    gws_script = find_google_workspace_script(None)
    if gws_script is None:
        print("google-workspace skill not found — skipping optional Calendar --meet patch.")
    else:
        print(f"Patching google-workspace at: {gws_script}")
        s = gws_script.read_text(encoding="utf-8")
        if '"--meet"' in s or "args.meet" in s:
            print("  [skip]  google_api.py: --meet already supported")
        else:
            old_func = (
                'def calendar_create(args):\n'
                '    event = {\n'
                '        "summary": args.summary,\n'
                '        "start": {"dateTime": args.start},\n'
                '        "end": {"dateTime": args.end},\n'
                '    }\n'
                '    if args.location:\n'
                '        event["location"] = args.location\n'
                '    if args.description:\n'
                '        event["description"] = args.description\n'
                '    if args.attendees:\n'
                '        event["attendees"] = [{"email": e.strip()} for e in args.attendees.split(",") if e.strip()]\n'
                '\n'
                '    if _gws_binary():\n'
                '        result = _run_gws(\n'
                '            ["calendar", "events", "insert"],\n'
                '            params={"calendarId": args.calendar},\n'
                '            body=event,\n'
                '        )\n'
                '        print(json.dumps({\n'
                '            "status": "created",\n'
                '            "id": result["id"],\n'
                '            "summary": result.get("summary", ""),\n'
                '            "htmlLink": result.get("htmlLink", ""),\n'
                '        }, indent=2))\n'
                '        return\n'
                '\n'
                '    service = build_service("calendar", "v3")\n'
                '    result = service.events().insert(calendarId=args.calendar, body=event).execute()\n'
                '    print(json.dumps({\n'
                '        "status": "created",\n'
                '        "id": result["id"],\n'
                '        "summary": result.get("summary", ""),\n'
                '        "htmlLink": result.get("htmlLink", ""),\n'
                '    }, indent=2))'
            )
            new_func = (
                'def calendar_create(args):\n'
                '    import uuid\n'
                '    event = {\n'
                '        "summary": args.summary,\n'
                '        "start": {"dateTime": args.start},\n'
                '        "end": {"dateTime": args.end},\n'
                '    }\n'
                '    if args.location:\n'
                '        event["location"] = args.location\n'
                '    if args.description:\n'
                '        event["description"] = args.description\n'
                '    if args.attendees:\n'
                '        event["attendees"] = [{"email": e.strip()} for e in args.attendees.split(",") if e.strip()]\n'
                '\n'
                '    add_meet = getattr(args, "meet", False)\n'
                '    if add_meet:\n'
                '        event["conferenceData"] = {\n'
                '            "createRequest": {\n'
                '                "requestId": uuid.uuid4().hex,\n'
                '                "conferenceSolutionKey": {"type": "hangoutsMeet"},\n'
                '            }\n'
                '        }\n'
                '\n'
                '    def _extract_meet_link(result):\n'
                '        link = result.get("hangoutLink", "")\n'
                '        if not link:\n'
                '            for ep in result.get("conferenceData", {}).get("entryPoints", []):\n'
                '                if ep.get("entryPointType") == "video":\n'
                '                    link = ep.get("uri", "")\n'
                '                    break\n'
                '        return link\n'
                '\n'
                '    if _gws_binary():\n'
                '        params = {"calendarId": args.calendar}\n'
                '        if add_meet:\n'
                '            params["conferenceDataVersion"] = 1\n'
                '        result = _run_gws(\n'
                '            ["calendar", "events", "insert"],\n'
                '            params=params,\n'
                '            body=event,\n'
                '        )\n'
                '        print(json.dumps({\n'
                '            "status": "created",\n'
                '            "id": result["id"],\n'
                '            "summary": result.get("summary", ""),\n'
                '            "htmlLink": result.get("htmlLink", ""),\n'
                '            "meetLink": _extract_meet_link(result),\n'
                '        }, indent=2))\n'
                '        return\n'
                '\n'
                '    service = build_service("calendar", "v3")\n'
                '    insert_kwargs = {"calendarId": args.calendar, "body": event}\n'
                '    if add_meet:\n'
                '        insert_kwargs["conferenceDataVersion"] = 1\n'
                '    result = service.events().insert(**insert_kwargs).execute()\n'
                '    print(json.dumps({\n'
                '        "status": "created",\n'
                '        "id": result["id"],\n'
                '        "summary": result.get("summary", ""),\n'
                '        "htmlLink": result.get("htmlLink", ""),\n'
                '        "meetLink": _extract_meet_link(result),\n'
                '    }, indent=2))'
            )
            if old_func in s:
                s = s.replace(old_func, new_func)
                old_arg = (
                    '    p = cal_sub.add_parser("create")\n'
                    '    p.add_argument("--summary", required=True)\n'
                    '    p.add_argument("--start", required=True, help="Start (ISO 8601 with timezone)")\n'
                    '    p.add_argument("--end", required=True, help="End (ISO 8601 with timezone)")\n'
                    '    p.add_argument("--location", default="")\n'
                    '    p.add_argument("--description", default="")\n'
                    '    p.add_argument("--attendees", default="", help="Comma-separated email addresses")\n'
                    '    p.add_argument("--calendar", default="primary")'
                )
                new_arg = old_arg + (
                    '\n    p.add_argument("--meet", action="store_true", '
                    'help="Attach a Google Meet conference link")'
                )
                s = s.replace(old_arg, new_arg)
                gws_script.write_text(s, encoding="utf-8")
                print("  [done]  google_api.py: added --meet flag to calendar create")
            else:
                print("  [WARN]  google_api.py: calendar_create body didn't match expected "
                      "pattern, skipping (inspect manually)")

    print("\nDone. Now run:\n"
          "  hermes plugins enable google_meet\n"
          "  hermes meet install\n"
          "  systemctl --user restart hermes-gateway-<profile>.service\n"
          "Then see references/auth-setup.md to authenticate.")


if __name__ == "__main__":
    main()
