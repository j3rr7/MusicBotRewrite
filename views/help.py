import math
import traceback
import wavelink
import discord
import logging
from discord.ui import View, Button
from typing import List, Any, Dict


class HelpView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.current_page = 0
        self.pages = [
            {
                "title": "Playback Commands",
                "description": [
                    ("/play <query>", "Play a song or add it to the queue"),
                    ("/playnext <query>", "Add a song to the top of the queue"),
                    (
                        "/playskip <query>",
                        "Play a song immediately, skipping the current song",
                    ),
                    ("/stop", "Stop playback and clear the queue"),
                    ("/skip", "Skip the currently playing song"),
                    ("/pause", "Pause playback"),
                    ("/resume", "Resume playback"),
                    (
                        "/seek <timestamp>",
                        "Seek to a specific time in the current song (e.g., 1:30, 30s)",
                    ),
                    ("/shuffle", "Shuffle the queue"),
                    ("/loop <state>", "Set loop mode (none, song, queue)"),
                    ("/volume <volume>", "Set the volume (0-100)"),
                    ("/autoplay <state>", "Enable or disable autoplay (on, off)"),
                    ("/disconnect", "Disconnect the bot from the voice channel"),
                    ("/queue", "Display the current queue"),
                ],
            },
            {
                "title": "Playlist Management Commands",
                "description": [
                    ("/playlist list [member]", "List your or a member's playlists"),
                    (
                        "/playlist create <name> [public]",
                        "Create a new playlist (default public)",
                    ),
                    (
                        "/playlist rename <playlist_name> <new_name>",
                        "Rename a playlist",
                    ),
                    ("/playlist delete <playlist_name>", "Delete a playlist"),
                    ("/playlist view <playlist_name> [member]", "View a playlist"),
                    (
                        "/playlist export <playlist_name> <extension>",
                        "Export a playlist (e.g., .txt, .json)",
                    ),
                    (
                        "/playlist import [playlist_name]",
                        "Import a playlist (file upload)",
                    ),
                    ("/playlist play <playlist_name>", "Play a playlist"),
                    ("/playlist current", "Shows the currently playing playlist"),
                ],
            },
            {
                "title": "Song Management Commands",
                "description": [
                    (
                        "/song add <playlist_name> [song_url] [song_title]",
                        "Add a song to a playlist (either URL or title)",
                    ),
                    (
                        "/song remove <playlist_name> <index>",
                        "Remove a song from a playlist by its index",
                    ),
                    (
                        "/song move <playlist_name> <index> <target> [mode]",
                        "Move a song within a playlist",
                    ),
                    ("/song clear <playlist_name>", "Clear all songs from a playlist"),
                    (
                        "/song shuffle <playlist_name>",
                        "Shuffle songs within a playlist",
                    ),
                ],
            },
        ]

        # Add the navigation buttons
        self.add_item(
            Button(
                style=discord.ButtonStyle.primary,
                custom_id="previous",
                label="◀",
                disabled=True,
            )
        )
        self.add_item(
            Button(style=discord.ButtonStyle.primary, custom_id="next", label="▶")
        )

    def create_embed(self) -> discord.Embed:
        page = self.pages[self.current_page]

        embed = discord.Embed(
            title="Music Bot Help",
            description=f"**{page['title']}**\nPage {self.current_page + 1}/{len(self.pages)}",
            color=discord.Color.blue(),
        )

        # Add commands for current page
        for command, description in page["description"]:
            embed.add_field(name=command, value=description, inline=False)

        embed.set_footer(text=f"Use the buttons below to navigate through the pages")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data["custom_id"] == "next":
            await self.next_page(interaction)
        elif interaction.data["custom_id"] == "previous":
            await self.previous_page(interaction)
        return True

    async def next_page(self, interaction: discord.Interaction):
        self.current_page = min(self.current_page + 1, len(self.pages) - 1)

        # Update button states
        self.update_buttons()

        # Update the message with new embed
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)

        # Update button states
        self.update_buttons()

        # Update the message with new embed
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    def update_buttons(self):
        # Get the buttons
        previous_button = self.children[0]
        next_button = self.children[1]

        # Update previous button state
        previous_button.disabled = self.current_page == 0

        # Update next button state
        next_button.disabled = self.current_page == len(self.pages) - 1
