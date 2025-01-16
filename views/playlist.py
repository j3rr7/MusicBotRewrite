import math
import traceback
import wavelink
import discord
import logging
from discord.ui import View
from typing import List, Any, Dict


class PlaylistListView(View):
    def __init__(self, playlists: List[tuple]):
        super().__init__(timeout=180)
        self.playlists = playlists
        self.current_page = 0
        self.playlist_per_page = 10

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="⬅️")
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.create_embed())

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        max_pages = math.ceil(len(self.playlists) / self.playlist_per_page)
        self.current_page = min(self.current_page + 1, max_pages - 1)
        await interaction.response.edit_message(embed=self.create_embed())

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"Playlists Saved: {len(self.playlists)}", color=discord.Color.blue()
        )

        start_idx = self.current_page * self.playlist_per_page
        end_idx = start_idx + self.playlist_per_page

        playlist_text = ""
        for idx, playlist in enumerate(self.playlists[start_idx:end_idx], start=1):
            playlist_text += f"{idx}. {playlist[2]}\n"

        embed.description = playlist_text

        max_pages = math.ceil(len(self.playlists) / self.playlist_per_page)
        embed.set_footer(text=f"Page {self.current_page + 1}/{max_pages}")

        return embed


class PlaylistTrackView(View):
    def __init__(self, tracks: List[Any]):
        super().__init__(timeout=180)
        self.tracks = list(tracks)

        self.current_page = 0
        self.tracks_per_page = 10
        self.page_count = math.ceil(len(self.tracks) / self.tracks_per_page)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="⬅️")
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.create_embed())

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page = min(self.current_page + 1, self.page_count - 1)
        await interaction.response.edit_message(embed=self.create_embed())

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"Playlist Tracks: {len(self.tracks)}", color=discord.Color.blue()
        )

        start_idx = self.current_page * self.tracks_per_page
        end_idx = min(start_idx + self.tracks_per_page, len(self.tracks))

        track_list = []
        for idx, track in enumerate(
            self.tracks[start_idx:end_idx], start=start_idx + 1
        ):
            # Format track information
            track_line = (
                f"{idx}. {track[3]}\n"
                # f"    └ Duration: {track.duration_str} | Added: <t:{int(track.added_at.timestamp())}:R>"
            )
            track_list.append(track_line)

        tracks_text = "\n".join(track_list)
        embed.description = f"```\n{tracks_text}\n```"

        embed.set_footer(text=f"Page {self.current_page + 1}/{self.page_count}")

        return embed
