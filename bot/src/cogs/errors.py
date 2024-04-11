import traceback

import discord
from cogs.utils import embed_templates
from discord import app_commands
from discord.ext import commands


class Errors(commands.Cog):
    """Error handlers for commands"""

    def __init__(self, bot: commands.Bot):
        """
        Parameters
        ----------
        bot (commands.Bot): The bot instance
        """

        self.bot = bot
        bot.tree.on_error = self.on_app_command_error  # Set error handler for slash commands

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        """
        Logs prefix command execution metadata

        Parameters
        ----------
        ctx (commands.Context): Context object
        """

        self.bot.logger.info(
            f'{"❌ " if ctx.command_failed else "✔ "} {ctx.command} | '
            + f"{ctx.author.name} ({ctx.author.id}) | "
            + f"{ctx.guild.id}-{ctx.channel.id}-{ctx.message.id}"
        )

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command | app_commands.ContextMenu
    ):
        """
        Logs slash command execution metadata

        Parameters
        ----------
        interaction (discord.Interaction): Slash command context object
        command (app_commands.Command | app_commands.ContextMenu): Command object
        """

        self.bot.logger.info(
            f'{"❌ " if interaction.command_failed else "✔ "} {command.name} | '
            + f"{interaction.user.name} ({interaction.user.id}) | "
            + f"{interaction.guild_id}-{interaction.channel_id}-{interaction.id}"
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """
        Handle prefix command errors

        Parameters
        ----------
        ctx (commands.Context): Context object
        error (commands.CommandError): Eror context object
        """

        # Reset cooldown if command throws AttributeError
        try:
            self.bot.get_command(f"{ctx.command}").reset_cooldown(ctx)
        except AttributeError:
            pass

        # Ignore command's own error handling
        if hasattr(ctx.command, "on_error"):
            return

        error = getattr(error, "original", error)

        # Ignored errors
        ignored_errors = (commands.CommandNotFound, commands.DisabledCommand, commands.CheckFailure)
        if isinstance(error, ignored_errors):
            self.bot.logger.info("Ignored error", error)
            return

        # Errors that should prompt a help message
        send_help = (commands.MissingRequiredArgument, commands.TooManyArguments, commands.BadArgument)
        if isinstance(error, send_help):
            return await ctx.send_help(ctx.command)

        elif isinstance(error, commands.BotMissingPermissions):
            embed = self.error_missing_perms(error.missing_permissions, "Jeg")
        elif isinstance(error, commands.MissingPermissions):
            embed = self.error_missing_perms(error.missing_permissions, "Du")
        elif isinstance(error, commands.NotOwner):
            embed = embed_templates.error_warning("Bare boteieren kan gjøre dette")
        elif isinstance(error, commands.CommandOnCooldown):
            embed = embed_templates.error_warning(
                f"Kommandoen har nettopp blitt brukt\nPrøv igjen om `{error.retry_after:.1f}` sekunder.",
            )
        elif isinstance(error, commands.NoPrivateMessage):
            embed = embed_templates.error_warning("Denne kommandoen kan bare utføres it servere")
        else:
            embed = embed_templates.error_fatal("En ukjent feil oppstod!")
            f = discord.File("./src/assets/edb.png")
            embed.set_image(url="attachment://edb.png")

        # Yeah, this fucking sucks but I want my beautiful edb picture :_;
        try:
            f
        except NameError:
            f = None

        try:
            await ctx.reply(embed=embed, file=f)
        except discord.errors.Forbidden:
            self.bot.logger.warning("Could not send error message to user")
        except app_commands.BotMissingPermissions:
            await ctx.reply(
                "Jeg mangler `embed_links` og/eller `attach_files` tillatelsen(e). Ingenting funker uten de"
            )

        # Log full exception to file
        self.bot.logger.error("".join(traceback.format_exception(type(error), error, error.__traceback__)))

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """
        Handle slash command errors

        Parameters
        ----------
        interaction (discord.Interaction): Slash command context object
        error (app_commands.AppCommandError): Eror context object
        """

        await interaction.response.defer()

        # Log command usage, just in case
        await self.on_app_command_completion(interaction, interaction.command)

        if isinstance(error, app_commands.BotMissingPermissions):
            embed = self.error_missing_perms(error.missing_permissions, "Jeg")
        elif isinstance(error, app_commands.MissingPermissions):
            embed = self.error_missing_perms(error.missing_permissions, "Du")
        elif isinstance(error, app_commands.CommandOnCooldown):
            embed = embed_templates.error_warning(
                f"Kommandoen har nettopp blitt brukt\nPrøv igjen om `{error.retry_after:.1f}` sekunder."
            )
        else:
            embed = embed_templates.error_fatal("En ukjent feil oppstod!")
            f = discord.File("./src/assets/edb.png")
            embed.set_image(url="attachment://edb.png")

        # Yeah, this fucking sucks but I want my beautiful edb picture :_;
        try:
            f
        except NameError:
            f = None

        try:
            await interaction.followup.send(embed=embed, file=f)
        except discord.errors.Forbidden:
            self.bot.logger.warning("Could not send error message to user")
        except app_commands.BotMissingPermissions:
            await interaction.followup.send(
                "Jeg mangler `embed_links` og/eller `attach_files` tillatelsen(e). Ingenting funker uten de"
            )

        # Log full exception to file
        self.bot.logger.error("".join(traceback.format_exception(type(error), error, error.__traceback__)))

    def error_missing_perms(self, permissions: list[str], client: str) -> discord.Embed:
        """
        Missing permissions embed template.
        Since it only applies to this cog it has been put here instead of the util file

        Parameters
        ----------
        permissions (list[str]): The missing permissions
        client (str): Who is missing the permissions? Typically "Du" (user) or "Jeg" (bot client)

        Returns
        ----------
        (discord.Embed): The final embed
        """

        permissions = ", ".join(permissions)
        return embed_templates.error_warning(f"{client} mangler følgende tillatelser\n\n```{permissions}\n```")


async def setup(bot: commands.Bot):
    """
    Add the cog to the bot on extension load

    Parameters
    ----------
    bot (commands.Bot): Bot instance
    """

    await bot.add_cog(Errors(bot))
