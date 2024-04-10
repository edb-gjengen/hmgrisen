import asyncio
import secrets
import urllib.parse

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks

from cogs.utils import embed_templates
from cogs.utils import misc_utils


class Galtinn(commands.Cog):
    """Manage Galtinn membership and roles for users"""

    def __init__(self, bot: commands.Bot):
        """
        Parameters
        ----------
        bot (commands.Bot): The bot instance
        """

        self.bot = bot
        self.cursor = self.bot.db_connection.cursor()

        self.init_db()

    def init_db(self):
        """
        Create the necessary tables for the cog to work
        """

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS galtinn_users (
                discord_id BIGINT PRIMARY KEY,
                galtinn_id TEXT NOT NULL
            );
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS galtinn_verification (
                discord_id BIGINT PRIMARY KEY,
                challenge TEXT NOT NULL,
                state TEXT NOT NULL
            );
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS galtinn_roles (
                galtinn_org_id TEXT PRIMARY KEY,
                discord_role_id BIGINT NOT NULL
            );
            """
        )

    def cog_unload(self):
        self.bot.logger.info("Unloading cog")
        self.membership_check.cancel()
        self.cursor.close()

    @tasks.loop(time=misc_utils.MIDNIGHT)
    async def membership_check(self):
        """
        Checks all registered user's membership status and assigns roles based on the status
        """

        self.cursor.execute(
            """
            SELECT *
            FROM galtinn_users;
            """
        )

        if not (results := self.cursor.fetchall()):
            self.bot.logger.info("No registered users found")

        for result in results:
            discord_id, galtinn_id = result

            user = self.bot.get_user(discord_id)  # Try fetching discord user from cache
            if not user:
                user = await self.bot.fetch_user(discord_id)  # Use API call to fetch if not found

            if not user:
                self.bot.logger.info(f"User with ID {discord_id} not found")
                continue

            # Fetch membership status

            # Set roles

    @membership_check.before_loop
    async def before_membership_check(self):
        """
        Make sure bot is ready before starting the membership check loop
        """

        await self.bot.wait_until_ready()

    galtinn_group = app_commands.Group(name="galtinn", description="Koble Galtinnbrukeren din til Discord")

    @app_commands.checks.bot_has_permissions(embed_links=True)
    @galtinn_group.command(name="registrer", description="Koble Galtinnbrukeren din til Discord")
    async def register(self, interaction: discord.Interaction):
        """
        Connect your Galtinn account to your Discord account

        Parameters
        ----------
        interaction (discord.Interaction): Slash command context object
        """

        await interaction.response.defer()

        # Check if user is already registered
        self.cursor.execute(
            """
            SELECT *
            FROM galtinn_users
            WHERE discord_id = %s
            """,
            (interaction.user.id,),
        )
        if self.cursor.fetchone():
            embed = embed_templates.error_warning("Du er allerede registrert med en Galtinnbruker!")
            await interaction.followup.send(embed=embed)
            return

        # Check if user is already pending verification
        self.cursor.execute(
            """
            SELECT *
            FROM galtinn_verification
            WHERE discord_id = %s
            """,
            (interaction.user.id,),
        )
        if self.cursor.fetchone():
            embed = embed_templates.error_warning("Du har allerede en pågående verifikasjon!")
            await interaction.followup.send(embed=embed)
            return

        # Generate OAuth2 URL
        challenge = f"{secrets.token_urlsafe(32)}"  # TODO: generate challenge based on private key?
        state = f"{secrets.token_urlsafe(32)}"
        base_url = f"{self.bot.galtinn['api_url']}/oauth/authorize/"
        params = {
            "client_id": self.bot.galtinn["client_id"],
            "scope": "openid profile email",
            "response_type": "code",
            "redirect_uri": self.bot.galtinn["redirect_uri"],
            "code_challenge": challenge,
            "state": state,
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        # Insert into verfications table
        self.cursor.execute(
            """
            INSERT INTO galtinn_verification
            VALUES (%s, %s, %s)
            """,
            (interaction.user.id, challenge, state),
        )

        self.bot.logger.info(f"Generated challenge for user {interaction.user.id}")

        embed = discord.Embed(title="Koble Galtinnbrukeren din til Discord", color=discord.Color.orange())
        embed.description = (
            "Klikk på lenken under for å koble Galtinnbrukeren din til Discord\n\n"
            + f"{url}\n\nDu har 2 minutter på deg til å fullføre verifikasjonen."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await asyncio.sleep(120)
        self.cursor.execute(
            """
            DELETE FROM galtinn_verification
            WHERE discord_id = %s;
            """,
            (interaction.user.id,),
        )

    @app_commands.checks.bot_has_permissions(embed_links=True)
    @galtinn_group.command(name="slett", description="Fjern koblingen mellom Galtinnbrukeren din og Discord")
    async def delete(self, interaction: discord.Interaction):
        """
        Remove the connection between your Galtinn user and Discord

        Parameters
        ----------
        interaction (discord.Interaction): Slash command context object
        """

        await interaction.response.defer()

        self.cursor.execute(
            """
            SELECT * FROM galtinn_users
            WHERE discord_id = %s
            """,
            (interaction.user.id,),
        )
        if not self.cursor.fetchone():
            embed = embed_templates.error_warning("Du er ikke registrert med en Galtinnbruker!")
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(title="Fjern bruker", color=discord.Color.yellow())
        embed.description = (
            "Er du sikker på at du vil slette koblingen mellom Galtinnbrukeren din og Discord?\n\n"
            + "Merk at roller knyttet til Galtinn vil bli fjernet."
        )
        await interaction.followup.send(embed=embed, view=DeleteView(self.bot, self.cursor), ephemeral=True)


class DeleteView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cursor):
        super().__init__()
        self.bot = bot
        self.cursor = cursor

    @discord.ui.button(label="Ja, slett", style=discord.ButtonStyle.danger, custom_id="delete_yes")
    async def delete_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.logger.info(f"Deleting user {interaction.user.id}")

        # Remove Roles

        # Delete user from database
        self.cursor.execute(
            """
            DELETE FROM galtinn_users
            WHERE discord_id = %s
            """,
            (interaction.user.id,),
        )
        embed = embed_templates.success("Du har slettet tilkoblingen til Galtinnbrukeren din!")
        await interaction.message.edit(embed=embed, view=None)

    @discord.ui.button(label="Avbryt", style=discord.ButtonStyle.primary, custom_id="delete_no")
    async def delete_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = embed_templates.error_warning("Sletting avbrutt")
        await interaction.message.edit(embed=embed, view=None)


async def setup(bot: commands.Bot):
    """
    Add the cog to the bot on extension load

    Parameters
    ----------
    bot (commands.Bot): Bot instance
    """

    await bot.add_cog(Galtinn(bot))
