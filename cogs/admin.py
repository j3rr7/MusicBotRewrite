import logging
import discord
import pathlib
import traceback
import wavelink
from discord import app_commands
from discord.ext import commands
from importlib import import_module
from config import ADMIN_IDS
from typing import List


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

    @staticmethod
    def format_bytes(bytes: int) -> str:
        """
        Converts a byte size to a human-readable format.
        """
        bytes = int(bytes)
        if bytes <= 0:
            return "0 B"
        if bytes < 1024:
            return f"{bytes} B"
        if bytes < 1024 * 1024:
            return f"{bytes / 1024:.2f} KB"
        if bytes < 1024 * 1024 * 1024:
            return f"{bytes / (1024 * 1024):.2f} MB"
        return f"{bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def format_miliseconds(milliseconds: int) -> str:
        """
        Converts milliseconds (integer) to human readable format
        """
        if milliseconds < 0:
            raise ValueError("Milliseconds cannot be negative")

        if milliseconds == 0:
            return "0 milliseconds"

        units = [
            ("days", 1000 * 60 * 60 * 24),
            ("hours", 1000 * 60 * 60),
            ("minutes", 1000 * 60),
            ("seconds", 1000),
            ("milliseconds", 1),
        ]

        output_parts = []
        remaining_milliseconds = milliseconds

        for unit_name, unit_value in units:
            unit_count = remaining_milliseconds // unit_value
            if unit_count > 0:
                output_parts.append(f"{unit_count} {unit_name}")
                remaining_milliseconds %= unit_value

        return ", ".join(output_parts)

    @app_commands.command(name="sync", description="Syncs slash commands.")
    async def sync(self, interaction: discord.Interaction):
        await self.bot.tree.sync(guild=None)
        await interaction.response.send_message(
            "Slash commands synced.", ephemeral=True
        )

    @app_commands.command(name="lvstats", description="Shows Lavalink node stats")
    async def lvstats(self, interaction: discord.Interaction):
        """
        Displays statistics for all connected Lavalink nodes.
        """
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="Lavalink Node Stats",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        stats_description = ""
        player_details = ""

        try:
            if not wavelink.node.Pool.nodes:
                stats_description = "No Lavalink nodes connected."
            else:
                for node_name, node in wavelink.node.Pool.nodes.items():
                    self.logger.debug(f"Fetching stats for node: {node_name} ({node})")
                    try:
                        players: List[wavelink.PlayerResponsePayload] = (
                            await wavelink.Node.fetch_players(node)
                        )
                        stats: wavelink.StatsResponsePayload = (
                            await wavelink.Node.fetch_stats(node)
                        )

                        node_stats_str = (
                            f"**Node: {node_name}**\n"
                            f"Players: {len(players)}\n"
                            f"Uptime: {Admin.format_miliseconds(stats.uptime)}\n"
                            f"Memory: Used: {Admin.format_bytes(stats.memory.used)}, Reservable: {Admin.format_bytes(stats.memory.reservable)}, "
                            f"Allocated: {Admin.format_bytes(stats.memory.allocated)}, Free: {Admin.format_bytes(stats.memory.free)}\n"
                            f"CPU: Cores: {stats.cpu.cores}, Load: {stats.cpu.lavalink_load:.2f}%, System Load: {stats.cpu.system_load:.2f}%\n"
                        )
                        stats_description += node_stats_str + "\n"

                        if players:
                            player_details += (
                                f"\n**Player Details for Node: {node_name}**\n"
                            )
                            for player in players:
                                track_title = "None"
                                if player.track:
                                    track_title = player.track.title

                                player_info = (
                                    f"  Guild ID: {player.guild_id}\n"
                                    f"  Paused: {player.paused}\n"
                                    f"  State: Connected: {player.state.connected}, Ping: {player.state.ping}ms\n"
                                    f"  Track: {track_title}\n"
                                )
                                player_details += player_info

                    except Exception as node_err:
                        self.logger.error(
                            f"Error fetching stats for node {node_name}: {node_err}"
                        )
                        stats_description += f"\n**Error fetching stats for node {node_name}:** {node_err}\n"

            embed.description = stats_description
            if player_details:
                embed.add_field(
                    name="Player Details", value=player_details, inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.exception(f"Error during lvstats command:")
            await interaction.followup.send(
                f"An error occurred while fetching Lavalink stats.", ephemeral=True
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
            module = import_module(f"cogs.{cog}")
            await self.bot.reload_extension(module.__name__)
            await interaction.followup.send(f"Cog {cog} reloaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @reload.autocomplete(name="cog")
    async def reload_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=str(cog).lower())
            for cog in self.bot.cogs
            if cog.startswith(value)
        ]

    @app_commands.command(name="load", description="Loads a cog.")
    @app_commands.describe(cog="The cog to load.")
    async def load(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)
        try:
            module = import_module(f"cogs.{cog}")
            await self.bot.load_extension(module.__name__)
            await interaction.followup.send(f"Cog {cog} loaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @load.autocomplete(name="cog")
    async def load_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=str(cog).lower())
            for cog in self.bot.cogs
            if cog.startswith(value)
        ]

    @app_commands.command(name="unload", description="Unloads a cog.")
    @app_commands.describe(cog="The cog to unload.")
    async def unload(self, interaction: discord.Interaction, cog: str):
        await interaction.response.defer(ephemeral=True)

        try:
            module = import_module(f"cogs.{cog}")
            await self.bot.unload_extension(module.__name__)
            await interaction.followup.send(f"Cog {cog} unloaded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @unload.autocomplete(name="cog")
    async def unload_autocomplete(
        self, interaction: discord.Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cog, value=str(cog).lower())
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
