import math
import discord
from discord.ui import View
from typing import List, Any


class PaginatedView(View):
    """
    Base class for creating paginated views in Discord.

    Attributes:
        items_per_page: Number of items to display per page.
        current_page: Current page number (0-indexed).
        item_list: List of items to paginate.
        page_count: Total number of pages.
    """

    def __init__(
        self, item_list: List[Any], items_per_page: int = 10, timeout: int = 180
    ):
        super().__init__(timeout=timeout)
        self.items_per_page = items_per_page
        self.current_page = 0
        self.item_list = item_list
        self.page_count = (
            math.ceil(len(self.item_list) / self.items_per_page)
            if self.item_list
            else 1
        )

        # Disable buttons if only one page or no pages
        if self.page_count <= 1:
            self.previous_button.disabled = True
            self.next_button.disabled = True

    async def update_buttons(self, interaction: discord.Interaction):
        """
        Updates the state of the previous and next buttons based on the current page.
        """
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.page_count - 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="⬅️")
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Button to navigate to the previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_buttons(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Button to navigate to the next page."""
        if self.current_page < self.page_count - 1:
            self.current_page += 1
            await self.update_buttons(interaction)

    def get_current_page_items(self) -> List[Any]:
        """
        Returns the items to be displayed on the current page.
        """
        start_index = self.current_page * self.items_per_page
        end_index = min(start_index + self.items_per_page, len(self.item_list))
        return self.item_list[start_index:end_index]

    def create_embed(self) -> discord.Embed:
        """
        Abstract method to create the embed for the current page.
        Subclasses should implement this method to define the embed content.
        """
        raise NotImplementedError("Subclasses must implement create_embed method.")
