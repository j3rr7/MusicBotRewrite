import traceback
import logging
import discord
from discord import app_commands
from discord.ext import commands
from views.help import HelpView
from modals.issue import IssueModal


class General(commands.Cog):
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def cog_load(self):
        self.logger.info("General cog loaded")

    async def cog_unload(self):
        self.logger.info("General cog unloaded")

    @app_commands.command(name="ping", description="Ping the bot.")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Latency: " + str(round(self.bot.latency * 1000)) + "ms", ephemeral=True
        )

    @app_commands.command(name="help", description="Get help")
    async def help(self, interaction: discord.Interaction):
        view = HelpView()
        await interaction.response.send_message(embed=view.create_embed(), view=view)

    @discord.app_commands.command(name="issue", description="Report an issue")
    async def issue(self, interaction: discord.Interaction):
        if hasattr(self.bot, "database"):
            issue_modal = IssueModal(
                database=self.bot.database, title="Report an issue", timeout=120
            )
            await interaction.response.send_modal(issue_modal)
        else:
            await interaction.response.send_message(
                "Error: Database not found", ephemeral=True
            )

    async def cog_app_command_error(self, interaction, error):
        self.logger.error(traceback.format_exc())

        try:
            await interaction.response.send_message(
                "Error: " + str(error), ephemeral=True
            )
        except discord.errors.InteractionResponded:
            await interaction.followup.send("Error: " + str(error), ephemeral=True)


async def setup(bot):
    await bot.add_cog(General(bot))
