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