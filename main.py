import logging
import traceback
import discord
from config import DISCORD_TOKEN, DEBUG_GUILD_ID
from database import DatabaseManager
from pathlib import Path
from discord.ext import commands, tasks
from logging.handlers import RotatingFileHandler
from typing import Union

log_handler = RotatingFileHandler(
    "discord.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8", mode="w"
)  # 5Mb, 5 backups
formatter = logging.Formatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"
)
log_handler.setFormatter(formatter)
logger = logging.getLogger(__name__)


class MusicBot(commands.AutoShardedBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = DatabaseManager("database.db")
        self.cog_extensions: list[Path] = [
            file for file in Path("cogs").rglob("*.py") if not file.stem.startswith("_")
        ]

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")

        # get all guilds from bot and insert to database
        for guild in self.guilds:
            await self.database.insert("guilds", [{"id": guild.id}], "ignore")

        # setup activity
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="with more bugs"
            ),
            status=discord.Status.online,
        )

    async def setup_hook(self):
        for file in self.cog_extensions:
            await self.load_extension(".".join(file.with_suffix("").parts))

        guild = discord.Object(id=DEBUG_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(f"Synced {len(synced)} global commands")

    @discord.app_commands.command(name="help", description="Get help")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message("Help")


if __name__ == "__main__":
    bot = MusicBot(
        command_prefix="!",
        intents=discord.Intents.all(),
        help_command=None,
        description="Listen to your heartbeat",
    )
    bot.run(
        DISCORD_TOKEN,
        log_handler=log_handler,
        log_formatter=formatter,
        log_level=logging.INFO,
        root_logger=True,
    )
