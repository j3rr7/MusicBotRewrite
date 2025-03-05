import logging
import discord
from discord.ui import View, Button, Select, Item
from typing import List, Dict, Any, cast


class SongSelect(discord.ui.Select):
    def __init__(self, songs: List[dict]):
        options = [
            discord.SelectOption(
                label=f"{song.get("trackName", 'Unknown Track')} - {song.get('artistName', 'Unknown Artist')}",
                value=str(song.get("id", -1)),
            )
            for song in songs
        ]
        super().__init__(
            placeholder="Select a song...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.songs = songs

    async def callback(self, interaction: discord.Interaction):
        selected_track_id = self.values[0]

        if selected_track_id:
            selected_song = next(
                (
                    song
                    for song in self.songs[:25]
                    if str(song.get("id", -1)) == selected_track_id
                ),
                None,
            )

            if selected_song:
                lyrics = selected_song.get("plainLyrics", "")

                chunk_size = 2000
                chunks = [
                    lyrics[i : i + chunk_size]
                    for i in range(0, len(lyrics), chunk_size)
                ]

                for index, chunk in enumerate(chunks):
                    try:
                        await interaction.response.send_message(chunk, ephemeral=False)
                    except discord.errors.InteractionResponded:
                        await interaction.followup.send(chunk, ephemeral=False)
            else:
                try:
                    await interaction.response.send_message("Invalid song", ephemeral=False)
                except discord.errors.InteractionResponded:
                    await interaction.followup.send("Invalid song", ephemeral=False)
        else:
            try:
                await interaction.response.send_message("Invalid song", ephemeral=False)
            except discord.errors.InteractionResponded:
                await interaction.followup.send("Invalid song", ephemeral=False)


class LyricLookupView(View):
    def __init__(self, interaction: discord.Interaction, songs: List[dict]):
        super().__init__(timeout=180)
        self.logger = logging.getLogger(__name__)
        self.interaction = interaction
        self.add_item(SongSelect(songs))

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True
            elif isinstance(item, Select):
                item.disabled = True

        if self.interaction:
            await self.interaction.edit_original_response(view=self)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: Item
    ):
        self.logger.error(f"Error in {item}: {error}", exc_info=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != interaction.user:
            await interaction.response.send_message(
                "This select menu is not for you!", ephemeral=True
            )
            return False
        return True
