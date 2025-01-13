import json
import asyncio
import wavelink
import logging
import discord
import traceback
from database import DatabaseManager
from discord import app_commands
from discord.ext import commands
from typing import Optional
from views.queue import QueueView
from config import ADMIN_IDS


class Music(commands.Cog):
    playlist_group = app_commands.Group(
        name="playlist", description="Playlist commands", guild_only=True
    )

    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.nodes = []

        # check if self.bot has attr database
        if not hasattr(self.bot, "database"):
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

            # self.nodes.clear()
            # this default should be enough
            # TODO: maybe remove this
            # self.nodes.append(
            #     wavelink.Node(
            #         uri="http://localhost:2333",
            #         identifier="Local Lavalink",
            #         password="youshallnotpass",
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
        ephemeral: Optional[bool] = False,
    ):
        """Use this if unsure whether the interaction is deferred or not."""
        try:
            await interaction.response.send_message(content, ephemeral=ephemeral)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(content, ephemeral=ephemeral)

    async def try_connect_voice(
        self, interaction: discord.Interaction, as_ephemeral: Optional[bool] = False
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
                    ephemeral=as_ephemeral,
                )
                return

            player = await interaction.user.voice.channel.connect(
                self_deaf=True, cls=wavelink.Player
            )
            return player

        except discord.ClientException as e:
            self.logger.warning(f"Unable to join voice channel: {e}")
            await self.send_interaction_message(
                interaction, "Unable to join voice channel.", ephemeral=as_ephemeral
            )

        except Exception as e:
            self.logger.error(f"Error joining voice channel: {e}")
            await self.send_interaction_message(
                interaction,
                "An error occurred while joining voice channel.",
                ephemeral=as_ephemeral,
            )

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

        if not player:
            await interaction.response.send_message(
                "There is no music playing or player not connected", ephemeral=True
            )
            return

        # position in millisecs
        await player.seek()

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
            self.database.update(
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

    @playlist_group.command(name="list", description="List playlists.")
    async def playlist_list(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            playlists = await self.database.get(
                "playlists", "user_id = ?", (interaction.user.id,)
            )
            if not playlists or len(playlists) == 0:
                await interaction.followup.send("You have no playlists", ephemeral=True)
                return

            embed = discord.Embed(
                title="Playlists",
                description="\n".join([f"**{playlist[2]}**" for playlist in playlists]),
                color=discord.Color.green(),
            )

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"Failed to list playlists: {e}", ephemeral=True
            )

    @playlist_group.command(name="create", description="Creates a playlist.")
    @app_commands.describe(name="The name of the playlist.")
    async def playlist_create(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()

        try:
            await self.database.insert(
                "playlists",
                [{"name": name, "user_id": interaction.user.id}],
                mode="replace",
            )
            await interaction.followup.send(
                f"Playlist '{name}' created, use '/playlist add' to add tracks or '/playlist current' to insert current queue into playlist",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to create playlist: {e}", ephemeral=True
            )

    @playlist_group.command(
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

    @playlist_group.command(name="view", description="Views a playlist.")
    @app_commands.describe(playlist_name="The name of the playlist.")
    async def playlist_view(self, interaction: discord.Interaction, playlist_name: str):
        await interaction.response.defer()
        # TODO: implement view playlist
        await interaction.followup.send(
            f"Viewing playlist '{playlist_name}'", ephemeral=True
        )

    @playlist_group.command(name="add", description="Adds a track to a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.", track_url="The URL of the track."
    )
    async def playlist_add(
        self, interaction: discord.Interaction, playlist_name: str, track_url: str
    ):
        await interaction.response.defer()

        # TODO: Implement add track to playlist
        # await self.database.insert(
        #     "tracks",
        #     [{"playlist_id": playlist_name, "url": track_url}],
        #     mode="replace",
        # )

        await interaction.followup.send(
            f"Track added to playlist '{playlist_name}'", ephemeral=True
        )

    @playlist_group.command(name="append", description="Appends a track to a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        track_url="The URL of the track.",
        position="Position to append the track.",
    )
    async def playlist_append(
        self,
        interaction: discord.Interaction,
        playlist_name: str,
        track_url: str,
        position: int,
    ):
        await interaction.response.defer()

        # TODO: Implement append track to playlist
        await interaction.followup.send("Append track to playlist", ephemeral=True)

    @playlist_group.command(
        name="remove", description="Removes a track from a playlist."
    )
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        index="The index of the track in the playlist.",
    )
    async def playlist_remove(
        self, interaction: discord.Interaction, playlist_name: str, index: int
    ):
        await interaction.response.defer()

        # TODO: Implement remove track from playlist

        await interaction.followup.send("Remove track from playlist", ephemeral=True)

    @playlist_group.command(name="rename", description="Renames a playlist.")
    @app_commands.describe(
        playlist_name="The name of the playlist.",
        new_name="The new name of the playlist.",
    )
    async def playlist_rename(
        self, interaction: discord.Interaction, playlist_name: str, new_name: str
    ):
        await interaction.response.defer()

        try:
            await self.database.update(
                "playlists",
                {"name": new_name},
                "name = ? AND user_id = ?",
                (playlist_name, interaction.user.id),
            )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to rename playlist: {e}", ephemeral=True
            )

        await interaction.followup.send(
            f"Playlist '{playlist_name}' renamed to '{new_name}'", ephemeral=True
        )

    # some commands TODO: configure 

    @app_commands.command(name="lavareload", description="Reloads Lavalink nodes")
    @app_commands.describe(lavalink_nodes="json string of lavalink nodes")
    async def lavareload(self, interaction: discord.Interaction, lavalink_nodes: str):
        await interaction.response.defer()

        if interaction.user.id not in ADMIN_IDS:
            await interaction.followup.send(
                "You are not an admin", ephemeral=True
            )
            return

        try:
            lavalink_nodes_json = json.loads(lavalink_nodes)
            for node in lavalink_nodes_json:
                self.nodes.append(
                    wavelink.Node(
                        uri=node["uri"],
                        identifier=node["identifier"],
                        password=node["password"],
                    )
                )
        except Exception as e:
            await interaction.followup.send(
                f"Failed to parse lavalink nodes: {e}", ephemeral=True
            )

        await self.setup_lavalink()

    @app_commands.command(name="lavaclear", description="Clears lavalink nodes")
    async def lavaclear(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if interaction.user.id not in ADMIN_IDS:
            await interaction.followup.send(
                "You are not an admin", ephemeral=True
            )
            return

        self.nodes.clear()
        await self.setup_lavalink()
        await interaction.followup.send("Lavalink nodes cleared", ephemeral=True)

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
