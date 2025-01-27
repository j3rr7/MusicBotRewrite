import discord
import logging
import traceback
from discord import ui
from database import DatabaseManager  # Assuming DatabaseManager is needed in base


class BaseModal(ui.Modal):
    def __init__(self, database: DatabaseManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = database
        self.logger = logging.getLogger(__name__)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        self.logger.error(traceback.format_exc())
        tb = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        message = (
            f"An error occurred while processing the interaction:\n```py\n{tb}\n```"
        )
        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.InteractionResponded:
            await interaction.edit_original_response(content=message, view=None)
        finally:
            self.stop()

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.process_submission(interaction)
        except Exception as e:
            await self.on_error(interaction, e)
        finally:
            self.stop()

    async def process_submission(self, interaction: discord.Interaction):
        """Abstract method to be implemented by subclasses to handle specific submission logic."""
        raise NotImplementedError("Subclasses must implement process_submission method")
