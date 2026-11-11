<img align="right" src="https://preview.redd.it/jn16whkslzv71.png?width=640&crop=smart&auto=webp&s=3a961c72d5a5648c2e00f3bf4a0860d0f6278ee0" width=400 />  

<img  src="https://cdn.discordapp.com/attachments/908104736455155762/963925809284919366/Animation-logo-emoji-discord.gif" width=400 />


![](https://img.shields.io/badge/code%20style-black-black?style=for-the-badge)

[![MakeDockerImage](https://github.com/battlefield-portal-community/ranger/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/battlefield-portal-community/ranger/actions/workflows/docker-publish.yml)

## $Ranger$ is  a general purpose discord bot. Handcrafted for The Battlefield Discord Community 

## Docker Health Check

Ranger exposes its gateway liveness through Docker's built-in `HEALTHCHECK`.

The bot periodically writes its current gateway state (timestamp and gateway latency) to a small state file. The health probe reads this file and reports the container as:

- **healthy** when the state file is fresh and the Discord gateway latency is finite.
- **unhealthy** when the state file becomes stale or the gateway latency is infinite (indicating the bot has lost its gateway connection).

This allows Docker to monitor whether the bot is actually connected to Discord rather than only checking that the Python process is running.

The behaviour can be configured through the following environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_SETTINGS__HEALTH_STATE_FILE` | `/tmp/ranger.health` | Path to the health state file. |
| `BOT_SETTINGS__HEALTH_HEARTBEAT_INTERVAL` | `15` | Seconds between health state updates. |
| `BOT_SETTINGS__HEALTH_STALE_THRESHOLD` | `45` | Maximum allowed age (in seconds) of the health state before the probe reports the container as unhealthy. |
## Feedback Intake

One channel (`📮・submit-feedback`) is the only way into the bug and feature forums:
a reporter presses a button, fills a modal and nothing else. Ranger files the post
in the right forum, applies the tags, and records who reported it, the body it
filed and the thread's status in SQLite.

- **Bug form:** Title · What happened · Steps to reproduce · optional media.
- **Feature form:** Title · Your request · How it helps · Example (optional) · optional media.
  The free-text fields say markdown is supported, because it reaches the post as-is,
  and a field left empty is left out of the filed body.
- **Reporter credit:** the starter message ends with a small-type `Reported by
  @reporter`; the game is carried by the applied tag, not repeated in the body.
- **Tags at creation:** every post carries the game tag (`BF6`); a feature request
  also carries `feature-request`. The forums require a tag, so these are never empty.
- **Status is the thread's own tag.** Staff change it with Discord's "Edit Tags";
  `on_thread_update` mirrors the result into `feedback_posts.status`. Nothing acts on
  it yet — the mirror exists so the later forum cleanup pass has history to query. A
  retag made while the bot is offline is missed by design; the tags in Discord stay
  the truth.
- **Dedupe:** before filing, the report is searched (SQLite FTS5, no privileged
  intents) against earlier posts. A likely duplicate offers *Open existing* or *File
  anyway*; filing anyway is written to `feedback_events`.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID` | *(unset)* | Channel holding the intake message. The cog logs once and stays inert while it is unset, so an image can ship before the channel exists. |
| `FEEDBACK_COG_SETTINGS__BUG_FORUM_ID` | `1403608614899421294` | Bug forum. |
| `FEEDBACK_COG_SETTINGS__FEATURE_FORUM_ID` | `1006491137441276005` | Feature forum. |
| `FEEDBACK_COG_SETTINGS__DEFAULT_GAME_TAG` | `BF6` | Game tag stamped on every post. |
| `FEEDBACK_COG_SETTINGS__FEATURE_TAG` | `feature-request` | Tag marking a post as a feature request. |
| `FEEDBACK_COG_SETTINGS__MAX_UPLOAD_FILES` | `5` | Upload slots offered in the form; Discord's own maximum is 10. |

### Discord setup (manual, once)

1. Create `📮・submit-feedback`, deny `Send Messages` for `@everyone` so only the
   intake message lives there, and set `FEEDBACK_COG_SETTINGS__MENU_CHANNEL_ID`.
2. Give the bot View Channel, Send Messages, Create Posts, Read Message History,
   Attach Files and Embed Links in both forums and in the intake channel.
   `Manage Threads` is not needed: the bot never edits a thread's tags.
3. Check the forum tags. They are resolved by name, case-insensitively, and both
   forums' real tags are logged at startup so a rename is visible instead of silent:
   - bug forum: `BF6`, `Noted`, `Patched`, `Needs Info`, `Duplicate`, `Editor`,
     `Scripts`, `Godot`, `Rules editor`;
   - feature forum: `BF6`, `BF2042`, `feature-request`, `Noted`, `Added`,
     `Needs Info`, `Duplicate`, `game-ui`, `logic-editor`, `godot`.

   Two known holes: **`BF2042` is missing from the bug forum**, so a BF2042 bug can
   only be tagged `BF6`, and there is **no `Working` or `Declined` tag in either
   forum**, so those statuses never appear until someone creates them.
4. Optional, to let the dedupe cover threads posted before this cog existed:
   `python -m app.seed_feedback <discordchatexporter-export-dir>`. It is safe to
   re-run; threads already stored are skipped.

### Testing on a scratch server

With a bot that has **Administrator** in a test server, one command creates the
category, both forums with the tags above (plus `Working` and `Declined`, which the
live forums still lack) and the `@everyone`-muted intake channel, then starts the
bot against them:

```sh
python -m app.setup_feedback_test --guild-id <test server id> --run
```

Add `--dry-run` to see what it would do — which category, forums, tags and the
intake channel it would create or edit — without creating, editing or writing
anything.

Re-running is safe: existing channels are reused and only missing forum tags are
added, nothing is deleted. Without `--run` it prints the three
`FEEDBACK_COG_SETTINGS__*` ids instead — add `--env-file .env` to write them into a
file — so you can restart the bot however you normally do.

Point `BOT_SETTINGS__GUILD_ID` at the same test server, or the intake message and
the synced commands belong to another guild.
