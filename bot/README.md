# H.M. Grisen

A multi-purpose Discord bot for the Discord server of The Norwegian Student Society

## Get started

0. Create a bot user / obtain a bot token. [See this guide](https://discordpy.readthedocs.io/en/stable/discord.html). Also enable all three _Privileged Gateway Intents_ (Presence, Server Members and Message Content) under "Bot" in the Developer Portal. The bot requests all intents and won't start without them

1. Make a copy of the `.env.example` file and rename it to `.env`

2. Make sure all the fields are filled

`BOT_CONFIG_MODE` decides where the slash commands are synced. With `dev` they're only synced to the server in `BOT_DEV_GUILD`, where they show up right away. With `prod` they're synced globally. In both modes, `BOT_DEV_GUILD` is also the server where the bot assigns Galtinn roles.

Use a separate bot user when developing locally. If you run `dev` with the production bot's token, the server in `BOT_DEV_GUILD` gets both the global commands and the copies, and every command shows up twice. The bot logs a warning when that happens. In `prod`, commands left in `BOT_DEV_GUILD` from earlier `dev` runs are removed automatically.

Given a user with a access to a database the bot will create all the necessary tables by itself.

You have two options to run the bot:

### Option 1 - Docker (Recommended)

From the root of the repository, which starts both:

```
docker compose up
```

### Option 2 - Manual

0. Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right Python version for you

1. Install dependencies. The bot and the verification server share one project and one `uv.lock`, at the root of the repository

```
uv sync
```

2. Run bot, from this folder

```
uv run src/run.py
```
