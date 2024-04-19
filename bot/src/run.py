import os
from time import time

import asyncpg
import discord
from discord.ext import commands
from dotenv import load_dotenv
from logger import BotLogger

# Load config file
load_dotenv()


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(os.environ["BOT_PREFIX"]),
            case_insensitive=True,
            intents=discord.Intents.all(),
            allowed_mentions=discord.AllowedMentions(everyone=False),
        )

        self.logger = BotLogger().logger  # Initialize logger

        self.cog_files = set(os.listdir("./src/cogs"))

        self.galtinn = {
            "api_url": os.environ.get("GALTINN_API_URL", "http://127.0.0.1:8000"),
            "client_id": os.environ.get("GALTINN_CLIENT_ID"),
            "redirect_uri": os.environ.get("GALTINN_REDIRECT_URI"),
            "auth_token": os.environ.get("GALTINN_AUTH_TOKEN"),
        }
        self.galtinn_roles = {
            "member": os.environ.get("GALTINN_MEMBER_ROLE"),
            "volunteer": os.environ.get("GALTINN_VOLUNTEER_ROLE"),
        }

        self.guild_id = os.environ.get("BOT_DEV_GUILD", 1162158668079444199)

    async def setup_hook(self):
        # DB needs to be setup here because contructor is not async
        # Not ideal but does the job
        credentials = {
            "host": os.environ["DATABASE_HOST"],
            "database": os.environ["DATABASE_NAME"],
            "user": os.environ["DATABASE_USER"],
            "password": os.environ["DATABASE_PASSWORD"],
        }
        self.db = await asyncpg.create_pool(**credentials)

        # Load cogs
        cogs = os.listdir("./src/cogs")
        for file in cogs:
            if file.endswith(".py"):
                name = file[:-3]
                await bot.load_extension(f"cogs.{name}")

        # Sync slash commands
        if os.environ.get("CONFIG_MODE") == "prod":
            await self.tree.sync()
        else:
            self.tree.copy_global_to(guild=discord.Object(id=self.guild_id))
            await self.tree.sync(guild=discord.Object(id=self.guild_id))


# Create bot instance
bot = Bot()


@bot.event
async def on_ready():
    if not hasattr(bot, "uptime"):
        bot.uptime = time()

    # Print bot info
    print(f"Username:        {bot.user.name}")
    print(f"ID:              {bot.user.id}")
    print(f"Version:         {discord.__version__}")
    print("." * 50 + "\n")

    # Set initial presence
    # Presence status
    status_types = {
        "online": discord.Status.online,
        "dnd": discord.Status.dnd,
        "idle": discord.Status.idle,
        "offline": discord.Status.offline,
    }
    status_type = status_types.get(os.environ.get("BOT_PRESENCE_STATUS").lower(), discord.Status.online)

    # Presence actitivity
    activities = {"playing": 0, "listening": 2, "watching": 3}
    activity_type = activities.get(os.environ.get("BOT_PRESENCE_ACTIVITY").lower(), 0)

    await bot.change_presence(
        activity=discord.Activity(type=activity_type, name=os.environ.get("BOT_PRESENCE_MESSAGE", "Yeet")),
        status=status_type,
    )


bot.run(os.environ["BOT_TOKEN"], reconnect=True, log_handler=None)
