import json
import re
import asyncio
import wavelink
import logging
import discord
import traceback
import datetime
from database import DatabaseManager
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional, List
from views.queue import QueueView
from views.playlist import PlaylistListView, PlaylistTrackView
from config import ADMIN_IDS


class Music(commands.Cog):
    playlist_group = app_commands.Group(
        name="playlist", description="Playlist commands", guild_only=True
    )
    playlist_song = app_commands.Group(
        name="song", description="Song commands", guild_only=True
    )

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.nodes = []

        # check if self.bot has attr database
        if hasattr(self.bot, "database"):
            self.database: DatabaseManager = self.bot.database

    async def cog_load(self):
        self.logger.info("Music cog loaded")
        asyncio.create_task(self.setup_lavalink())

    async def cog_unload(self):
        self.logger.info("Music cog unloaded")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        self.logger.info(
            f"Wavelink Node connected: {payload.node} | Resumed: {payload.resumed}"
        )

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        self.logger.debug(
            f"Player {player} is inactive for {player.inactive_timeout} seconds"
        )
        # await player.channel.send(f"The player has been inactive for `{player.inactive_timeout}` seconds. Goodbye!")
        await player.disconnect()

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        self.logger.debug(f"Track {payload.track} started")

        player: wavelink.Player | None = payload.player
        if not player:
            return

        original: wavelink.Playable | None = payload.original
        track: wavelink.Playable = payload.track

        self.logger.debug(f"Original: {original} | Track: {track}")

    async def setup_lavalink(self):
        await self.bot.wait_until_ready()
        self.logger.info("Setting up lavalink")

        try:
            # close and terminate all connection
            await wavelink.node.Pool.close()

            self.nodes.append(
                wavelink.Node(
                    uri="http://localhost:2333",
                    identifier="Local Lavalink",
                    password="youshallnotpass",
                )
            )

            # add some public nodes
            # self.nodes.append(
            #     wavelink.Node(
            #         uri="https://lavalink.alfari.id:443",
            #         identifier="Catfein DE",
            #         password="catfein",
            #     )
            # )
            # self.nodes.append(
            #     wavelink.Node(
            #         uri="https://lava-v4.ajieblogs.eu.org:443",
            #         identifier="Public Lavalink v4",
            #         password="https://dsc.gg/ajidevserver",
            #     )
            # )

            await wavelink.node.Pool.connect(
                nodes=self.nodes, client=self.bot, cache_capacity=100
            )
        except Exception as e:
            self.logger.error(f"Error setting up lavalink: {e}")
            raise e

    async def send_interaction_message(
        interaction: discord.Interaction,
        content: str,
        as_ephemeral: Optional[bool] = False,
    ):
        """Use this if unsure whether the interaction is deferred or not."""
        try:
            await interaction.response.send_message(content, ephemeral=as_ephemeral)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(content, ephemeral=as_ephemeral)

    async def try_connect_voice(
        self, interaction: discord.Interaction, is_ephemeral: Optional[bool] = False
    ) -> Optional[wavelink.Player]:
        """Attempts to connect to the voice channel the user is in."""
        try:
            if not interaction.user.voice or not interaction.user.voice.channel:
                self.logger.warning(
                    f"User {interaction.user} is not in a voice channel."
                )
                await self.send_interaction_message(
                    interaction,
                    "You are not in a voice channel.",
                    as_ephemeral=is_ephemeral,
                )
                return

            player = await interaction.user.voice.channel.connect(
                self_deaf=True, cls=wavelink.Player
            )
            return player

        except discord.ClientException as e:
            self.logger.warning(f"Unable to join voice channel: {e}")
            await self.send_interaction_message(
                interaction, "Unable to join voice channel.", as_ephemeral=is_ephemeral
            )

        except Exception as e:
            self.logger.error(f"Error joining voice channel: {e}")
            await self.send_interaction_message(
                interaction,
                "An error occurred while joining voice channel.",
                as_ephemeral=is_ephemeral,
            )

    def convert_timestamp_to_milliseconds(timestamp: str) -> int:
        """Convert a timestamp string (e.g., '1m30s', '90s') to milliseconds."""
        total_seconds = 0

        # Parse minutes
        minutes_match = re.search(r"(\d+)m", timestamp.lower())
        if minutes_match:
            total_seconds += int(minutes_match.group(1)) * 60

        # Parse seconds
        seconds_match = re.search(r"(\d+)s", timestamp.lower())
        if seconds_match:
            total_seconds += int(seconds_match.group(1))

        if not minutes_match and not seconds_match:
            raise ValueError("Invalid timestamp format")

        return total_seconds * 1000  # Convert to milliseconds

    def format_duration(milliseconds: int) -> str:
        """Format milliseconds into a readable duration string."""
        seconds = milliseconds // 1000
        minutes = seconds // 60
        seconds = seconds % 60

        if minutes > 0:
            return f"{minutes}m{seconds}s"
        return f"{seconds}s"

    def convert_autoplay_mode(self, mode_string) -> Optional[wavelink.AutoPlayMode]:
        """Converts a string to a wavelink.AutoPlayMode enum member (one-liner)."""
        return {
            "partial": wavelink.AutoPlayMode.partial,
            "disabled": wavelink.AutoPlayMode.disabled,
            "enabled": wavelink.AutoPlayMode.enabled,
        }.get(mode_string, None)

    def convert_loop_mode(self, mode_string) -> Optional[wavelink.AutoPlayMode]:
        """Converts a string to a wavelink.AutoPlayMode enum member (one-liner)."""
        return {
            "normal": wavelink.QueueMode.normal,
            "loop": wavelink.QueueMode.loop,
            "loopall": wavelink.QueueMode.loop_all,
        }.get(mode_string, None)

    @app_commands.command(
        name="play", description="Play a song given a URL or a search query."
    )
    @app_commands.guild_only()
    @app_commands.describe(query="The query to play.")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            player = await self.try_connect_voice(interaction)

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
                f"{interaction.user.mention} - Unable to find track.", ephemeral=True
            )
            return

        if isinstance(tracks, wavelink.Playlist):
            added: int = await player.queue.put_wait(tracks)
            # await self.send_interaction_message(f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue.")
            embed = discord.Embed(
                title="Playlist Added",
                description=f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue.",
                color=discord.Color.yellow(),
                timestamp=discord.utils.utcnow(),
            )
            if tracks.artwork:
                embed.set_thumbnail(url=tracks.artwork)
            await interaction.followup.send(embed=embed)
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)
            # await self.send_interaction_message("Added the track to the queue.")
            embed = discord.Embed(
                title="Track Added",
                description=f"Added **`{track.title}`** to the queue.",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            await interaction.followup.send(embed=embed)

        player.autoplay = autoplay

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

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=True
            )
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

        await interaction.followup.send(
            f"Added **`{track.title}`** to the queue after the current song."
        )

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

        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.followup.send(
                "There is no music playing or player not connected", ephemeral=True
            )
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

        await interaction.followup.send(
            f"Added **`{track.title}`** to the queue after the current song."
        )

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

        if not player:
            await interaction.response.send_message(
                "Queue is already empty.", ephemeral=True
            )
            return

        if not player.queue.is_empty:
            player.queue.reset()

        await player.stop(force=True)
        await player.disconnect()
        await interaction.response.send_message("Stopped the player.", ephemeral=True)

    @app_commands.command(name="skip", description="Skips the current song.")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        await player.skip(force=True)
        await interaction.response.send_message(
            "⏩ Skipping current song", ephemeral=True
        )

    @app_commands.command(name="pause", description="Pauses the player.")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        await player.pause(True)
        await interaction.response.send_message("⏸️ Pausing the player", ephemeral=True)

    @app_commands.command(name="resume", description="Resumes the player.")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        await player.pause(False)
        await interaction.response.send_message("▶️ Resuming the player", ephemeral=True)

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
        await interaction.response.send_message(
            "🔀 Shuffling the queue", ephemeral=True
        )

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
        await interaction.response.send_message(
            f"Loop set to `{state}`", ephemeral=True
        )

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
        await interaction.response.send_message(
            f"Volume changed to `{volume}`", ephemeral=True
        )

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
        await interaction.response.send_message(
            f"Autoplay changed to `{state.name}`", ephemeral=True
        )

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
        await interaction.response.send_message(
            "Disconnected from voice channel", ephemeral=True
        )

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
                "playlist_id = ?", (playlist[0],),
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

    @playlist_group.command(name="export", description="Exports a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        extension="The extension of the file.",
    )
    async def playlist_export(
        self, interaction: discord.Interaction, playlist_name: str, extension: str
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

            await interaction.followup.send(f"not implemented yet")
        except Exception as e:
            await interaction.followup.send(
                f"Failed to export playlist: {e}", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Playlist '{playlist_name}' shared", ephemeral=True
        )

    @playlist_group.command(name="import", description="Imports a playlist.")
    async def playlist_import(
        self, interaction: discord.Interaction, playlist_name: str = "Imported Playlist"
    ):
        await interaction.response.defer(ephemeral=True)

        # if interaction.message.attachments:
        # TODO: implement this

        await interaction.followup.send("not implemented yet", ephemeral=True)

    # TODO: implement this
    @playlist_group.command(name="play", description="Plays a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.", member="playlist owner"
    )
    async def playlist_play(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        member: discord.Member = None,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            player: wavelink.Player = interaction.guild.voice_client

            if not player:
                player = await self.try_connect_voice(interaction)

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

            if not player.playing:
                await player.play(player.queue.get(), volume=volume)

            await interaction.followup.send(
                f"Playing playlist '{playlist_name}'", ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"Failed to play playlist: {e}", ephemeral=True
            )

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

        # TODO: append current playing track to playlist

        for i, track in enumerate(player.queue):
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
            f"Current queue inserted into playlist '{playlist_name}'", ephemeral=True
        )

    @playlist_song.command(
        name="add",
        description="Adds a track to a playlist using either track URL or title",
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
                max_position = await self.database.query(
                    "SELECT MAX(position) FROM tracks WHERE playlist_id = ?",
                    (playlist[0],),
                )[0]
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

    @playlist_song.command(
        name="remove", description="Removes a track from a playlist."
    )
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        index="The index of the track in the playlist.",
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

    @playlist_song.command(name="move", description="Moves a track in a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        index="The index of the track in the playlist.",
        mode="The mode to move the track in the playlist.",
        target="The target index of the track in the playlist.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="before", value="before"),
            app_commands.Choice(name="after", value="after"),
        ]
    )
    async def song_move(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        index: int,
        target: int,
        mode: str = "before",
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
            if mode == "before":
                await self.database.query(
                    "UPDATE tracks SET position = position - 1 WHERE playlist_id = ? AND position > ?",
                    (playlist[0], index),
                )
            elif mode == "after":
                await self.database.query(
                    "UPDATE tracks SET position = position + 1 WHERE playlist_id = ? AND position >= ?",
                    (playlist[0], target),
                )
            else:
                await interaction.followup.send("Invalid mode", ephemeral=True)
                return

            # move track
            await self.database.update(
                "tracks",
                {"position": target},
                "playlist_id = ? AND position = ?",
                (playlist[0], index),
            )

            await interaction.followup.send(
                f"Song moved in playlist '{playlist_name}' from index {index} to index {target}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to move track: {e}", ephemeral=True
            )
            return

    @playlist_song.command(
        name="clear", description="Clears the playlist of all tracks."
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

    @playlist_song.command(name="shuffle", description="Shuffles the playlist.")
    @app_commands.describe(playlist_name="The name of the playlist.")
    async def song_shuffle(self, interaction: discord.Interaction, playlist_name: str):
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

            # shuffle playlist, but make sure positions are correct
            await self.database.query("")

            await interaction.followup.send(
                f"Playlist '{playlist_name}' shuffled", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
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
