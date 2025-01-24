import traceback
import discord
from discord import ui
from database import DatabaseManager

class EvalModal(ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = None

    code = ui.TextInput(label="Enter code to evaluate", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            code = self.code.value

            eval(code)

            await interaction.followup.send(
                "Code has been evaluated successfully.",
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