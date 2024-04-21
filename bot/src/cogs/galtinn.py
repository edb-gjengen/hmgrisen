import asyncio
import secrets
import urllib.parse
from datetime import datetime

import aiohttp
import discord
from cogs.utils import discord_utils
from cogs.utils import embed_templates
from cogs.utils import misc_utils
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from models import DiscordProfiles
from models import DuskenUser
from models import Groups
from models import Users


class Galtinn(commands.Cog):
    """Manage Galtinn membership and roles for users"""

    def __init__(self, bot: commands.Bot):
        """
        Parameters
        ----------
        bot (commands.Bot): The bot instance
        """

        self.bot = bot

        self.membership_check.start()
        self.verification_cleanup.start()
        asyncio.create_task(self.listen_db())

    def cog_unload(self):
        self.bot.logger.info("Unloading cog")
        self.membership_check.cancel()
        self.verification_cleanup.cancel()

    async def init_db(self):
        """
        Create the necessary tables for the cog to work
        """

        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS galtinn_verification (
                discord_id BIGINT PRIMARY KEY,
                challenge TEXT NOT NULL,
                state TEXT NOT NULL,
                expires TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc') + INTERVAL '2 minutes'
            );
            """
        )

    async def listen_db(self):
        """
        Creates a listener for galitnn_auth_complete events from the database and processes them
        """

        async def process_notification(conn, pid, channel, payload):
            if channel != "galtinn_auth_complete":
                return

            self.bot.logger.info("Received galtinn_auth_complete event from database")

            # Surely, no one would ever send a bad payload, right? RIGHT???
            discord_user_id, galtinn_user_id = payload.split(" ")

            # Fetch Galtinn user
            if not (
                galtinn_users := await self.fetch_galtinn_users(
                    galtinn_user_id=int(galtinn_user_id), discord_id=int(discord_user_id)
                )
            ):
                self.bot.logger.error(f"Failed to fetch user with ID {discord_user_id}. Not found")
                return

            galtinn_user = galtinn_users.results[0]

            # Fetch Discord user
            if not (guild := await discord_utils.get_discord_guild(self.bot, self.bot.guild_id)):
                self.bot.logger.error("Failed to fetch guild. Can't convert role ids to objects. Roles not applied")
                return
            if not (discord_user := await discord_utils.get_guild_member(self.bot, guild, discord_user_id)):
                self.bot.logger.error(f"Failed to fetch member with ID {discord_user_id}. Not found")
                return

            # Fetch and give roles
            roles_to_add, roles_to_remove = await self.get_user_galtinn_roles(galtinn_user)
            await self.update_roles(discord_user, roles_to_add, roles_to_remove)

        conn = await self.bot.db.acquire()
        await conn.add_listener("galtinn_auth_complete", process_notification)

        while True:
            await asyncio.sleep(1)

    async def fetch_galtinn_users(
        self, galtinn_user_id: int | None = None, discord_id: int | None = None, page: int = 1
    ) -> Users | None:
        """
        Attempts to fetch user(s) from Galtinn. If no parameters are given, all users are fetched
        """

        async def fetch_page(url: str):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Token {self.bot.galtinn['auth_token']}"},
                ) as r:
                    if r.status == 404:
                        self.bot.logger.info(f"No users found in Galtinn with the given parameters {params}")
                        return None
                    if r.status != 200:
                        self.bot.logger.warning(f"Failed to fetch galtinn user(s). Status: {r.status}")
                        return None

                    data = await r.json()
                    users = Users(**data)

                    return users

        params = {"no_discord_id": False, "page": page, "format": "json"}
        if discord_id:
            params["discord_profile__discord_id"] = discord_id
        if galtinn_user_id:
            params["id"] = galtinn_user_id

        initial_url = f"{self.bot.galtinn['api_url']}/users/?{urllib.parse.urlencode(params)}"
        galtinn_users = await fetch_page(initial_url)
        if not galtinn_users:
            return None

        if galtinn_users.count == 0:
            return galtinn_users

        # Due to pagination we have to do this hacky workaround.
        # I do not like the fact that we're modifying a return object like this just to satisfy the return type
        # and it should probably be changed in the future.
        # I do, however, not have the time to find a better way right now
        all_galtinn_users = galtinn_users.copy()
        while galtinn_users.next:
            self.bot.logger.info(f"Fetching next page. {galtinn_users.next}")
            galtinn_users = await fetch_page(galtinn_users.next)
            if not galtinn_users or galtinn_users.count == 0:
                break
            all_galtinn_users.results.extend(galtinn_users.results)
            all_galtinn_users.count += galtinn_users.count

        # This doesn't make any difference but feels cleaner I guess
        all_galtinn_users.next = None
        all_galtinn_users.previous = None

        return all_galtinn_users

    async def fetch_galtinn_discordprofiles(
        self, galtinn_user_id: int | None = None, discord_id: int | None = None, page: int = 1
    ) -> DiscordProfiles | None:
        """
        Attempts to fetch discord profile(s) from Galtinn. If no parameters are given, all profiles are fetched
        """

        async def fetch_page(url: str):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Token {self.bot.galtinn['auth_token']}"},
                ) as r:
                    if r.status == 404:
                        self.bot.logger.info(f"No discord profiles found in Galtinn with the given parameters {params}")
                        return None
                    if r.status != 200:
                        self.bot.logger.warning(f"Failed to fetch galtinn user(s). Status: {r.status}")
                        return None

                    data = await r.json()
                    discord_profiles = DiscordProfiles(**data)

                    return discord_profiles

        params = {"page": page, "format": "json"}
        if discord_id:
            params["discord_id"] = discord_id
        if galtinn_user_id:
            params["user"] = galtinn_user_id

        initial_url = f"{self.bot.galtinn['api_url']}/discordprofiles/?{urllib.parse.urlencode(params)}"

        discord_profiles = await fetch_page(initial_url)
        if not discord_profiles:
            return None

        if discord_profiles.count == 0:
            return discord_profiles

        # Due to pagination we have to do this hacky workaround.
        # I do not like the fact that we're modifying a return object like this just to satisfy the return type
        # and it should probably be changed in the future.
        # I do, however, not have the time to find a better way right now
        all_discord_profiles = discord_profiles.copy()
        while discord_profiles.next:
            discord_profiles = await fetch_page(discord_profiles.next)
            if not discord_profiles or discord_profiles.count == 0:
                break
            all_discord_profiles.results.extend(discord_profiles.results)
            all_discord_profiles.count += discord_profiles.count

        # This doesn't make any difference but feels cleaner I guess
        all_discord_profiles.next = None
        all_discord_profiles.previous = None

        return all_discord_profiles

    async def fetch_all_galtinn_roles(self) -> set[int] | None:
        """
        Fetch all roles connected to Galtinn groups

        Returns
        ----------
        set(int) | None: Set of role ids or None if failed
        """

        async def fetch_page(url: str):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Token {self.bot.galtinn['auth_token']}"},
                ) as r:
                    if r.status == 404:
                        self.bot.logger.info("No groups found in Galtinn")
                        return None
                    if r.status != 200:
                        self.bot.logger.warning(f"Failed to fetch groups from Galtinn. Status: {r.status}")
                        return None

                    data = await r.json()
                    groups = Groups(**data)

                    return groups

        all_roles = {self.bot.galtinn_roles["volunteer"], self.bot.galtinn_roles["member"]}

        params = {"no_discord_roles": False, "format": "json"}
        initial_url = f"{self.bot.galtinn['api_url']}/groups/?{urllib.parse.urlencode(params)}"

        groups = await fetch_page(initial_url)
        if not groups or groups.count == 0:
            return None

        for group in groups.results:
            for discord_role in group.profile.discord_roles:
                all_roles.add(discord_role.discord_id)

        # Due to pagination we have to do this hacky workaround.
        while groups.next:
            groups = await fetch_page(groups.next)
            if not groups or groups.count == 0:
                break
            for group in groups.results:
                for discord_role in group.profile.discord_roles:
                    all_roles.add(discord_role.discord_id)

        return all_roles

    async def get_user_galtinn_roles(self, galtinn_user: DuskenUser) -> tuple[set, set]:
        """
        Get which roles to add and which to remove based on the user's Galtinn membership status

        Parameters
        ----------
        galtinn_user (DuskenUser): Galtinn user object

        Reuturns
        ----------
        tuple[set[int], set[int]]: Role ids to add, role ids to remove
        """

        # Make sure we have the latest roles
        all_roles = await self.fetch_all_galtinn_roles()

        roles_to_add = set()
        roles_to_remove = set()

        if galtinn_user.is_volunteer:
            roles_to_add.add(self.bot.galtinn_roles["volunteer"])
        if galtinn_user.is_member:
            roles_to_add.add(self.bot.galtinn_roles["member"])

        if not galtinn_user.groups:
            return roles_to_add, roles_to_remove

        for group in galtinn_user.groups:
            # TODO: add a filter for this in the API?
            if not group.profile or not group.profile.discord_roles:
                continue

            for discord_role in group.profile.discord_roles:
                roles_to_add.add(discord_role.discord_id)

        roles_to_remove = all_roles - roles_to_add

        return roles_to_add, roles_to_remove

    async def update_roles(self, user: discord.Member, roles_to_add: set, roles_to_remove: set) -> bool:
        """
        Attempts to assign and remove roles to/from a user.

        Parameters
        ----------
        user (discord.Member): Discord user
        roles_to_add (set): Role ids to assign
        roles_to_remove (set): Role ids to remove

        Reuturns
        ----------
        bool: True if successful, False otherwise
        """

        if not (guild := await discord_utils.get_discord_guild(self.bot, self.bot.guild_id)):
            self.bot.logger.warning("Failed to fetch guild. Can't convert role ids to objects. Roles not applied")
            return False

        roles_to_add = {await discord_utils.get_guild_role(self.bot, guild, role_id) for role_id in roles_to_add}
        roles_to_remove = {await discord_utils.get_guild_role(self.bot, guild, role_id) for role_id in roles_to_remove}

        # Filter out None values
        # This should probably be integrated into the above code
        roles_to_add = set(filter(None, roles_to_add))
        roles_to_remove = set(filter(None, roles_to_remove))

        try:
            await user.add_roles(*roles_to_add, reason="Membership check")
            await user.remove_roles(*roles_to_remove, reason="Membership check")
        except discord.Forbidden:
            self.bot.logger.error(f"Failed to assign roles to user {user.id}. Forbidden")
            return False
        except discord.HTTPException as e:
            self.bot.logger.error(f"Failed to assign roles to user {user.id}. {e}")
            return False

        self.bot.logger.info(f"Roles updated for user {user.id}. Gave {roles_to_add}. Removed {roles_to_remove}")

        return True

    @tasks.loop(time=misc_utils.MIDNIGHT)
    async def membership_check(self):
        """
        Checks all registered user's membership status and assigns roles based on the status
        """

        self.bot.logger.info("Checking membership status for all users")

        if not (guild := await discord_utils.get_discord_guild(self.bot, self.bot.guild_id)):
            self.bot.logger.error("Failed to fetch guild. Can't convert role ids to objects. Roles not applied")
            return

        # Fetch all galtinn users with a discord profile
        galtinn_users = await self.fetch_galtinn_users()
        if not galtinn_users:
            self.bot.logger.error("Failed to fetch Galtinn users or no users found. Aborting membership check...")
            return

        for galtinn_user in galtinn_users.results:
            self.bot.logger.info(
                f"Checking membership status for galtinn user {galtinn_user.id}."
                + f" Discord ID: {galtinn_user.discord_profile.discord_id}"
            )
            # Fetch Discord user
            if not (
                discord_user := await discord_utils.get_guild_member(
                    self.bot, guild, galtinn_user.discord_profile.discord_id
                )
            ):
                self.bot.logger.error(
                    f"Failed to fetch member with ID {galtinn_user.discord_profile.discord_id}. Not found"
                )
                continue

            roles_to_add, roles_to_remove = await self.get_user_galtinn_roles(galtinn_user)
            await self.update_roles(discord_user, roles_to_add, roles_to_remove)

            await asyncio.sleep(0.5)

        self.bot.logger.info("Membership check completed")

    @membership_check.before_loop
    async def before_membership_check(self):
        """
        Make sure bot is ready before starting the membership check loop
        """

        await self.bot.wait_until_ready()

    @tasks.loop(minutes=2)
    async def verification_cleanup(self):
        """
        Clean up any pending verifications that have expired. This is in case the register command fails to do so
        """

        results = await self.bot.db.fetch(
            """
            SELECT discord_id, expires
            FROM galtinn_verification;
            """
        )
        for result in results:
            discord_id, expires = list(result)
            if expires < datetime.utcnow():
                await self.bot.db.execute(
                    """
                    DELETE FROM galtinn_verification
                    WHERE discord_id = $1;
                    """,
                    discord_id,
                )

    @verification_cleanup.before_loop
    async def before_verification_cleanup(self):
        """
        Make sure bot is ready before starting the verification cleanup loop
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

        await interaction.response.defer(ephemeral=True)

        # Check if user is already registered
        discord_profile = await self.fetch_galtinn_discordprofiles(discord_id=interaction.user.id)
        # API guarantees that there is only one or zero results so this is safe
        if discord_profile.count == 1:
            embed = embed_templates.error_warning("Du er allerede registrert!")
            await interaction.followup.send(embed=embed)
            return

        # Check if user is already pending verification
        verification = await self.bot.db.fetchrow(
            """
            SELECT discord_id, challenge, state
            FROM galtinn_verification
            WHERE discord_id = $1;
            """,
            interaction.user.id,
        )
        if verification:
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
        await self.bot.db.execute(
            """
            INSERT INTO galtinn_verification
            VALUES ($1, $2, $3);
            """,
            interaction.user.id,
            challenge,
            state,
        )

        self.bot.logger.info(f"Generated challenge for user {interaction.user.id}")

        embed = discord.Embed(title="Koble Galtinnbrukeren din til Discord", color=discord.Color.orange())
        embed.description = (
            "Klikk på lenken under for å koble Galtinnbrukeren din til Discord\n\n"
            + f"{url}\n\nDu har 2 minutter på deg til å fullføre verifikasjonen."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        #  Remove verification after 2 minutes
        await asyncio.sleep(120)
        await self.bot.db.execute(
            """
            DELETE FROM galtinn_verification
            WHERE discord_id = $1;
            """,
            interaction.user.id,
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

        # TODO: add confirmation button
        # I could not get it to consistently work
        # because discord interactions are confusing as hell

        await interaction.response.defer(ephemeral=True)

        # Check if user exists
        galtinn_users = await self.fetch_galtinn_users(discord_id=interaction.user.id)
        # API guarantees that there is only one or zero results so this is safe
        if galtinn_users.count == 0:
            embed = embed_templates.error_warning("Du er ikke registrert!")
            await interaction.followup.send(embed=embed)
            return

        self.bot.logger.info(f"Deleting user {interaction.user.id}")

        galtinn_user = galtinn_users.results[0]

        roles_to_add, roles_to_remove = await self.get_user_galtinn_roles(galtinn_user)
        all_roles = roles_to_add.union(roles_to_remove)
        roles_changed = await self.update_roles(interaction.user, set(), all_roles)

        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.bot.galtinn['api_url']}/discordprofiles/{galtinn_user.id}/",
                headers={"Authorization": f"Token {self.bot.galtinn['auth_token']}"},
            ) as r:
                if r.status != 200 and r.status != 202 and r.status != 204:
                    self.bot.logger.error(f"Failed to delete discord profile. Status: {r.status}.")
                    embed = embed_templates.error_warning(
                        "Klarte ikke å slette tilkoblingen til Galtinnbrukeren din. Dette bør du rapportere til EDB!"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

        role_warning = (
            "\n\nVi klarte dessverre ikke å slette rollene dine derimot. Kontakt en serveradmin"
            if not roles_changed
            else ""
        )
        embed = embed_templates.success(f"Du har slettet tilkoblingen til Galtinnbrukeren din!{role_warning}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """
    Add the cog to the bot on extension load

    Parameters
    ----------
    bot (commands.Bot): Bot instance
    """

    cog = Galtinn(bot)
    await cog.init_db()
    await bot.add_cog(cog)
