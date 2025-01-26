import re
import json
import zlib
import base64
import asyncio
import logging
import datetime
import traceback

from database import DatabaseManager
from typing import Optional, List
from views.queue import QueueView
from views.playlist import PlaylistListView, PlaylistTrackView
from modals.playlist import ImportPlaylistModal
from config import ADMIN_IDS

import discord
import wavelink
from discord import app_commands
from discord.ext import commands, tasks


class Music(commands.Cog):
    """Music cog to handle music related commands."""

    playlist_group = app_commands.Group(
        name="playlist", description="Playlist commands", guild_only=True
    )
    playlist_song = app_commands.Group(
        name="song", description="Song commands", guild_only=True
    )

    def __init__(self, bot: commands.AutoShardedBot):
        """Initializes the Music cog."""

        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.nodes = []

        self.use_local_lavalink = True
        self.database: DatabaseManager = getattr(bot, "database", None)

    async def cog_load(self):
        """Called when the cog is loaded."""
        self.logger.info("Cog loaded")
        asyncio.create_task(self.setup_lavalink())

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        self.logger.info("Cog unloaded")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        """Event listener for when a Wavelink node is ready."""
        node = payload.node
        resumed = payload.resumed
        self.logger.debug(f"Wavelink Node connected: {node} | Resumed: {resumed}")

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Event listener for when a Wavelink player becomes inactive."""
        self.logger.debug(
            f"Player {player} is inactive for {player.inactive_timeout} seconds. Disconnecting."
        )
        await player.disconnect()

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        """Event listener for when a Wavelink track starts playing."""
        track = payload.track
        player = payload.player
        self.logger.debug(f"Track started: {track} on player {player}")

    async def setup_lavalink(self):
        """Sets up the Lavalink connection."""
        await self.bot.wait_until_ready()
        self.logger.debug("Setting up lavalink")

        try:
            await wavelink.node.Pool.close()

            if self.use_local_lavalink:
                node = wavelink.Node(
                    uri="http://localhost:2333",
                    identifier="Local Lavalink",
                    password="youshallnotpass",
                )
                self.nodes.append(node)
                self.logger.debug(f"Added local Lavalink node: {node.identifier}")

            await wavelink.node.Pool.connect(
                nodes=self.nodes, client=self.bot, cache_capacity=100
            )
            self.logger.info("Lavalink connection setup complete.")
        except Exception as e:
            self.logger.error(f"Error setting up Lavalink: {e}", exc_info=True)
            raise

    @staticmethod
    def convert_timestamp_to_milliseconds(timestamp: str) -> int:
        """Converts a timestamp string (e.g., '1m30s', '90s') to milliseconds using regex."""
        timestamp = timestamp.lower()
        minutes_match = re.search(r"(\d+)m", timestamp)
        seconds_match = re.search(r"(\d+)s", timestamp)

        if not minutes_match and not seconds_match:
            raise ValueError("Invalid timestamp format")

        minutes = int(minutes_match.group(1)) if minutes_match else 0
        seconds = int(seconds_match.group(1)) if seconds_match else 0

        return (minutes * 60 + seconds) * 1000

    @staticmethod
    def format_duration(milliseconds: int) -> str:
        """Formats milliseconds into a readable duration string (mm:ss or ss)."""
        seconds = milliseconds // 1000
        minutes, seconds = divmod(seconds, 60)
        if minutes:
            return f"{minutes}m{seconds:02}s"  # Ensure seconds are always two digits if minutes exist
        return f"{seconds}s"

    @staticmethod
    def convert_autoplay_mode(mode_string: str) -> Optional[wavelink.AutoPlayMode]:
        """Converts a string to a wavelink.AutoPlayMode enum member."""
        mode_string = mode_string.lower()
        mode_map = {
            "partial": wavelink.AutoPlayMode.partial,
            "disabled": wavelink.AutoPlayMode.disabled,
            "enabled": wavelink.AutoPlayMode.enabled,
        }
        return mode_map.get(mode_string)

    @staticmethod
    def convert_loop_mode(mode_string: str) -> Optional[wavelink.QueueMode]:
        """Converts a string to a wavelink.QueueMode enum member."""
        mode_string = mode_string.lower()
        mode_map = {
            "normal": wavelink.QueueMode.normal,
            "loop": wavelink.QueueMode.loop,
            "loopall": wavelink.QueueMode.loop_all,
        }
        return mode_map.get(mode_string)

    async def _send_error_as_embed(
        self, interaction: discord.Interaction, message: str, ephemeral: bool = False
    ):
        """Sends an error embed to the interaction."""

        embed = discord.Embed(
            title="Error",
            description=message,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(
                    embed=embed, ephemeral=ephemeral
                )
        except discord.errors.InteractionResponded:  # Handle in case of race conditions
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            self.logger.exception(f"Error sending error embed: {e}")

    async def ensure_player_connection(
        self,
        interaction: discord.Interaction,
        is_ephemeral: bool = False,
        deafen: bool = True,
    ) -> Optional[wavelink.Player]:
        """Ensures the bot is connected to a voice channel.

        Returns the player if connected, otherwise sends an error and returns None.
        """
        player: wavelink.Player | None = interaction.guild.voice_client
        if player:
            return player

        voice_channel = (
            interaction.user.voice.channel if interaction.user.voice else None
        )
        if not voice_channel:
            await self._send_error_embed(
                interaction,
                "You need to be in a voice channel to use this command.",
                is_ephemeral,
            )
            return None

        try:
            player = await voice_channel.connect(cls=wavelink.Player, self_deaf=deafen)
            self.logger.debug(
                f"Connected player to voice channel: {voice_channel.name}"
            )
            return player
        except Exception as e:
            self.logger.error(f"Failed to connect to voice channel: {e}", exc_info=True)
            await self._send_error_embed(
                interaction, "Failed to connect to voice channel.", is_ephemeral
            )
            return None

    async def _get_user_settings(
        self, user_id: int
    ) -> tuple[int, wavelink.AutoPlayMode]:
        """Retrieves user settings from the database or defaults."""
        default_volume = 30
        default_autoplay = wavelink.AutoPlayMode.partial

        if not self.database:
            return default_volume, default_autoplay

        try:
            user_settings = await self.database.get_one(
                "user_settings", "user_id = ?", (user_id,)
            )
            if not user_settings:
                await self.database.insert(
                    "user_settings",
                    [
                        {
                            "user_id": user_id,
                            "volume": default_volume,
                            "autoplay": "partial",
                        }
                    ],
                )
                return default_volume, default_autoplay

            volume = int(user_settings[1])
            autoplay_str = str(user_settings[3])
            autoplay = (
                self.convert_autoplay_mode(autoplay_str) or default_autoplay
            )  # Fallback in case of invalid string in DB
            return volume, autoplay

        except Exception as e:
            self.logger.error(
                f"[DATABASE] Error getting user settings for user {user_id}: {e}",
                exc_info=True,
            )
            return default_volume, default_autoplay  # Return defaults on error

    async def _search_tracks(self, query: str) -> Optional[wavelink.Search]:
        """Searches for tracks using wavelink.Playable.search and handles errors."""
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query)
            return tracks
        except Exception as e:
            self.logger.error(f"Error during track search for query '{query}': {e}", exc_info=True)
            return None
    
    def _create_track_embed(self, track: wavelink.Playable, queue_position_text: str) -> discord.Embed:
        """Creates a standardized embed for a track being added to the queue."""
        embed = discord.Embed(
            title="Track Added to Queue",
            description=f"[{track.title}]({track.uri}) by **{track.author}** added {queue_position_text}.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        return embed

    def _create_playlist_embed(self, playlist: wavelink.Playlist, added_count: int) -> discord.Embed:
        """Creates a standardized embed for a playlist being added to the queue."""
        embed = discord.Embed(
            title="Playlist Added to Queue",
            description=f"**`{playlist.name}`** ({added_count} songs) added.",
            color=discord.Color.yellow(),
            timestamp=discord.utils.utcnow(),
        )
        if playlist.artwork:
            embed.set_thumbnail(url=playlist.artwork)
        return embed

    async def _autocomplete_query(self, interaction: discord.Interaction, query: str) -> List[app_commands.Choice[str]]:
        """Reusable autocomplete function for track queries."""
        if not query or len(query) < 3:
            return []

        tracks: Optional[wavelink.Search] = await self._search_tracks(query)
        if not tracks:
            return []

        choices: List[app_commands.Choice[str]] = []
        for track in tracks[:10]:
            if isinstance(track, wavelink.Playable):
                choices.append(
                    app_commands.Choice(name=f"{track.title[:80]}", value=track.uri)
                )
        return choices

    @app_commands.command(
        name="play", description="Play a song given a URL or a search query."
    )
    @app_commands.guild_only()
    @app_commands.describe(query="The query to play.")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player: wavelink.Player = (
            interaction.guild.voice_client
            or await self.ensure_player_connection(interaction)
        )
        if not player:
            return

        # grab user settings from database if they exist
        try:
            user_settings = await self.database.get_one(
                "user_settings", "user_id = ?", (interaction.user.id,)
            )
            if not user_settings:
                await self.database.insert(
                    "user_settings",
                    [
                        {
                            "user_id": interaction.user.id,
                            "volume": 30,
                            "autoplay": "partial",
                        }
                    ],
                )
                volume, autoplay = 30, wavelink.AutoPlayMode.partial
            else:
                volume = int(user_settings[1])
                autoplay = self.convert_autoplay_mode(str(user_settings[3]))
        except Exception as e:
            self.logger.error(f"[DATABASE] Error getting user settings: {e}")
            volume, autoplay = 30, wavelink.AutoPlayMode.partial

        tracks: wavelink.Search = await wavelink.Playable.search(query)

        if not tracks:
            await interaction.followup.send(
                f"I'm unable to find the requested song.", ephemeral=True
            )
            return

        player.autoplay = autoplay

        if isinstance(tracks, wavelink.Playlist):
            added: int = await player.queue.put_wait(tracks)
            embed = discord.Embed(
                title="Playlist Added",
                description=f"**`{tracks.name}`** ({added} songs) to the queue.",
                color=discord.Color.yellow(),
                timestamp=discord.utils.utcnow(),
            )
            if tracks.artwork:
                embed.set_thumbnail(url=tracks.artwork)
            await interaction.followup.send(embed=embed)
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)

            embed = discord.Embed(
                title=f"**{track.title}** - {track.author}",
                description=f"[{track.title}]({track.uri}) added to the queue.",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)

            await interaction.followup.send(embed=embed)

        if not player.playing:
            # Play now since we aren't playing anything...
            await player.play(player.queue.get(), volume=volume)

    @play.autocomplete(name="query")
    async def play_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        if not query or len(query) < 3:
            return []

        try:
            results: wavelink.Search = await wavelink.Playable.search(query)
            choices = []

            for track in results[:10]:
                if isinstance(track, wavelink.Playable):
                    choices.append(
                        app_commands.Choice(name=f"{track.title[:80]}", value=track.uri)
                    )
            return choices
        except Exception as e:
            return []

    @app_commands.command(
        name="playnext", description="Plays the song after the current song."
    )
    @app_commands.guild_only()
    async def playnext(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player: wavelink.Player = (
            interaction.guild.voice_client
            or await self.ensure_player_connection(interaction)
        )
        if not player:
            return

        tracks: wavelink.Search = await wavelink.Playable.search(query)

        if not tracks:
            await interaction.followup.send(
                f"{interaction.user.mention} - Unable to find track.", ephemeral=True
            )
            return

        if isinstance(tracks, wavelink.Playlist):
            await interaction.followup.send(
                "You cannot add a playlist to the queue after the current song.",
                ephemeral=True,
            )
            return
            added: int = await player.queue.put_wait(tracks)

        else:
            track: wavelink.Playable = tracks[0]
            player.queue.put_at(1, track)

        embed = discord.Embed(
            title=f"**{track.title}** - {track.author}",
            description=f"[{track.title}]({track.uri}) added to the queue after the current song.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        await interaction.followup.send(embed=embed, ephemeral=False)

    @playnext.autocomplete(name="query")
    async def playnext_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        if not query or len(query) < 3:
            return []

        try:
            results: wavelink.Search = await wavelink.Playable.search(query)
            choices = []

            for track in results[:10]:
                if isinstance(track, wavelink.Playable):
                    choices.append(
                        app_commands.Choice(name=f"{track.title[:80]}", value=track.uri)
                    )
            return choices
        except Exception as e:
            return []

    @app_commands.command(
        name="playskip",
        description="Skips the current song and plays the song after the current song.",
    )
    @app_commands.guild_only()
    async def playskip(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player: wavelink.Player = (
            interaction.guild.voice_client
            or await self.ensure_player_connection(interaction)
        )
        if not player:
            return

        tracks: wavelink.Search = await wavelink.Playable.search(query)

        if not tracks:
            await interaction.followup.send(
                f"{interaction.user.mention} - Unable to find track.", ephemeral=True
            )
            return

        if isinstance(tracks, wavelink.Playlist):
            await interaction.followup.send(
                "You cannot add a playlist to the queue after the current song.",
                ephemeral=True,
            )
            return
            added: int = await player.queue.put_wait(tracks)

        else:
            track: wavelink.Playable = tracks[0]
            player.queue.put_at(1, track)
            await player.skip(force=True)

        embed = discord.Embed(
            title=f"**{track.title}** - {track.author}",
            description=f"[{track.title}]({track.uri}) Added to the queue, skipping current song.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        await interaction.followup.send(embed=embed, ephemeral=False)

    @playskip.autocomplete(name="query")
    async def playskip_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        if not query or len(query) < 3:
            return []

        try:
            results: wavelink.Search = await wavelink.Playable.search(query)
            choices = []

            for track in results[:10]:
                if isinstance(track, wavelink.Playable):
                    choices.append(
                        app_commands.Choice(name=f"{track.title[:80]}", value=track.uri)
                    )
            return choices
        except Exception as e:
            return []

    @app_commands.command(name="stop", description="Stops the player.")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player or not player.playing:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unable to Stop",
                    description="There is no music playing or player is not connected",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                ),
                ephemeral=True,
            )
            return

        if not player.queue.is_empty:
            player.queue.reset()

        await player.stop(force=True)
        await player.disconnect()

        embed = discord.Embed(
            title="Player Stopped",
            description="🛑 Stopped the player and cleared the queue.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="skip", description="Skips the current song.")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        # if player is disconnected or no music playing return
        if not player or not player.playing:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unable to Skip",
                    description="There is no music playing or player is not connected.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                ),
                ephemeral=True,
            )
            return

        await player.skip(force=True)

        embed = discord.Embed(
            title=f"⏩ Skipped Song",
            description="Skipped the current song.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="pause",
        description="Pauses the player. Run again to resume or use /resume.",
    )
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unable to Pause/Resume",
                    description="I'm not connected to a voice channel or nothing is playing.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        new_pause_state = not player.paused
        action_word = "Paused" if new_pause_state else "Resumed"
        emoji = "⏸️" if new_pause_state else "▶️"

        await player.pause(new_pause_state)

        embed = discord.Embed(
            title=f"Player {action_word}",
            description=f"{emoji} Player has been {action_word.lower()}.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="resume",
        description="Resumes the player. Run again to pause or use /pause.",
    )
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unable to Pause/Resume",
                    description="I'm not connected to a voice channel or nothing is playing.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        new_pause_state = not player.paused
        action_word = "Paused" if new_pause_state else "Resumed"
        emoji = "⏸️" if new_pause_state else "▶️"

        await player.pause(new_pause_state)

        embed = discord.Embed(
            title=f"Player {action_word}",
            description=f"{emoji} Player has been {action_word.lower()}.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="seek", description="Seek current song to a specific timestamp."
    )
    @app_commands.guild_only()
    @app_commands.describe(timestamp="The timestamp to seek to. (e.g., 1s, 1m1s etc.)")
    async def seek(self, interaction: discord.Interaction, timestamp: str):
        player: wavelink.Player = interaction.guild.voice_client

        if not player or not player.current:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        # Convert timestamp string to milliseconds
        try:
            milliseconds = self.convert_timestamp_to_milliseconds(timestamp)
        except ValueError:
            await interaction.response.send_message(
                "Invalid timestamp format. Please use format like '1m30s', '90s', etc.",
                ephemeral=True,
            )
            return

        # Check if the timestamp is within track duration
        if milliseconds > player.current.length:
            await interaction.response.send_message(
                f"Timestamp exceeds track duration ({self.format_duration(player.current.length)})",
                ephemeral=True,
            )
            return

        # Seek to position
        await player.seek(milliseconds)
        await interaction.response.send_message(
            f"Seeked to {self.format_duration(milliseconds)}"
        )

    @app_commands.command(name="shuffle", description="Shuffles the queue.")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        player.queue.shuffle()

        embed = discord.Embed(
            title="Queue Shuffled",
            description="🔀 Shuffled the queue.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="loop", description="Sets the loop state.")
    @app_commands.guild_only()
    @app_commands.choices(
        state=[
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Loop", value="loop"),
            app_commands.Choice(name="Loop All", value="loopall"),
        ]
    )
    async def loop(
        self, interaction: discord.Interaction, state: app_commands.Choice[str]
    ):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        wavelink.Queue.mode = self.convert_loop_mode(state.value)

        embed = discord.Embed(
            title="Loop State Changed",
            description=f"🔁 Loop set to `{state.name}`",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="volume", description="Sets the volume.")
    @app_commands.guild_only()
    @app_commands.describe(volume="The volume to set (0-1000)")
    async def volume(self, interaction: discord.Interaction, volume: int):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        volume = max(0, min(1000, volume))  # Clamp volume to 0-1000

        # database update
        try:
            await self.database.update(
                "user_settings",
                {"volume": volume},
                f"user_id = ?",
                (interaction.user.id,),
            )
        except Exception as e:
            self.logger.error(f"Error updating volume in database: {e}")

        await player.set_volume(volume)

        embed = discord.Embed(
            title="Volume Changed",
            description=f"🔊 Volume changed to `{volume}`",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="autoplay", description="Change autoplay state.")
    @app_commands.guild_only()
    @app_commands.choices(
        state=[
            app_commands.Choice(name="disabled", value="disabled"),
            app_commands.Choice(name="partial", value="partial"),
            app_commands.Choice(name="enabled", value="enabled"),
        ]
    )
    async def autoplay(
        self, interaction: discord.Interaction, state: app_commands.Choice[str]
    ):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        player.autoplay = self.convert_autoplay_mode(state.value)

        embed = discord.Embed(
            title="Autoplay Changed",
            description=f"Autoplay changed to `{state.name}`",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="connect", description="Connect to the voice channel.")
    @app_commands.guild_only()
    @app_commands.describe(deafen="Whether to deafen the bot or not.")
    async def connect(self, interaction: discord.Interaction, deafen: bool = True):
        player: wavelink.Player = (
            interaction.guild.voice_client
            or await self.ensure_player_connection(interaction, deafen=deafen)
        )

        if not player:
            return

        embed = discord.Embed(
            title="Connected",
            description="👋 Connected to voice channel",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnects the player.")
    @app_commands.guild_only()
    async def disconnect(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        await player.disconnect()

        embed = discord.Embed(
            title="Disconnected",
            description="👋 Disconnected from voice channel",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="queue", description="Displays the current queue.")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        view = QueueView(player)
        await interaction.response.send_message(
            embed=view.create_embed(), view=view, ephemeral=False
        )

    @app_commands.command(name="clear", description="Clears the queue.")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        player.queue.clear()
        await interaction.response.send_message("Queue cleared", ephemeral=True)

    @app_commands.command(name="np", description="Shows the current playing song.")
    @app_commands.guild_only()
    async def np(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player: wavelink.Player = interaction.guild.voice_client

        if not player or not player.current:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=False
            )
            return

        embed = discord.Embed(
            title="Now Playing",
            description=f"[**{player.current.title}**]({player.current.uri})",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if player.current.artwork:
            embed.set_thumbnail(url=player.current.artwork)

        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(
        name="stuck",
        description="Use this if music is stuck. (Will restart the player)",
    )
    @app_commands.guild_only()
    async def stuck(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=False
            )
            return

        if player.paused:
            player.pause(False)

        self.logger.info(f"Player {player} is stuck, restarting player...")
        self.logger.debug(
            f"Player {player}\n  queue: {player.queue}, playing: {player.playing}, current: {player.current}, paused: {player.paused}"
        )

        current_track = player.current
        if not current_track:
            await player.play(player.queue.get())
        else:
            await player.play(current_track)

    # =========================
    # Playlist
    # =========================

    @playlist_group.command(name="list", description="Lists of saved playlists.")
    @app_commands.describe(member="Playlist owner")
    async def playlist_list(
        self, interaction: discord.Interaction, member: discord.Member = None
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            if member:
                playlists = await self.database.get(
                    "playlists", f"user_id = ? AND is_public = 1", (member.id,)
                )

                view = PlaylistListView(playlists)
                await interaction.followup.send(embed=view.create_embed(), view=view)
            else:
                # TODO: Edit This
                # playlists = await self.database.get("playlists")
                # await interaction.followup.send(
                #     "Unable to get playlists globally, use tag instead", ephemeral=True
                # )
                playlists = await self.database.get(
                    "playlists", f"user_id = ?", (interaction.user.id,)
                )
                view = PlaylistListView(playlists)
                await interaction.followup.send(embed=view.create_embed(), view=view)
        except Exception as e:
            await interaction.followup.send(
                f"Failed to list playlists: {e}", ephemeral=True
            )

    @playlist_group.command(name="create", description="Creates a playlist.")
    @app_commands.describe(
        name="The name of the playlist.",
        public="Whether the playlist is shown to other users.",
    )
    async def playlist_create(
        self, interaction: discord.Interaction, name: str, public: bool = True
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.database.insert(
                "playlists",
                [
                    {
                        "name": name,
                        "user_id": interaction.user.id,
                        "is_public": bool(public),
                    }
                ],
                mode="ignore",
            )
            await interaction.followup.send(
                f"Playlist '{name}' created, use '/song add' to add songs or '/song current' to insert current queue into playlist",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to create playlist: {e}", ephemeral=True
            )

    @playlist_group.command(name="rename", description="Renames a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        new_name="The new name of the playlist.",
    )
    async def playlist_rename(
        self, interaction: discord.Interaction, playlist_name: str, new_name: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            # get playlist with that name
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # check ownership
            if int(playlist[1]) != interaction.user.id:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is not owned by you", ephemeral=True
                )
                return

            # check if new_name is same as old_name
            if playlist_name == new_name:
                await interaction.followup.send(
                    "New name cannot be the same as old name", ephemeral=True
                )
                return

            # check if new_name already exists
            if await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (new_name, interaction.user.id),
            ):
                await interaction.followup.send(
                    f"Playlist with '{new_name}' already exists", ephemeral=True
                )
                return

            # update playlist
            await self.database.update(
                "playlists",
                {
                    "name": new_name,
                    "updated_at": datetime.datetime.now(
                        datetime.timezone(datetime.timedelta(hours=7))
                    ),
                },
                "id = ?",
                (playlist[0],),
            )

            await interaction.followup.send(
                f"Playlist '{playlist_name}' renamed to '{new_name}'", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to rename playlist: {e}", ephemeral=True
            )

    @playlist_group.command(name="delete", description="Remove a playlist.")
    @app_commands.describe(playlist_name="The name of the playlist.")
    async def playlist_delete(
        self, interaction: discord.Interaction, playlist_name: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )
            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # check ownership
            if int(playlist[1]) != interaction.user.id:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is not owned by you", ephemeral=True
                )
                return

            # delete playlist
            await self.database.delete(
                "playlists",
                "id = ?",
                (playlist[0],),
            )

            # TODO: delete all playlist songs
            await self.database.delete(
                "tracks",
                "playlist_id = ?",
                (playlist[0],),
            )

            await interaction.followup.send(
                f"Deleted playlist '{playlist_name}', use '/playlist list' to see all your playlists ",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to delete playlist: {e}", ephemeral=True
            )

    @playlist_group.command(name="view", description="Views a playlist.")
    @app_commands.describe(
        member="The member to view the playlist for. (Optional)",
        playlist_name="The name of the playlist.",
    )
    async def playlist_view(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        member: discord.Member = None,
    ):
        await interaction.response.defer()

        try:
            if member:
                playlist = await self.database.get_one(
                    "playlists",
                    "name = ? AND user_id = ? AND is_public = 1",
                    (playlist_name, member.id),
                )
            else:
                playlist = await self.database.get_one(
                    "playlists",
                    "name = ? AND user_id = ?",
                    (playlist_name, interaction.user.id),
                )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            tracks = list(
                await self.database.get("tracks", "playlist_id = ?", (playlist[0],))
            )

            if not tracks or len(tracks) == 0:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is empty", ephemeral=True
                )
                return

            view = PlaylistTrackView(tracks)

            await interaction.followup.send(embed=view.create_embed(), view=view)
        except Exception as e:
            await interaction.followup.send(
                f"Failed to view playlist: {e}", ephemeral=True
            )
            return

    # TODO: a lot of implementation here

    @playlist_group.command(name="export", description="Exports your playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        extension="Use 'auto' to let the bot decide. (default: auto)",
    )
    @app_commands.choices(
        extension=[
            app_commands.Choice(name="auto", value="auto"),
            app_commands.Choice(name="image", value="image"),
        ]
    )
    async def playlist_export(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        extension: str = "auto",
    ):
        await interaction.response.defer()

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # get all tracks in the playlist
            tracks = await self.database.get(
                "tracks", "playlist_id = ?", (playlist[0],)
            )

            if not tracks or len(tracks) == 0:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is empty", ephemeral=True
                )
                return

            tracks_obj = {
                "playlist_name": playlist[2],
                "playlist_owner": playlist[1],
                "songs": [
                    {
                        "title": track[3],
                        "url": track[2],
                        "artist": track[4],
                        "duration": track[5],
                        "position": track[7],
                    }
                    for track in tracks
                ],
            }

            # export playlist
            json_data = json.dumps(tracks_obj)
            compressed_data = zlib.compress(json_data.encode("utf-8"))
            # f = Fernet(FERNET_KEY)
            # encrypted_data = f.encrypt(compressed_data)
            base64_data = base64.urlsafe_b64encode(compressed_data).decode("utf-8")

            # send base64 string if less than 2000 characters
            if len(base64_data) <= 2000:
                await interaction.followup.send(f"```{base64_data}```", ephemeral=True)
                return

            await interaction.followup.send("Unable to export playlist", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Failed to export playlist: {e}", ephemeral=True
            )
            return

    @playlist_group.command(name="import", description="Imports a playlist.")
    async def playlist_import(
        self, interaction: discord.Interaction, playlist_name: str = "Imported Playlist"
    ):
        playlist_modal = ImportPlaylistModal(interaction, self.database, playlist_name)
        await interaction.response.send_modal(playlist_modal)

    # TODO: implement this
    @playlist_group.command(name="play", description="Plays a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        member="playlist owner",
        shuffled="Whether to shuffle the playlist.",
    )
    async def playlist_play(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        member: discord.Member = None,
        shuffled: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            player: wavelink.Player = (
                interaction.guild.voice_client
                or await self.ensure_player_connection(interaction)
            )

            if not player:
                return

            user_settings = await self.database.get_one(
                "user_settings", "user_id = ?", (interaction.user.id,)
            )

            if not user_settings:
                await self.database.insert(
                    "user_settings",
                    [
                        {
                            "user_id": interaction.user.id,
                            "volume": 30,
                            "autoplay": "partial",
                        }
                    ],
                )
                volume, autoplay = 30, wavelink.AutoPlayMode.partial
            else:
                volume = int(user_settings[1])
                autoplay = self.convert_autoplay_mode(str(user_settings[3]))

            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, member.id if member else interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )

            tracks = await self.database.get(
                "tracks", "playlist_id = ?", (playlist[0],)
            )

            if not tracks or len(tracks) == 0:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is empty", ephemeral=True
                )
                return

            for track in tracks:
                track_ = await wavelink.Playable.search(track[2])  # the url
                await player.queue.put_wait(track_[0])

            player.autoplay = autoplay

            if shuffled:
                player.queue.shuffle()

            if not player.playing:
                await player.play(player.queue.get(), volume=volume)

            embed = discord.Embed(
                title=f"Playing Playlist: {playlist_name}",
                description=f"Playing {len(tracks)} tracks",
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Requested by {interaction.user}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"Failed to play playlist: {e}", ephemeral=True
            )

    @playlist_play.autocomplete(name="playlist_name")
    async def playlist_play_autocomplete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=playlist[2], value=playlist[2])
            for playlist in await self.database.get(
                "playlists", "user_id = ?", (interaction.user.id,)
            )
            if str(playlist[2]).startswith(playlist_name)
        ]

    # =========================
    # SONG
    # =========================

    # TODO: Check again
    @playlist_song.command(
        name="current", description="Inserts the current queue into a playlist."
    )
    @app_commands.describe(playlist_name="The name of the playlist.")
    async def playlist_current(
        self, interaction: discord.Interaction, playlist_name: str
    ):
        await interaction.response.defer()

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            query_result = await self.database.query(
                "SELECT MAX(position) FROM tracks WHERE playlist_id = ?",
                (playlist[0],),
            )

            max_position = query_result[0][0]
            new_position = 0 if max_position is None else max_position + 1

            await self.database.delete("tracks", "playlist_id = ?", (playlist[0],))

            if player.playing:
                track = player.current

                await self.database.insert(
                    "tracks",
                    [
                        {
                            "playlist_id": playlist[0],
                            "url": track.uri,
                            "title": track.title,
                            "artist": track.artist.url,
                            "duration": track.length,
                            "position": new_position,
                        }
                    ],
                )

            for i, track in enumerate(player.queue, start=new_position + 1):
                await self.database.insert(
                    "tracks",
                    [
                        {
                            "playlist_id": playlist[0],
                            "url": track.uri,
                            "title": track.title,
                            "artist": track.artist.url,
                            "duration": track.length,
                            "position": i,
                        }
                    ],
                    mode="replace",
                )

            await interaction.followup.send(
                f"Current queue inserted into playlist '{playlist_name}'",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to insert current queue into playlist: {e}", ephemeral=True
            )

    @playlist_song.command(
        name="add",
        description="Adds a song to a playlist using either song URL or title",
    )
    @app_commands.describe(
        playlist_name="The name of the playlist",
        song_title="The title of the song (optional if URL is provided)",
        song_url="The URL of the song (optional if title is provided)",
    )
    async def song_add(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        song_title: Optional[str] = None,
        song_url: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # verify that at least one of song_url or song_title is provided
        if song_url is None and song_title is None:
            await interaction.followup.send(
                "You must provide either a song URL or a song title!", ephemeral=True
            )
            return

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # check ownership
            if int(playlist[1]) != interaction.user.id:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is not owned by you", ephemeral=True
                )
                return

            if song_url:
                query_result = await self.database.query(
                    "SELECT MAX(position) FROM tracks WHERE playlist_id = ?",
                    (playlist[0],),
                )

                max_position = query_result[0][0]
                new_position = 0 if max_position is None else max_position + 1

                await self.database.insert(
                    "tracks",
                    [
                        {
                            "playlist_id": playlist[0],
                            "url": song_url,
                            "title": song_title if song_title else "Unknown Title",
                            "artist": "Unknown Artist",
                            "duration": 0,
                            "position": new_position,
                        }
                    ],
                    mode="ignore",
                )

                await interaction.followup.send(
                    f"Song added to playlist '{playlist_name}'", ephemeral=True
                )
            else:
                song_tracks = await wavelink.Playable.search(song_title)

                if not song_tracks:
                    await interaction.followup.send(
                        f"Could not find a track with the title '{song_title}'",
                        ephemeral=True,
                    )
                    return

                song_url = song_tracks[0].uri
                song_duration = song_tracks[0].length
                song_artist = (
                    "" if song_tracks[0].artist is None else song_tracks[0].title
                )

                query_result = await self.database.query(
                    "SELECT MAX(position) FROM tracks WHERE playlist_id = ?",
                    (playlist[0],),
                )

                max_position = query_result[0][0]
                new_position = 0 if max_position is None else max_position + 1

                await self.database.insert(
                    "tracks",
                    [
                        {
                            "playlist_id": playlist[0],
                            "url": song_url,
                            "title": song_title,
                            "artist": song_artist,
                            "duration": song_duration,
                            "position": new_position,
                        }
                    ],
                    mode="ignore",
                )

                await interaction.followup.send(
                    f"Song [**{song_title}**]({song_url}) added to playlist '{playlist_name}'",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to add track to playlist: {e}", ephemeral=True
            )

    @playlist_song.command(name="remove", description="Removes a song from a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        index="The index of the song in the playlist.",
    )
    async def song_remove(
        self, interaction: discord.Interaction, playlist_name: str, index: int
    ):
        await interaction.response.defer(ephemeral=True)

        # make index human readable and easier to read/understand show index as 1-indexed
        if index <= 0:
            await interaction.followup.send(
                "Index must be greater than 0", ephemeral=True
            )
            return

        # decrement index
        index -= 1

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # check ownership
            if int(playlist[1]) != interaction.user.id:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is not owned by you", ephemeral=True
                )

                return

            # recount positions
            await self.database.query(
                "UPDATE tracks SET position = position - 1 WHERE playlist_id = ? AND position > ?",
                (playlist[0], index),
            )

            # delete track
            await self.database.delete(
                "tracks",
                "playlist_id = ? AND position = ?",
                (playlist[0], index),
            )

            await interaction.followup.send(
                f"Song removed from playlist '{playlist_name}'", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to remove track from playlist: {e}", ephemeral=True
            )
            return

    @playlist_song.command(
        name="clear", description="Clears the playlist of all songs."
    )
    @app_commands.describe(playlist_name="The name of the playlist.")
    async def song_clear(self, interaction: discord.Interaction, playlist_name: str):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist = await self.database.get_one(
                "playlists",
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # check ownership
            if int(playlist[1]) != interaction.user.id:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is not owned by you", ephemeral=True
                )
                return

            # clear all tracks
            await self.database.delete(
                "tracks",
                "playlist_id = ?",
                (playlist[0],),
            )

            await interaction.followup.send(
                f"Playlist '{playlist_name}' cleared", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to clear playlist: {e}", ephemeral=True
            )
            return

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
    await bot.add_cog(Music(bot))
