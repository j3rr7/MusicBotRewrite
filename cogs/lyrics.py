import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands

import json
import aiohttp
import wavelink
from typing import Optional
from views.lyric import LyricLookupView


class LyricAPI(commands.Cog):
    BASE_URL = "https://lrclib.net/api/get"
    BASE_FUZZY_URL = "https://lrclib.net/api/search"

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def fetch_lyrics(self, track_name: str, artist_name: str) -> Optional[dict]:
        """Fetch lyrics for a given track and artist."""
        params = {"track_name": track_name, "artist_name": artist_name}
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get(self.BASE_URL, params=params)
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            self.logger.error(f"Failed to fetch lyrics: {e}")
            return None
    
    async def search_lyrics(self, query: str) -> Optional[dict]:
        """Search for lyrics using a fuzzy search query."""
        params = {"q": query}
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get(self.BASE_FUZZY_URL, params=params)
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            self.logger.error(f"Failed to search lyrics: {e}")
            return None

    @app_commands.command(name="lyrics", description="Get lyrics for a song.")
    @app_commands.describe(query="title or part of lyrics, if not provided, use the current song")
    async def lyrics(self, interaction: discord.Interaction, query: str = None):
        await interaction.response.defer()

        if not query:
            player: wavelink.Player = interaction.guild.voice_client

            if not player or not player.current:
                embed = discord.Embed(
                    title="There is no music playing or player not connected",
                    color=discord.Colour.red(),
                )
                await interaction.followup.send(
                    embed=embed, ephemeral=True
                )
                return

            query = player.current.title

        result = await self.search_lyrics(query)

        if result is None or not result:
            embed = discord.Embed(
                title="No lyrics found",
                color=discord.Colour.red(),
            )
            await interaction.followup.send(
                embed=embed, ephemeral=True
            )
            return
        
        lyricView = LyricLookupView(interaction, result)

        await interaction.followup.send(view=lyricView)


async def setup(bot):
    await bot.add_cog(LyricAPI(bot))
