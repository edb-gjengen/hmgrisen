import platform
from collections import Counter
from os import environ
from os import getpid
from os.path import exists
from time import time

import discord
from discord import app_commands
from discord.ext import commands
from psutil import Process

from cogs.utils import discord_utils


class BotInfo(commands.Cog):
    """View information about the bot"""

    def __init__(self, bot: commands.Bot):
        """
        Parameters
        ----------
        bot (commands.Bot): The bot instance
        """

        self.bot = bot

    @app_commands.checks.bot_has_permissions(embed_links=True, external_emojis=True)
    @app_commands.checks.cooldown(1, 2)
    @app_commands.command(name="botinfo", description="Se informasjon om botten")
    async def botinfo(self, interaction: discord.Interaction):
        """
        View information about the bot

        Parameters
        ----------
        interaction (discord.Interaction): The slash command interaction
        """

        # Memory usage
        process = Process(getpid())
        memory_usage = round(process.memory_info().rss / 1000000, 1)

        # Member stats
        # Presences are only available on members, and a user in several servers shows up once per server,
        # so key by id to count every user once
        statuses = {member.id: member.status for member in self.bot.get_all_members()}
        status_counts = Counter(statuses.values())

        # Build embed
        embed = discord.Embed(color=interaction.client.user.color, url=environ["BOT_MISC_WEBSITE"])
        embed.set_thumbnail(url=self.bot.user.display_avatar)
        embed.add_field(name="Dev", value="EDB-gjengen")
        embed.add_field(name="Oppetid", value=self.get_uptime())
        embed.add_field(name="Ping", value=f"Websocket ping: {self.get_ping()} ms")
        embed.add_field(name="Servere", value=len(self.bot.guilds))
        embed.add_field(name="Discord.py", value=discord.__version__)
        embed.add_field(name="Python", value=platform.python_version())
        embed.add_field(name="Ressursbruk", value=f"RAM: {memory_usage} MB")
        embed.add_field(name="Kernel", value=f"{platform.system()} {platform.release()}")
        if exists("/.dockerenv"):
            embed.add_field(name="Docker", value="✅")
        embed.add_field(
            name=f"Brukere ({len(statuses)})",
            value=discord_utils.format_status_counts(status_counts, self.bot.emoji, "\n"),
        )
        embed.add_field(
            name="Lenker",
            value=f'[Nettside]({environ["BOT_MISC_WEBSITE"]}) | ' + f'[Kildekode]({environ["BOT_MISC_SOURCE"]})',
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.checks.bot_has_permissions(embed_links=True)
    @app_commands.checks.cooldown(1, 2)
    @app_commands.command(name="oppetid", description="Se hvor lenge botten har kjørt")
    async def uptime(self, interaction: discord.Interaction):
        """
        View the bot's uptime

        Parameters
        ----------
        interaction (discord.Interaction): The slash command interaction
        """

        embed = discord.Embed(color=interaction.client.user.color)
        embed.add_field(name="🔌 Oppetid", value=self.get_uptime())
        await interaction.response.send_message(embed=embed)

    @app_commands.checks.bot_has_permissions(embed_links=True)
    @app_commands.checks.cooldown(1, 2)
    @app_commands.command(name="ping", description="Se botten sin nåværende ping")
    async def ping(self, interaction: discord.Interaction):
        """
        View the bot's ping

        Parameters
        ----------
        interaction (discord.Interaction): The slash command interaction
        """

        embed = discord.Embed(color=interaction.client.user.color)
        embed.add_field(name="📶 Ping", value=f"* **Websocket ping:** {self.get_ping()} ms\n* **I hodet:** ∞")
        await interaction.response.send_message(embed=embed, content=None)

    def get_ping(self) -> int:
        """
        Get the bot's ping in milliseconds

        Returns
        ----------
        (int): The bot's ping in milliseconds
        """

        return int(self.bot.latency * 1000)

    def get_uptime(self) -> str:
        """
        Returns the current uptime of the bot in string format

        Returns
        ----------
        (str): The bot's uptime in human readable format
        """

        now = time()
        diff = int(now - self.bot.uptime)
        days, remainder = divmod(diff, 24 * 60 * 60)
        hours, remainder = divmod(remainder, 60 * 60)
        minutes, seconds = divmod(remainder, 60)

        return f"{days}d, {hours}t, {minutes}m, {seconds}s"


async def setup(bot: commands.Bot):
    """
    Add the cog to the bot on extension load

    Parameters
    ----------
    bot (commands.Bot): The bot instance
    """

    await bot.add_cog(BotInfo(bot))
