# hermes-skills

Custom skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

## Installing a skill

```
hermes skills install Gabgabu/hermes-skills/skills/<skill-name>
```

Or browse this repo and install from a specific SKILL.md URL directly:

```
hermes skills install https://raw.githubusercontent.com/Gabgabu/hermes-skills/main/skills/<skill-name>/SKILL.md
```

## Skills in this repo

| Skill | Description |
|---|---|
| [`google-meet-bot-join`](skills/google-meet-bot-join) | Reliable Google Meet join, in-call chat, and post-call summarization — patches the bundled `google_meet` plugin's automation-detection, race-condition, and auth-wiring bugs, and adds a `meet_chat` tool. |

## Contributing

Each skill lives in its own folder under `skills/`, following the standard
Hermes skill layout:

```
skills/<skill-name>/
  SKILL.md          # required — frontmatter (name, description, version, ...) + usage docs
  scripts/           # optional — installer/helper scripts referenced from SKILL.md
  references/        # optional — supporting docs referenced from SKILL.md
```

See [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
for the skill format spec.
