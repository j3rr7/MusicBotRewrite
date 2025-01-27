from views import PaginatedView

import discord
from typing import List, Dict, Any, cast


class PlaylistListView(PaginatedView):
    """
    View for displaying a paginated list of playlists.
    """

    def __init__(self, playlists: List[Dict[str, Any]]):
        super().__init__(playlists)
        self.playlist = playlists

    def create_embed(self) -> discord.Embed:
        """
        Creates the embed displaying the current page of playlists.
        """
        embed = discord.Embed(
            title=f"🎧 Playlists (`{len(self.item_list)}` Total)",
            color=discord.Color.dark_purple(),
        )

        if not self.item_list:
            embed.description = "😔 No playlists found."
        else:
            playlist_text_lines = []
            for idx, playlist in enumerate(
                self.get_current_page_items(),
                start=self.current_page * self.items_per_page + 1,
            ):
                playlist = cast(Dict[str, Any], playlist)
                playlist_name = playlist.get("name", "Unnamed Playlist")
                playlist_desc = playlist.get("description")

                line = f"**{idx}. {playlist_name}**"

                if playlist_desc:
                    line += f" 🎶 - {playlist_desc}"

                playlist_text_lines.append(line)

            embed.description = "\n".join(playlist_text_lines)
            embed.set_footer(
                text=f"Page {self.current_page + 1}/{self.page_count} of Playlists"
            )

        return embed


class PlaylistTrackView(PaginatedView):
    """
    View for displaying a paginated list of playlist tracks.
    """

    def __init__(self, tracks: List[Dict[str, Any]], playlist_name: str):
        super().__init__(tracks)
        self.tracks = tracks
        self.playlist_name = playlist_name

    def create_embed(self) -> discord.Embed:
        """
        Creates the embed displaying the current page of playlist tracks.
        """
        embed = discord.Embed(
            title=f"Playlist `{self.playlist_name}`, Songs: `{len(self.item_list)}`",
            color=discord.Color.blue(),
        )

        if not self.item_list:
            embed.description = "No song in this playlist."
        else:
            track_lines = []
            for idx, track in enumerate(
                self.get_current_page_items(),
                start=self.current_page * self.items_per_page + 1,
            ):
                track = cast(Dict[str, Any], track)
                track_name = track.get("title", "Unnamed Song")
                track_url = track.get("url", "https://example.com")
                track_lines.append(f"**{idx}.** [{track_name}]({track_url})")

            embed.description = "\n".join(track_lines)
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.page_count}")

        return embed
