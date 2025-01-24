import logging
import traceback
import discord
from config import DISCORD_TOKEN, DISCORD_TOKEN_DEV, DEBUG_GUILD_ID
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
        self.debug_mode = False
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
        if self.debug_mode:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name="⚠️Maintenance⚠️ MODE | /issues | /help",
                ),
                status=discord.Status.dnd,
            )
        else:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name="BETA v1.0.1 | /issues | /help",
                ),
                status=discord.Status.online,
            )

    async def setup_hook(self):
        for file in self.cog_extensions:
            await self.load_extension(".".join(file.with_suffix("").parts))

        if self.debug_mode:
            guild = discord.Object(id=DEBUG_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} global commands")


if __name__ == "__main__":
    bot = MusicBot(
        command_prefix="!",
        intents=discord.Intents.all(),
        help_command=None,
        description="Listen to your heartbeat",
    )
    bot.run(
        DISCORD_TOKEN_DEV if bot.debug_mode else DISCORD_TOKEN,
        log_handler=log_handler,
        log_formatter=formatter,
        log_level=logging.INFO,
        root_logger=True,
    )
