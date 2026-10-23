import asyncio
import base64
import hashlib
import secrets
import urllib.parse
from typing import TypeVar

import aiohttp
import asyncpg
import discord
from cogs.utils import discord_utils
from cogs.utils import embed_templates
from cogs.utils import misc_utils
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from models import BasicResponse
from models import DiscordProfiles
from models import DuskenUser
from models import Groups
from models import Users

ResponseModel = TypeVar("ResponseModel", bound=BasicResponse)


class Galtinn(commands.Cog):
    """Manage Galtinn membership and roles for users"""

    def __init__(self, bot: commands.Bot):
        """
        Parameters
        ----------
        bot (commands.Bot): The bot instance
        """

        self.bot = bot

        self.listen_conn: asyncpg.Connection | None = None
        self.listen_reconnect_task: asyncio.Task | None = None
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        # One session for all Galtinn requests, so connections are reused
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Token {self.bot.galtinn['auth_token']}"},
            timeout=aiohttp.ClientTimeout(total=10),
        )

        await self.init_db()
        await self.listen_db()

        self.membership_check.start()
        self.verification_cleanup.start()

    async def cog_unload(self):
        self.bot.logger.info("Unloading cog")
        self.membership_check.cancel()
        self.verification_cleanup.cancel()

        if self.listen_reconnect_task:
            self.listen_reconnect_task.cancel()

        # Closing the connection also removes its listeners.
        # It is detached first so the termination listener doesn't try to reconnect
        if self.listen_conn:
            conn, self.listen_conn = self.listen_conn, None
            await conn.close()

        if self.session:
            await self.session.close()

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
                expires TIMESTAMPTZ DEFAULT NOW() + INTERVAL '2 minutes'
            );
            """
        )

        # Tables created before expires was timezone aware stored naive UTC timestamps
        await self.bot.db.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'galtinn_verification'
                    AND column_name = 'expires'
                    AND data_type = 'timestamp without time zone'
                ) THEN
                    ALTER TABLE galtinn_verification
                        ALTER COLUMN expires TYPE TIMESTAMPTZ USING expires AT TIME ZONE 'utc',
                        ALTER COLUMN expires SET DEFAULT NOW() + INTERVAL '2 minutes';
                END IF;
            END $$;
            """
        )

    async def listen_db(self):
        """
        Opens a dedicated database connection that listens for galtinn_auth_complete events.
        It is kept outside the pool so it doesn't hold a pool connection for the lifetime of the cog
        """

        conn = await asyncpg.connect(**self.bot.db_credentials)
        try:
            await conn.add_listener("galtinn_auth_complete", self.process_notification)
        except BaseException:
            # Also covers the reconnect task being cancelled on cog unload
            await conn.close()
            raise

        conn.add_termination_listener(self.on_listen_conn_terminated)
        self.listen_conn = conn

    def on_listen_conn_terminated(self, conn: asyncpg.Connection):
        """
        Starts reconnecting the listener if its connection is lost, e.g. on a database restart
        """

        # Connections closed on cog unload are detached before closing
        if conn is not self.listen_conn:
            return

        self.bot.logger.warning("Lost database listener connection. Reconnecting...")
        self.listen_conn = None
        self.listen_reconnect_task = asyncio.create_task(self.reconnect_listener())

    async def reconnect_listener(self):
        """
        Retries the listener connection with exponential backoff until it succeeds
        """

        delay = 1
        while True:
            try:
                await self.listen_db()
            except Exception as e:
                self.bot.logger.error(f"Failed to reconnect database listener. Retrying in {delay}s. {e!r}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                self.bot.logger.info("Database listener reconnected")
                self.listen_reconnect_task = None
                return

    async def process_notification(self, conn: asyncpg.Connection, pid: int, channel: str, payload: str):
        """
        Applies Galtinn roles to a user that has just completed verification
        """

        self.bot.logger.info("Received galtinn_auth_complete event from database")

        try:
            discord_user_id, galtinn_user_id = payload.split(" ", 1)
            discord_user_id = int(discord_user_id)
            galtinn_user_id = int(galtinn_user_id)
        except (TypeError, ValueError):
            self.bot.logger.error(f"Invalid galtinn_auth_complete payload: {payload!r}")
            return

        # asyncpg runs the callback as a detached task, so exceptions would otherwise go unnoticed
        try:
            # Fetch Galtinn user
            if not (
                galtinn_users := await self.fetch_galtinn_users(
                    galtinn_user_id=galtinn_user_id, discord_id=discord_user_id
                )
            ):
                self.bot.logger.error(
                    f"Failed to fetch Galtinn user {galtinn_user_id} for Discord user {discord_user_id}"
                )
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
            if not await self.update_roles(discord_user, roles_to_add, roles_to_remove):
                self.bot.logger.error(f"Failed to apply some or all Galtinn roles for user {discord_user_id}")
                return
        except Exception:
            self.bot.logger.exception(f"Failed to process galtinn_auth_complete event for user {discord_user_id}")
            return

        self.bot.logger.info(f"Completed processing {discord_user_id}!")

    async def fetch_paginated(self, endpoint: str, params: dict, model: type[ResponseModel]) -> ResponseModel | None:
        """
        Fetches every page of a paginated Galtinn endpoint and merges the results into the first page

        Parameters
        ----------
        endpoint (str): API endpoint, e.g. "users"
        params (dict): Query parameters
        model (type[BasicResponse]): Model each page is parsed into

        Returns
        ----------
        (BasicResponse | None): All results. None if the first page could not be fetched.
            If a later page fails, the results fetched so far are returned
        """

        url = f"{self.bot.galtinn['api_url']}/{endpoint}/?{urllib.parse.urlencode(params | {'format': 'json'})}"
        result = None
        while url:
            async with self.session.get(url) as r:
                if r.status != 200:
                    self.bot.logger.warning(f"Failed to fetch {url} from Galtinn. Status: {r.status}")
                    return result
                page = model(**await r.json())

            if result is None:
                result = page
            else:
                result.results.extend(page.results)
            url = page.next

        return result

    async def fetch_galtinn_users(
        self, galtinn_user_id: int | None = None, discord_id: int | None = None
    ) -> Users | None:
        """
        Attempts to fetch user(s) from Galtinn. If no parameters are given, all users are fetched
        """

        params = {"no_discord_id": False}
        if discord_id:
            params["discord_profile__discord_id"] = discord_id
        if galtinn_user_id:
            params["id"] = galtinn_user_id

        return await self.fetch_paginated("users", params, Users)

    async def fetch_galtinn_discordprofiles(
        self, galtinn_user_id: int | None = None, discord_id: int | None = None
    ) -> DiscordProfiles | None:
        """
        Attempts to fetch discord profile(s) from Galtinn. If no parameters are given, all profiles are fetched
        """

        params = {}
        if discord_id:
            params["discord_id"] = discord_id
        if galtinn_user_id:
            params["user"] = galtinn_user_id

        return await self.fetch_paginated("discordprofiles", params, DiscordProfiles)

    async def fetch_galtinn_groups(self) -> Groups | None:
        """
        Attempts to fetch all groups with associated Discord roles from Galtinn
        """

        return await self.fetch_paginated("groups", {"no_discord_roles": False}, Groups)

    async def fetch_all_galtinn_roles(self) -> set[int]:
        """
        Fetch all roles connected to Galtinn groups

        Returns
        ----------
        set(int): Set of role ids
        """

        all_roles = {self.bot.galtinn_roles["volunteer"], self.bot.galtinn_roles["member"]}

        if not (groups := await self.fetch_galtinn_groups()):
            return all_roles

        for group in groups.results:
            role_ids = [role.discord_id for role in group.profile.discord_roles] if group.profile else []
            self.bot.logger.info(f"Galtinn group {group.id} ({group.name}) roles: {role_ids}")
            all_roles.update(role_ids)

        return all_roles

    async def get_user_galtinn_roles(
        self, galtinn_user: DuskenUser, all_roles: set[int] | None = None
    ) -> tuple[set, set]:
        """
        Get which roles to add and which to remove based on the user's Galtinn membership status

        Parameters
        ----------
        galtinn_user (DuskenUser): Galtinn user object
        all_roles (set[int] | None): All roles connected to Galtinn, as returned by fetch_all_galtinn_roles.
            Fetched if not given. Pass it in when checking many users to avoid fetching it for every user

        Reuturns
        ----------
        tuple[set[int], set[int]]: Role ids to add, role ids to remove
        """

        if all_roles is None:
            all_roles = await self.fetch_all_galtinn_roles()

        roles_to_add = set()

        if galtinn_user.is_volunteer:
            roles_to_add.add(self.bot.galtinn_roles["volunteer"])
        if galtinn_user.is_member:
            roles_to_add.add(self.bot.galtinn_roles["member"])

        if not galtinn_user.groups:
            roles_to_remove = all_roles - roles_to_add
            return roles_to_add, roles_to_remove

        for group in galtinn_user.groups:
            if group.profile:
                roles_to_add.update(discord_role.discord_id for discord_role in group.profile.discord_roles)

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
        bool: True if all roles were updated, False if any role could not be updated
        """

        if not (guild := await discord_utils.get_discord_guild(self.bot, self.bot.guild_id)):
            self.bot.logger.warning("Failed to fetch guild. Can't convert role ids to objects. Roles not applied")
            return False

        requested_roles_to_add = roles_to_add
        requested_roles_to_remove = roles_to_remove
        guild_roles = await discord_utils.get_guild_roles(
            self.bot, guild, requested_roles_to_add | requested_roles_to_remove
        )
        roles_to_add = {guild_roles[role_id] for role_id in requested_roles_to_add if role_id in guild_roles}
        roles_to_remove = {guild_roles[role_id] for role_id in requested_roles_to_remove if role_id in guild_roles}

        # Problematic roles are skipped rather than aborting, so that one misconfigured role
        # doesn't stop every other role from being updated
        success = True

        # Roles that don't exist on the server can't be held by the user, so only missing roles to add are a problem
        if missing_roles_to_add := requested_roles_to_add - {role.id for role in roles_to_add}:
            self.bot.logger.error(f"Could not resolve Discord roles to add for user {user.id}: {missing_roles_to_add}")
            success = False

        # Only touch roles that actually change. Discord needs one API call per role added or removed
        current_roles = set(user.roles)
        roles_to_add -= current_roles
        roles_to_remove &= current_roles

        if not roles_to_add and not roles_to_remove:
            return success

        if unassignable_roles := {role for role in roles_to_add | roles_to_remove if not role.is_assignable()}:
            self.bot.logger.error(
                f"Discord bot cannot manage roles for user {user.id}: {[role.id for role in unassignable_roles]}. "
                "Check Manage Roles permission and role hierarchy"
            )
            roles_to_add -= unassignable_roles
            roles_to_remove -= unassignable_roles
            success = False

        self.bot.logger.info(f"Updating roles for user {user.id}. Adding {roles_to_add}. Removing {roles_to_remove}")

        try:
            await user.add_roles(*roles_to_add, reason="Membership check")
            await user.remove_roles(*roles_to_remove, reason="Membership check")
        except discord.Forbidden:
            self.bot.logger.error(f"Failed to assign roles to user {user.id}. Forbidden")
            return False
        except discord.HTTPException as e:
            self.bot.logger.error(f"Failed to assign roles to user {user.id}. {e}")
            return False

        self.bot.logger.info(f"Roles updated for user {user.id}!")

        return success

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

        all_roles = await self.fetch_all_galtinn_roles()

        for galtinn_user in galtinn_users.results:
            if not galtinn_user.discord_profile:
                self.bot.logger.warning(f"Galtinn user {galtinn_user.id} has no Discord profile. Skipping")
                continue

            self.bot.logger.info(
                f"Checking membership status for galtinn user {galtinn_user.id}."
                + f" Discord ID: {galtinn_user.discord_profile.discord_id}"
            )

            # An unhandled exception would stop the task loop until the bot is restarted,
            # so one bad user must not be allowed to stop the check for everyone else
            try:
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

                roles_to_add, roles_to_remove = await self.get_user_galtinn_roles(galtinn_user, all_roles)
                await self.update_roles(discord_user, roles_to_add, roles_to_remove)
            except Exception:
                self.bot.logger.exception(f"Failed to check membership status for galtinn user {galtinn_user.id}")

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
        Clean up any pending verifications that have expired
        """

        await self.bot.db.execute(
            """
            DELETE FROM galtinn_verification
            WHERE expires < NOW();
            """
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
        if discord_profile is None:
            embed = embed_templates.error_fatal("Klarte ikke å hente data fra Galtinn. Prøv igjen senere!")
            await interaction.followup.send(embed=embed)
            return
        # API guarantees that there is only one or zero results so this is safe
        if discord_profile.count == 1:
            embed = embed_templates.error_warning("Du er allerede registrert!")
            await interaction.followup.send(embed=embed)
            return

        # PKCE (S256). Only the hashed challenge is sent to Galtinn. The verifier is kept in the database
        # (in the challenge column) for the verification server to complete the token exchange with
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(32)

        # Insert into verfications table, unless the user already has a pending verification.
        # Expired verifications that haven't been cleaned up yet are replaced
        inserted = await self.bot.db.fetchval(
            """
            INSERT INTO galtinn_verification (discord_id, challenge, state)
            VALUES ($1, $2, $3)
            ON CONFLICT (discord_id) DO UPDATE
            SET challenge = EXCLUDED.challenge, state = EXCLUDED.state, expires = DEFAULT
            WHERE galtinn_verification.expires <= NOW()
            RETURNING TRUE;
            """,
            interaction.user.id,
            verifier,
            state,
        )
        if not inserted:
            embed = embed_templates.error_warning("Du har allerede en pågående verifikasjon!")
            await interaction.followup.send(embed=embed)
            return

        # Generate OAuth2 URL
        base_url = f"{self.bot.galtinn['api_url']}/oauth/authorize/"
        params = {
            "client_id": self.bot.galtinn["client_id"],
            "scope": "openid profile email",
            "response_type": "code",
            "redirect_uri": self.bot.galtinn["redirect_uri"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        self.bot.logger.info(f"Generated challenge for user {interaction.user.id}")

        embed = discord.Embed(title="Koble Galtinnbrukeren din til Discord", color=discord.Color.orange())
        embed.description = (
            "Klikk på lenken under for å koble Galtinnbrukeren din til Discord\n\n"
            + f"{url}\n\nDu har 2 minutter på deg til å fullføre verifikasjonen."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

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
        if galtinn_users is None:
            embed = embed_templates.error_fatal("Klarte ikke å hente data fra Galtinn. Prøv igjen senere!")
            await interaction.followup.send(embed=embed)
            return
        # API guarantees that there is only one or zero results so this is safe
        if galtinn_users.count == 0:
            embed = embed_templates.error_warning("Du er ikke registrert!")
            await interaction.followup.send(embed=embed)
            return

        self.bot.logger.info(f"Deleting user {interaction.user.id}")

        galtinn_user = galtinn_users.results[0]

        # Remove the link before the roles, so a failed deletion doesn't leave the user linked but without roles
        async with self.session.delete(f"{self.bot.galtinn['api_url']}/discordprofiles/{galtinn_user.id}/") as r:
            if r.status != 200 and r.status != 202 and r.status != 204:
                self.bot.logger.error(f"Failed to delete discord profile. Status: {r.status}.")
                embed = embed_templates.error_warning(
                    "Klarte ikke å slette tilkoblingen til Galtinnbrukeren din. Dette bør du rapportere til EDB!"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # The command can be used in DMs, where interaction.user is not a guild member and has no roles
        roles_changed = False
        if not (guild := await discord_utils.get_discord_guild(self.bot, self.bot.guild_id)):
            self.bot.logger.error("Failed to fetch guild. Roles not removed")
        elif not (member := await discord_utils.get_guild_member(self.bot, guild, interaction.user.id)):
            self.bot.logger.error(f"Failed to fetch member with ID {interaction.user.id}. Roles not removed")
        else:
            roles_changed = await self.update_roles(member, set(), await self.fetch_all_galtinn_roles())

        role_warning = (
            "\n\nVi klarte dessverre ikke å slette rollene dine derimot. Kontakt en serveradmin"
            if not roles_changed
            else ""
        )
        embed = embed_templates.success(f"Du har slettet tilkoblingen til Galtinnbrukeren din!{role_warning}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.checks.bot_has_permissions(embed_links=True)
    @app_commands.checks.cooldown(1, 5)
    @galtinn_group.command(name="roller", description="Vis alle roller som er koblet til en gruppe i Galtinn")
    async def roles(self, interaction: discord.Interaction):
        """
        List all Discord roles that are connected to a Galtinn group

        Parameters
        ----------
        interaction (discord.Interaction): Slash command context object
        """

        # Discord ignores guild_only on subcommands, and the rest of the group has to work in DMs
        if not interaction.guild:
            embed = embed_templates.error_warning("Denne kommandoen kan bare brukes i en server")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        groups = await self.fetch_galtinn_groups()
        if groups is None:
            embed = embed_templates.error_fatal("Klarte ikke å hente grupper fra Galtinn")
            await interaction.followup.send(embed=embed)
            return

        # The API may return the same group more than once, so group names are collected in a set
        role_groups: dict[int, set[str]] = {}
        for group in groups.results:
            if not group.profile:
                continue
            for discord_role in group.profile.discord_roles:
                role_groups.setdefault(discord_role.discord_id, set()).add(group.name)

        if not role_groups:
            embed = embed_templates.error_warning("Ingen roller er koblet til grupper i Galtinn")
            await interaction.followup.send(embed=embed)
            return

        found_roles = []
        missing_roles = []
        for role_id, group_names in role_groups.items():
            groups_text = ", ".join(sorted(group_names))
            if role := interaction.guild.get_role(role_id):
                found_roles.append((role.name.lower(), f"{role.mention} - {groups_text}"))
            else:
                missing_roles.append(f"`{role_id}` (finnes ikke på serveren) - {groups_text}")

        # Sort by role name, with roles missing from the server at the end
        roles_formatted = [text for _, text in sorted(found_roles)] + missing_roles

        paginator = misc_utils.Paginator(roles_formatted)
        view = discord_utils.Scroller(paginator, interaction.user)

        embed = view.construct_embed(
            discord.Embed(
                color=interaction.guild.me.color, title=f"Roller koblet til Galtinngrupper ({len(roles_formatted)})"
            )
        )
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    """
    Add the cog to the bot on extension load

    Parameters
    ----------
    bot (commands.Bot): Bot instance
    """

    await bot.add_cog(Galtinn(bot))
