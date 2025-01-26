from views import PaginatedView

import discord
from typing import List, Tuple, Any


class PlaylistListView(PaginatedView):
    """
    View for displaying a paginated list of playlists.
    """

    def __init__(self, playlists: List[Tuple[Any, Any, str]]):
        super().__init__(playlists)
        self.playlists = playlists

    def create_embed(self) -> discord.Embed:
        """
        Creates the embed displaying the current page of playlists.
        """
        embed = discord.Embed(
            title=f"Playlists Saved: {len(self.item_list)}",
            color=discord.Color.blue(),
        )

        if not self.item_list:
            embed.description = "No playlists found."
        else:
            playlist_text_lines = []
            for idx, playlist in enumerate(
                self.get_current_page_items(),
                start=self.current_page * self.items_per_page + 1,
            ):
                playlist_text_lines.append(f"{idx}. {playlist[2]}")

            embed.description = "\n".join(playlist_text_lines)
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.page_count}")

        return embed


class PlaylistTrackView(PaginatedView):
    """
    View for displaying a paginated list of playlist tracks.
    """

    def __init__(self, tracks: List[Tuple[Any, Any, str, str]]):
        super().__init__(tracks)
        self.tracks = self.item_list

    def create_embed(self) -> discord.Embed:
        """
        Creates the embed displaying the current page of playlist tracks.
        """
        embed = discord.Embed(
            title=f"Playlist Tracks: {len(self.item_list)}",
            color=discord.Color.blue(),
        )

        if not self.item_list:
            embed.description = "No tracks in this playlist."
        else:
            track_lines = []
            for idx, track in enumerate(
                self.get_current_page_items(),
                start=self.current_page * self.items_per_page + 1,
            ):
                track_line = f"{idx}. [{track[3]}]({track[2] if track[2] else ''})"
                track_lines.append(track_line)

            embed.description = "\n".join(track_lines)
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.page_count}")

        return embed
