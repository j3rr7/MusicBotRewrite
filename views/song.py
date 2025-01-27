import discord
from discord.ui import View, Button
from typing import List, Dict, Any, cast
from database import DatabaseManager


class SongSelect(discord.ui.Select):
    def __init__(self, database_instance, track_list: List[dict], playlist_name: str):
        self.database: DatabaseManager = database_instance
        self.track_list = track_list
        self.playlist_name = playlist_name
        options = [
            discord.SelectOption(
                label=track.get("title"),
                value=str(track.get("track_id")),
                # description=f"Track ID: {track.get("track_id")}",
            )
            for track in track_list
        ]
        super().__init__(
            placeholder="Select a song to remove...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_track_id = self.values[0]
        selected_track_name = ""
        for track in self.track_list:
            if str(track.get("track_id")) == str(selected_track_id):
                selected_track_name = track.get("title")
                break

        try:
            await self.database.track.delete(selected_track_id)
            await interaction.response.send_message(
                f"Removed song '{selected_track_name}' from playlist {self.playlist_name}.",
                ephemeral=True,
            )
            # Disable the select menu after selection (optional, but good UX)
            self.disabled = True
            await interaction.edit_original_response(view=self)

        except Exception as e:
            await interaction.response.send_message(
                f"Failed to remove track: {e}", ephemeral=True
            )


class SongListView(View):
    def __init__(
        self,
        database: DatabaseManager,
        songs: List[Dict[str, Any]],
        playlist_name: str,
        interaction: discord.Interaction,
    ):
        super().__init__(timeout=180)
        self.database = database
        self.songs = songs
        self.playlist_name = playlist_name
        self.interaction = interaction
        self.add_item(SongSelect(self.database, self.songs, self.playlist_name))

    async def on_timeout(self) -> None:
        # Disable components on timeout
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        if self.interaction:
            await self.interaction.response.edit_message(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != interaction.user:
            await interaction.response.send_message(
                "This select menu is not for you!", ephemeral=True
            )
            return False
        self.interaction = interaction
        return True
