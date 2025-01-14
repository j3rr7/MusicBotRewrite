import logging
import discord
import pathlib
import traceback
from discord import app_commands
from discord.ext import commands
from config import ADMIN_IDS


class Admin(commands.Cog):
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def cog_load(self):
        self.logger.info("Admin cog loaded")

    async def cog_unload(self):
        self.logger.info("Admin cog unloaded")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id in ADMIN_IDS

    @app_commands.command(name="sync", description="Syncs slash commands.")
    async def sync(self, interaction: discord.Interaction):
        await self.bot.tree.sync(guild=None)
        await interaction.response.send_message(
            "Slash commands synced.", ephemeral=True
        )

    @app_commands.command(
        name="prune", description="Deletes a number of messages. (max 100)"
    )
    @app_commands.describe(amount="The amount of messages to delete.")
    async def prune(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100] = 1,
    ):
        await interaction.response.defer(ephemeral=True)

        amount = min(amount, 100)
        deleted_messages = await interaction.channel.purge(
            limit=amount, check=lambda m: m.author == self.bot.user
        )

        await interaction.followup.send(
            f"Deleted {len(deleted_messages)} messages.", ephemeral=True
        )

    @app_commands.command(name="reload", description="Reloads a cog.")
    @app_commands.describe(cog="The cog to reload.")
    async def reload(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.reload_extension(f"{cog}")
            await interaction.followup.send(f"Cog {cog} reloaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @reload.autocomplete(name="cog")
    async def reload_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=cog)
            for cog in self.bot.cogs
            if cog.startswith(value)
        ]

    @app_commands.command(name="load", description="Loads a cog.")
    @app_commands.describe(cog="The cog to load.")
    async def load(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.load_extension(f"{cog}")
            await interaction.followup.send(f"Cog {cog} loaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @load.autocomplete(name="cog")
    async def load_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=cog)
            for cog in self.bot.cogs
            if cog.startswith(value)
        ]

    @app_commands.command(name="unload", description="Unloads a cog.")
    @app_commands.describe(cog="The cog to unload.")
    async def unload(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.bot.unload_extension(f"{cog}")
            await interaction.followup.send(f"Cog {cog} unloaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @unload.autocomplete(name="cog")
    async def unload_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=cog)
            for cog in self.bot.cogs
            if cog.startswith(value)
        ]

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction[discord.Client],
        error: app_commands.AppCommandError,
    ) -> None:
        self.logger.error(traceback.format_exc())

        if isinstance(error, app_commands.CommandOnCooldown):
            message = (
                f"Command is on cooldown. Try again in {error.retry_after:.2f} seconds."
            )
        elif isinstance(error, app_commands.CommandNotFound):
            message = "Command not found."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You are missing the required permissions to use this command."
        elif isinstance(error, app_commands.CommandInvokeError):
            message = "An error occurred while invoking the command."
        else:
            message = f"Error: {error}"

        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
