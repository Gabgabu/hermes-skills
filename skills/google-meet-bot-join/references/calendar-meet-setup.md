# Calendar, organizer identity, and the lobby

## Why "the bot scheduled it" doesn't mean "the bot is host"

Google Calendar sets the true event organizer/host as whichever
account/calendar *created* the event — not whoever is listed as an
attendee, and not whoever has "guest can modify" permissions. If the bot
fabricates or improvises a meeting link some other way (e.g. asking an LLM
to "create a meeting" without an actual Calendar API call, or generating
an ad-hoc `meet.google.com/xxx-xxxx-xxx` code through a different,
unauthenticated browsing tool), nobody has real host authority over that
room — not even the human who later joins it. In that situation no one can
admit anyone, and a "knock" may not even register properly.

The only reliable way to make the bot a genuine host: create the event
through Calendar using the **same account** that's authenticated in
`auth.json`, with `--meet` (see auth-setup.md and the installer's patch
#11). Then `meet_join` on that event's Meet link goes straight in, no
admission needed, because the bot is the organizer.

## If the meeting is created by someone else

The bot needs a human to manually admit it from the lobby — every single
time, there's no bypass for this. The documented Google behavior ("guests
explicitly invited via Calendar skip the lobby") only applies to the
*human* attendee on that invite; it does not transitively grant the bot
host rights just because it's also listed somewhere.

If you want the bot to be able to join meetings *you* create without
manual admission each time, you'd need to either:
- Add the bot's account as an explicit Calendar guest on each event (it
  may still see a knock-free join in many configurations, but verify —
  this depends on the Workspace org's external-guest policies and isn't
  guaranteed), or
- Always have the bot be the one to create the event (this skill's
  primary supported path), or
- Accept that someone has to admit it from the lobby for ad-hoc/guest
  joins, and have the bot say so plainly rather than claiming success
  (see SKILL.md's join workflow — don't assume `meet_join`'s immediate
  return means anything; poll `meet_status` for `inCall: true`).
