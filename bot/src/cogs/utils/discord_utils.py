import os

import discord

from .misc_utils import Paginator


async def send_as_txt_file(interaction: discord.Interaction, content: str, file_path: str):
    """
    Sends a string as a txt file and deletes the file afterwards

    Parameters
    ----------
    interaction (discord.Interaction): Slash command context object
    content (str): String that's too long to send
    file_path (str): Path to file
    """

    # Create file
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

    # Send file
    txt_file = discord.File(file_path)
    await interaction.response.send_message(file=txt_file)

    # Delete file
    try:
        os.remove(file_path)
    except (FileNotFoundError, OSError, PermissionError):
        pass


class ScrollerButton(discord.ui.Button):
    """Button that scrolls through pages in a scroller view"""

    def __init__(
        self,
        paginator: Paginator,
        button_action: callable,
        content_constructor: callable,
        owner: discord.User | discord.Member,
        label: str,
        disabled: bool = False,
    ):
        """
        Parameters
        -----------
        paginator (Paginator): The paginator object that contains the data to be paginated
        button_action (callable): The function that returns the requested page
        content_constructor (callable): A function that takes a paginator object and a page number and returns an embed
        owner (discord.User|discord.Member): The user that invoked the paginator. Only this user can use the button
        """

        super().__init__(label=label, disabled=disabled)
        self.paginator = paginator
        self.button_action = button_action
        self.content_constructor = content_constructor
        self.owner = owner

    async def callback(self, interaction: discord.Interaction):
        """
        What to do when the button is pressed

        Parameters
        -----------
        interaction (discord.Interaction): Slash command context object
        """

        if interaction.user.id != self.owner.id:
            return await interaction.response.send_message(
                "Bare den som skrev kommandoen kan bruke denne knappen", ephemeral=True
            )

        await interaction.response.defer()

        content = self.content_constructor(self.button_action(), interaction.message.embeds[0])
        await interaction.message.edit(
            embed=content, view=Scroller(self.paginator, self.owner, self.content_constructor)
        )


class Scroller(discord.ui.View):
    """View that allows scrolling through pages of data using the pagination module"""

    def __init__(
        self, paginatior: Paginator, owner: discord.User | discord.Member, content_constructor: callable = None
    ):
        """
        Parameters
        -----------
        paginator (Paginator): The paginator object that contains the data to be paginated
        owner (discord.User|discord.Member): The user that invoked the paginator. Only this user can use the buttons
        content_constructor (callable): A function that takes a paginator object and a page number and returns an embed
        """

        super().__init__()
        self.paginator = paginatior
        self.content_constructor = content_constructor if content_constructor else self.__default_content_constructor

        self.add_item(
            ScrollerButton(
                self.paginator,
                self.paginator.first_page,
                self.content_constructor,
                owner,
                label="<<",
                disabled=self.paginator.current_page == 1,
            )
        )
        self.add_item(
            ScrollerButton(
                self.paginator,
                self.paginator.previous_page,
                self.content_constructor,
                owner,
                label="<",
                disabled=self.paginator.current_page == 1,
            )
        )
        self.add_item(
            ScrollerButton(
                self.paginator,
                self.paginator.next_page,
                self.content_constructor,
                owner,
                label=">",
                disabled=self.paginator.current_page == self.paginator.total_page_count,
            )
        )
        self.add_item(
            ScrollerButton(
                self.paginator,
                self.paginator.last_page,
                self.content_constructor,
                owner,
                label=">>",
                disabled=self.paginator.current_page == self.paginator.total_page_count,
            )
        )

    def construct_embed(self, base_embed: discord.Embed):
        """
        Constructs the embed to be displayed

        Parameters
        -----------
        base_embed (discord.Embed): The base embed to add fields to
        """

        return self.content_constructor(self.paginator.get_current_page(), embed=base_embed)

    def __default_content_constructor(self, page: list, embed: discord.Embed) -> discord.Embed:
        """
        Default embed template for the paginator

        Parameters
        ----------
        paginator (Paginator): Paginator dataclass
        page (list): List of streaks to display on a page
        embed (discord.Embed): Embed to add fields to
        """

        embed.description = "\n".join(page)
        embed.set_footer(text=f"Side {self.paginator.current_page}/{self.paginator.total_page_count}")
        return embed
