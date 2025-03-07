import io
import re
import json
import zlib
import base64
import random
import asyncio
import logging
import datetime
import traceback

from database import DatabaseManager
from typing import Optional, List
from views.queue import QueueView
from views.playlist import PlaylistListView, PlaylistTrackView
from modals.playlist import ImportPlaylistModal
from views.song import SongListView
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
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        guild = member.guild

        player: wavelink.Player = guild.voice_client

        if not isinstance(player, wavelink.Player):
            return  # No player in this guild, nothing to do

        bot_channel = player.channel

        if not bot_channel:
            return  # No bot channel, nothing to do

        active_voice_channel = None
        # Determine the active voice channel to check for members
        if before.channel == bot_channel:
            active_voice_channel = before.channel
        elif after.channel == bot_channel:
            active_voice_channel = after.channel

        if active_voice_channel is None:
            return  # Neither before nor after channel is the bot's channel, ignore.

        human_members_in_channel = [
            m for m in active_voice_channel.members if not m.bot
        ]
        human_count = len(human_members_in_channel)

        if human_count == 0:
            # bot is alone
            if player.playing:
                if not player.paused:
                    await player.pause(True)
                    self.logger.debug(
                        f"Paused player in {guild.name} due to no human members in voice channel"
                    )
            elif player.connected:
                await player.disconnect()
                self.logger.debug(
                    f"Disconnected player in {guild.name} due to no human members in voice channel"
                )
        else:
            # bot is not alone
            if player.paused:
                await player.pause(False)
                self.logger.debug(
                    f"Resumed player in {guild.name} due to human members in voice channel"
                )

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

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ):
        self.logger.exception(f"Track exception: {payload.exception}")

    async def setup_lavalink(self):
        """Sets up the Lavalink connection."""
        await self.bot.wait_until_ready()
        self.logger.debug("Setting up lavalink")

        try:
            await wavelink.node.Pool.close()

            if self.use_local_lavalink:
                node = wavelink.Node(
                    uri="http://lavalink:2333",
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
        mode_string = str(mode_string).lower()
        mode_map = {
            "partial": wavelink.AutoPlayMode.partial,
            "disabled": wavelink.AutoPlayMode.disabled,
            "enabled": wavelink.AutoPlayMode.enabled,
        }
        return mode_map.get(mode_string, wavelink.AutoPlayMode.partial)

    @staticmethod
    def convert_loop_mode(mode_string: str) -> Optional[wavelink.QueueMode]:
        """Converts a string to a wavelink.QueueMode enum member."""
        mode_string = str(mode_string).lower()
        mode_map = {
            "normal": wavelink.QueueMode.normal,
            "single": wavelink.QueueMode.loop,
            "all": wavelink.QueueMode.loop_all,
        }
        return mode_map.get(mode_string, wavelink.QueueMode.normal)

    @staticmethod
    def milliseconds_to_hms_string(milliseconds):
        """
        Converts milliseconds (integer) to a string in the format 00h:00m:00s,
        """

        if not isinstance(milliseconds, int):
            raise TypeError("Input must be an integer representing milliseconds.")
        if milliseconds < 0:
            raise ValueError("Milliseconds cannot be negative.")

        seconds = milliseconds // 1000
        minutes = seconds // 60
        seconds %= 60
        hours = minutes // 60
        minutes %= 60

        minutes_str = str(minutes).zfill(2)
        seconds_str = str(seconds).zfill(2)

        if hours > 0:
            hours_str = str(hours).zfill(2)
            return f"{hours_str}h:{minutes_str}m:{seconds_str}s"
        else:
            return f"{minutes_str}m:{seconds_str}s"

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
                    embed=embed, ephemeral=ephemeral, delete_after=60
                )
        except discord.errors.InteractionResponded:  # Handle in case of race conditions
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            self.logger.exception(f"Error sending error embed: {e}")

    async def _send_success_playlist_embed(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        song_title: str,
        ephemeral: bool = False,
    ):
        """Sends a success message as an embed."""

        embed = discord.Embed(
            title="Song Added to Playlist", color=discord.Color.green()
        )
        embed.add_field(name="Playlist", value=playlist_name, inline=False)
        embed.add_field(name="Song", value=song_title, inline=False)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(
                    embed=embed, ephemeral=ephemeral, delete_after=60
                )
        except discord.errors.InteractionResponded:  # Handle in case of race conditions
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            self.logger.exception(f"Error sending success playlist embed: {e}")

    async def _send_embed(
        self,
        interaction: discord.Interaction,
        embed: discord.Embed,
        ephemeral: bool = False,
    ):
        """Sends an embed to the interaction, handling response and followup."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(
                    embed=embed, ephemeral=ephemeral
                )
        except discord.errors.InteractionResponded:  # Handle race conditions
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            self.logger.exception(f"Error sending embed: {e}")

    async def _get_player(
        self, interaction: discord.Interaction
    ) -> Optional[wavelink.Player]:
        """Retrieves the player or connects to the voice channel if necessary.

        Returns the player if connected, otherwise sends an error and returns None.
        """
        player: Optional[wavelink.Player] = interaction.guild.voice_client
        if player:
            return player

        voice_channel: Optional[discord.VoiceChannel] = (
            interaction.user.voice.channel if interaction.user.voice else None
        )
        if not voice_channel:
            await self._send_error_as_embed(
                interaction,
                "You need to be in a voice channel to use this command.",
                ephemeral=True,
            )
            return None

        try:
            player = await voice_channel.connect(cls=wavelink.Player, self_deaf=True)
            self.logger.debug(
                f"Connected player to voice channel: {voice_channel.id}, {voice_channel.name}"
            )
            return player
        except Exception as e:
            self.logger.error(f"Failed to connect to voice channel: {e}", exc_info=True)
            await self._send_error_as_embed(
                interaction,
                "Failed to connect to voice channel.",
                ephemeral=True,
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
            user_settings = await self.database.member.get(user_id)
            if user_settings:
                return user_settings.get(
                    "volume", default_volume
                ), Music.convert_autoplay_mode(user_settings.get("autoplay", "partial"))
            else:
                await self.database.member.create(
                    user_id, volume=default_volume, autoplay="partial"
                )
                return default_volume, default_autoplay
        except Exception as e:
            self.logger.error(
                f"[DATABASE] Error getting user settings for user {user_id}: {e}",
                exc_info=True,
            )
            return default_volume, default_autoplay  # Return defaults on error

    async def _search_tracks(self, query: str) -> Optional[wavelink.Search]:
        """Searches for tracks using wavelink.Playable.search and handles errors."""
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTube)
            return tracks
        except Exception as e:
            self.logger.error(
                f"Error during track search for query '{query}': {e}", exc_info=True
            )
            return None

    def _create_track_embed(
        self, track: wavelink.Playable, queue_position_text: str
    ) -> discord.Embed:
        """Creates a standardized embed for a track being added to the queue."""
        embed = discord.Embed(
            title="Song Added to Queue",
            description=f"[{track.title}]({track.uri}) by **{track.author}** added {queue_position_text}.",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
            url=track.uri,
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        return embed

    def _create_playlist_embed(
        self, playlist: wavelink.Playlist, added_count: int
    ) -> discord.Embed:
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

    async def _enqueue_track(
        self,
        interaction: discord.Interaction,
        query: str,
        play_next: bool = False,
        play_skip: bool = False,
    ):
        """Handles the track enqueueing and playing logic, used by /play, /playnext, and /playskip"""
        player: Optional[wavelink.Player] = await self._get_player(interaction)
        if not player:
            return

        volume, autoplay_mode = await self._get_user_settings(interaction.user.id)
        player.autoplay = autoplay_mode

        tracks: Optional[wavelink.Search] = await self._search_tracks(query)
        if not tracks:
            await self._send_error_as_embed(
                interaction, f"No tracks found for query: `{query}`.", True
            )
            return

        if isinstance(tracks, wavelink.Playlist):
            if play_next or play_skip:
                await self._send_error_as_embed(
                    interaction,
                    f"Playlists cannot be added to the play{'next' if play_next else 'skip'} queue.",
                    True,
                )
                return
            added_count = await player.queue.put_wait(tracks)
            embed = self._create_playlist_embed(tracks, added_count)
        else:
            track: wavelink.Playable = tracks[0]
            if play_next:
                player.queue.put_at(0, track)  # Insert after current track
                queue_position_text = "after the current song"
            elif play_skip:
                player.queue.put_at(0, track)  # Insert at skip position
                queue_position_text = "skipping the current song"
            else:
                await player.queue.put_wait(track)
                queue_position_text = "to the queue"
            embed = self._create_track_embed(track, queue_position_text)

        await self._send_embed(interaction, embed)

        if not player.playing:
            await player.play(player.queue.get(), volume=volume)

        if player.playing and play_skip:
            await player.skip(force=True)

    @app_commands.command(
        name="play", description="Play a song given a URL or a search query."
    )
    @app_commands.guild_only()
    @app_commands.describe(query="The query to play.")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        await self._enqueue_track(interaction, query)

    @app_commands.command(
        name="playnext", description="Plays the song after the current song."
    )
    @app_commands.guild_only()
    async def playnext(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        await self._enqueue_track(interaction, query, play_next=True)

    @app_commands.command(
        name="playskip",
        description="Skips the current song and plays the song after the current song.",
    )
    @app_commands.guild_only()
    async def playskip(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        await self._enqueue_track(interaction, query, play_skip=True)

    async def _autocomplete_query(
        self, interaction: discord.Interaction, query: str
    ) -> List[app_commands.Choice[str]]:
        """Reusable autocomplete function for track queries."""
        if not query or len(query) < 3:
            return []

        tracks: Optional[wavelink.Search] = await self._search_tracks(query)
        if not tracks:
            return []

        choices: List[app_commands.Choice[str]] = []
        for track in tracks[:25]:
            if isinstance(track, wavelink.Playable):
                choices.append(
                    app_commands.Choice(name=f"{track.title[:80]}", value=track.uri)
                )
        return choices

    @play.autocomplete(name="query")
    async def play_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_query(interaction, query)

    @playnext.autocomplete(name="query")
    async def playnext_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_query(interaction, query)

    @playskip.autocomplete(name="query")
    async def playskip_autocomplete(
        self, interaction: discord.Interaction, query: str
    ) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_query(interaction, query)

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

    async def _handle_pause_resume(
        self, interaction: discord.Interaction, pause_state: bool
    ):
        """
        Handles the pause and resume logic, reducing code duplication.

        Args:
            interaction: The Discord interaction.
            pause_state: True to pause, False to resume.
        """
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Unable to Pause/Resume",
                    description="I am not connected to a voice channel or nothing is playing.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        action_word = "Paused" if pause_state else "Resumed"
        emoji = "⏸️" if pause_state else "▶️"

        await player.pause(pause_state)

        embed = discord.Embed(
            title=f"Player {action_word}",
            description=f"{emoji} Player has been {action_word.lower()}.",
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
        await self._handle_pause_resume(interaction, True)

    @app_commands.command(
        name="resume",
        description="Resumes the player. Run again to pause or use /pause.",
    )
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        await self._handle_pause_resume(interaction, False)

    @app_commands.command(
        name="seek", description="Seek current song to a specific timestamp."
    )
    @app_commands.guild_only()
    @app_commands.describe(timestamp="The timestamp to seek to. (e.g., 1s, 1m1s etc.)")
    async def seek(self, interaction: discord.Interaction, timestamp: str):
        player: wavelink.Player = interaction.guild.voice_client

        if not player or not player.playing:
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

        # edge cases
        if not player.current:
            await interaction.response.send_message(
                "Cannot seek to a position if no song is playing.", ephemeral=True
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
            app_commands.Choice(name="Single", value="single"),
            app_commands.Choice(name="All", value="all"),
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
            await self.database.member.update(interaction.user.id, volume=volume)
        except Exception as e:
            self.logger.error(f"Unable to update volume in database: {e}")

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

        try:
            await self.database.member.update(interaction.user.id, autoplay=state.value)
        except Exception as e:
            self.logger.error(f"Unable to save autoplaymode in database: {e}")

        embed = discord.Embed(
            title="Autoplay Changed",
            description=f"Autoplay changed to `{state.name}`",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="connect", description="Connect to the voice channel.")
    @app_commands.guild_only()
    async def connect(self, interaction: discord.Interaction):
        player: wavelink.Player = (
            interaction.guild.voice_client or await self._get_player(interaction)
        )

        if not player:
            return

        embed = discord.Embed(
            title="Connected",
            description=f"👋 Connected to voice channel {player.channel.mention}",
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
        embed = discord.Embed(
            title="Queue Cleared",
            description=f"🗑️ Queue cleared by {interaction.user.mention}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
            title=f"{player.current.title}",
            description=f"Duration: `{Music.milliseconds_to_hms_string(player.current.length)}`",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
            url=player.current.uri,
        )
        if player.current.artwork:
            embed.set_image(url=player.current.artwork)

        await interaction.followup.send(embed=embed, ephemeral=False)

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
            user_id = member.id if member else interaction.user.id
            playlists = await self.database.playlist.list_by_owner(user_id)

            view = PlaylistListView(playlists)
            await interaction.followup.send(embed=view.create_embed(), view=view)
        except Exception as e:
            await interaction.followup.send(
                f"Failed to list playlists: {e}", ephemeral=True
            )

    @playlist_group.command(name="create", description="Creates a playlist.")
    @app_commands.describe(
        name="The name of the playlist.",
        description="The description of the playlist.",
        public="Whether the playlist is shown to other users.",
    )
    async def playlist_create(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str = None,
        public: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.database.playlist.create(
                interaction.user.id, name, description, public=public
            )

            embed = discord.Embed(
                title="Playlist Created",
                description=f"Playlist '{name}' created by {interaction.user.mention}\nUse `/playlist view {name}` to view the playlist\nUse `/playlist delete {name}` to delete the playlist\nUse `/song add {name} <URL>` to add a song to the playlist",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            self.logger.error("Unable to create playlist", exc_info=e)
            await interaction.followup.send("Unable to create playlist", ephemeral=True)

    async def _autocomplete_playlist(
        self, interaction: discord.Interaction, playlist_name: str, owner_id: int
    ) -> List[app_commands.Choice[str]]:
        """Return a list of playlist names."""
        try:

            playlists = await self.database.playlist.list_by_owner(owner_id)

            return [
                app_commands.Choice(
                    name=playlist.get("name", "Unknown"),
                    value=playlist.get("name", "Unknown"),
                )
                for playlist in playlists[:25]
                if str(playlist.get("name", "Unknown")).startswith(playlist_name)
            ]
        except Exception as e:
            self.logger.error("Unable to autocomplete playlist", exc_info=e)
        return []

    @playlist_group.command(name="rename", description="Renames a playlist.")
    @app_commands.describe(
        new_name="The new name of the playlist.",
    )
    async def playlist_rename(
        self, interaction: discord.Interaction, playlist_name: str, new_name: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist: dict = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            await self.database.playlist.update(
                playlist.get("playlist_id"), name=new_name
            )

            await interaction.followup.send(
                f"Playlist '{playlist_name}' renamed to '{new_name}'", ephemeral=True
            )

        except Exception as e:
            self.logger.error("Unable to rename playlist", exc_info=e)
            await interaction.followup.send("Unable to rename playlist", ephemeral=True)

    @playlist_rename.autocomplete("playlist_name")
    async def autocomplete_playlist_rename(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_group.command(name="delete", description="Remove a playlist.")
    async def playlist_delete(
        self, interaction: discord.Interaction, playlist_name: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist: dict = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            await self.database.track.delete_by_playlist_id(playlist.get("playlist_id"))
            await self.database.playlist.delete(playlist.get("playlist_id"))

            await interaction.followup.send(
                f"Deleted playlist '{playlist_name}', use '/playlist list' to see all your playlists ",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to delete playlist: {e}", ephemeral=True
            )

    @playlist_delete.autocomplete("playlist_name")
    async def autocomplete_playlist_delete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_group.command(name="view", description="Views a playlist.")
    @app_commands.describe(
        member="The member to view the playlist for. (Optional)",
    )
    async def playlist_view(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        member: discord.Member = None,
    ):
        await interaction.response.defer()

        try:
            user_id = member.id if member else interaction.user.id
            playlist: dict = await self.database.playlist.get_by_name_owner_id(
                playlist_name, user_id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            tracks = await self.database.track.list_by_playlist(
                playlist.get("playlist_id")
            )
            view = PlaylistTrackView(tracks, playlist.get("name"))
            await interaction.followup.send(embed=view.create_embed(), view=view)
        except Exception as e:
            await interaction.followup.send(
                f"Failed to view playlist: {e}", ephemeral=True
            )
            return

    @playlist_view.autocomplete("playlist_name")
    async def autocomplete_playlist_view(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_group.command(name="export", description="Exports your playlist.")
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
            playlist: dict = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            # get all tracks in the playlist
            tracks = await self.database.track.list_by_playlist(
                playlist.get("playlist_id")
            )

            if not tracks or len(tracks) == 0:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is empty", ephemeral=True
                )
                return

            tracks_obj = {
                "playlist_name": playlist.get("name"),
                "playlist_owner": playlist.get("owner_id"),
                "songs": [
                    {
                        "title": track.get("title"),
                        "url": track.get("url"),
                    }
                    for track in tracks
                ],
            }

            # export playlist
            json_data = json.dumps(tracks_obj)
            compressed_data = zlib.compress(json_data.encode("utf-8"))
            # f = Fernet(FERNET_KEY)
            # encrypted_data = f.encrypt(compressed_data)
            encoded_data = base64.urlsafe_b64encode(compressed_data)
            base64_data = encoded_data.decode("utf-8")

            # send base64 string if less than 2000 characters
            if len(base64_data) <= 2000:
                await interaction.followup.send(f"```{base64_data}```", ephemeral=True)
                return

            if extension != "auto":
                await interaction.followup.send(
                    "Unable to export playlist", ephemeral=True
                )
                return

            io_bytes = io.BytesIO(encoded_data)
            await interaction.followup.send(file=discord.File(io_bytes, "playlist.txt"))

        except Exception as e:
            await interaction.followup.send(
                f"Failed to export playlist: {e}", ephemeral=True
            )
            return

    @playlist_export.autocomplete("playlist_name")
    async def autocomplete_playlist_export(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_group.command(name="import", description="Imports a playlist.")
    async def playlist_import(
        self, interaction: discord.Interaction, playlist_name: str = "Imported Playlist"
    ):
        playlist_modal = ImportPlaylistModal(interaction, self.database, playlist_name)
        await interaction.response.send_modal(playlist_modal)

    @playlist_group.command(name="play", description="Plays a playlist.")
    @app_commands.describe(
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
            player: Optional[wavelink.Player] = await self._get_player(interaction)
            if not player:
                return

            volume, autoplay_mode = await self._get_user_settings(interaction.user.id)
            player.autoplay = autoplay_mode

            user_id = member.id if member else interaction.user.id
            playlist = await self.database.playlist.get_by_name_owner_id(
                playlist_name, user_id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            songs = await self.database.track.list_by_playlist(
                playlist.get("playlist_id")
            )

            if not songs:
                await self._send_error_as_embed(
                    interaction,
                    f"Playlist '{playlist_name}' is empty",
                    True,
                )
                return

            if shuffled:
                random.shuffle(songs)

            for song in songs:
                tracks: Optional[wavelink.Search] = await self._search_tracks(
                    song.get("url")
                )
                if not tracks:
                    await self._send_error_as_embed(
                        interaction,
                        f"No tracks found for query: `{song.get("title")}`.",
                        True,
                    )
                    return

                await player.queue.put_wait(tracks[0])

            if not player.playing:
                await player.play(player.queue.get(), volume=volume)

            embed = discord.Embed(
                title=f"Playing Playlist: {playlist_name}",
                description=f"Playing {len(songs)} songs",
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
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    # =========================
    # SONG
    # =========================

    @playlist_song.command(
        name="current",
        description="Inserts the current queue into a playlist. (Will replace existing playlist)",
    )
    async def song_current(self, interaction: discord.Interaction, playlist_name: str):
        await interaction.response.defer()

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        try:
            playlist = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            await self.database.track.delete_by_playlist_id(playlist.get("playlist_id"))

            if player.playing:
                track = player.current

                await self.database.track.create(
                    playlist.get("playlist_id"), track.title, track.uri
                )

            for i, track_ in enumerate(player.queue):
                await self.database.track.create(
                    playlist.get("playlist_id"), track_.title, track_.uri
                )

            await interaction.followup.send(
                f"Current queue inserted into playlist '{playlist_name}'",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to insert current queue into playlist: {e}", ephemeral=True
            )

    @song_current.autocomplete("playlist_name")
    async def song_current_autocomplete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_song.command(
        name="add",
        description="Adds a song to a playlist using either song URL or title",
    )
    @app_commands.describe(song_query="Song title or song url")
    async def song_add(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        song_query: str,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await self._send_error_as_embed(
                    interaction, f"Playlist '{playlist_name}' not found.", True
                )
                return

            song_tracks = await wavelink.Playable.search(song_query)

            if not song_tracks:
                await self._send_error_as_embed(
                    interaction, f"No tracks found for query: `{song_query}`.", True
                )
                return

            track_title: str = ""

            if isinstance(song_tracks, wavelink.Playlist):
                for track in song_tracks:
                    await self.database.track.create(
                        playlist.get("playlist_id"), track.title, track.uri
                    )
                track_title = song_tracks[0].title
            else:
                await self.database.track.create(
                    playlist.get("playlist_id"),
                    song_tracks[0].title,
                    song_tracks[0].uri,
                )
                track_title = song_tracks[0].title

            await self._send_success_playlist_embed(
                interaction, playlist_name, track_title, True
            )

        except Exception as e:
            await interaction.followup.send(
                f"Failed to add track to playlist: {e}", ephemeral=True
            )

    @song_add.autocomplete("playlist_name")
    async def song_add_playlist_autocomplete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @song_add.autocomplete("song_query")
    async def song_add_query_autocomplete(
        self, interaction: discord.Interaction, song_query: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_query(interaction, song_query)

    @playlist_song.command(name="remove", description="Removes a song from a playlist.")
    async def song_remove(self, interaction: discord.Interaction, playlist_name: str):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            tracks = await self.database.track.list_by_playlist(
                playlist.get("playlist_id")
            )

            if not tracks:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' is empty.", ephemeral=True
                )
                return

            # Show Select from tracks select one and remove using
            # self.database.track.delete(track_id)
            view = SongListView(self.database, tracks, playlist_name, interaction)

            await interaction.followup.send(
                "Select a song to remove:",
                view=view,
                ephemeral=True,
            )

        except Exception as e:
            await interaction.followup.send(
                f"Failed to remove track from playlist: {e}", ephemeral=True
            )
            return

    @song_remove.autocomplete("playlist_name")
    async def song_remove_autocomplete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(
            interaction, playlist_name, interaction.user.id
        )

    @playlist_song.command(
        name="clear", description="Clears the playlist of all songs."
    )
    async def song_clear(self, interaction: discord.Interaction, playlist_name: str):
        await interaction.response.defer(ephemeral=True)

        try:
            playlist = await self.database.playlist.get_by_name_owner_id(
                playlist_name, interaction.user.id
            )

            if not playlist:
                await interaction.followup.send(
                    f"Playlist '{playlist_name}' not found", ephemeral=True
                )
                return

            await self.database.track.delete_by_playlist_id(playlist.get("playlist_id"))

            await interaction.followup.send(
                f"Playlist '{playlist_name}' cleared", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to clear playlist: {e}", ephemeral=True
            )
            return

    @song_clear.autocomplete("playlist_name")
    async def song_clear_autocomplete(
        self, interaction: discord.Interaction, playlist_name: str
    ) -> List[app_commands.Choice[str]]:
        return await self._autocomplete_playlist(interaction, playlist_name)

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
        elif isinstance(error, wavelink.exceptions.InvalidNodeException):
            message = "Unable to find connected Nodes"
        else:
            message = f"Error: {error}"

        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Music(bot))
