import traceback
import discord
import logging
from discord import ui
from database import DatabaseManager


class IssueModal(ui.Modal):
    def __init__(self, database: DatabaseManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = database
        self.logger = logging.getLogger(__name__)

    issue = ui.TextInput(label="Describe Your Issue", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.database.insert(
                "issues", [{"user_id": interaction.user.id, "issue": self.issue.value}]
            )

            await interaction.followup.send(
                "Your issue has been submitted. Thank you for your help!",
                ephemeral=True,
            )
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            message = (
                f"An error occurred while processing the interaction:\n```py\n{tb}\n```"
            )
            await interaction.followup.send(message, ephemeral=True)
        finally:
            self.stop()

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
