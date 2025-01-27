import traceback
import discord
import logging
import json
import base64
import zlib
import uuid
from discord import ui
from database import DatabaseManager
from typing import Optional, Any


class ImportPlaylistModal(ui.Modal):
    """
    Modal for importing playlists into the bot.

    Allows users to paste exported playlist data to import a playlist.
    """

    playlist_name_input = ui.TextInput(
        label="Playlist Name",
        style=discord.TextStyle.short,
        placeholder="Enter playlist name",
        required=True,
    )
    playlist_data_input = ui.TextInput(
        label="Playlist Exported Data",
        style=discord.TextStyle.paragraph,
        placeholder="Paste your exported playlist data here",
        required=True,
    )

    def __init__(
        self,
        interaction: discord.Interaction,
        database: DatabaseManager,
        initial_playlist_name: Optional[str] = None,
    ):
        """
        Initializes the ImportPlaylistModal.

        Args:
            interaction: The discord.Interaction that triggered the modal.
            database: The DatabaseManager instance.
            initial_playlist_name: An optional initial playlist name to pre-fill.
        """
        super().__init__(title="Import Playlist", timeout=120)
        self.logger = logging.getLogger(__name__)
        self.interaction = interaction
        self.database = database

        if initial_playlist_name:
            self.playlist_name_input.default = initial_playlist_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Checks if the interaction is from the user who invoked the modal.
        """
        return interaction.user.id == self.interaction.user.id

    async def on_timeout(self) -> None:
        """
        Handles modal timeout. Disables all input fields and deletes the original response.
        """
        for item in self.children:
            if isinstance(item, ui.TextInput):
                item.disabled = True

        if self.interaction:
            try:
                await self.interaction.delete_original_response()
            except discord.NotFound:
                self.logger.debug(
                    "Original interaction response not found during timeout."
                )
            except Exception as e:
                self.logger.error(
                    f"Error deleting original response: {e}\n{traceback.format_exc()}"
                )

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """
        Handles errors that occur during modal interaction.
        Logs the error and sends an ephemeral error message to the user.
        """
        self.logger.error(f"Modal error: {error}", exc_info=True)
        error_message = f"An error occurred during playlist import: `{error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(error_message, ephemeral=True)
        except discord.errors.NotFound:
            self.logger.warning("Interaction not found when sending error message.")

    async def _validate_inputs(self, interaction: discord.Interaction) -> Optional[str]:
        """
        Validates the user inputs in the modal.

        Returns:
            None if inputs are valid, otherwise an error message string.
        """
        playlist_name = self.playlist_name_input.value.strip()
        playlist_data = self.playlist_data_input.value.strip()

        if not playlist_name or not playlist_data:
            return "Please fill in both Playlist Name and Playlist Data fields."

        if await self.database.playlist.get_by_name_owner_id(
            playlist_name, interaction.user.id
        ):
            return f"Playlist with name `{playlist_name}` already exists."

        return None

    async def _decode_playlist_data(
        self, interaction: discord.Interaction
    ) -> Optional[dict]:
        """
        Decodes and decompresses the playlist data from base64 and zlib.

        Returns:
            A dictionary representing the playlist data if successful, otherwise None.
        """
        playlist_data_str = self.playlist_data_input.value.strip()
        try:
            compressed_data = base64.urlsafe_b64decode(playlist_data_str)
            json_data = zlib.decompress(compressed_data).decode("utf-8")
            tracks_obj = json.loads(json_data)
            return tracks_obj
        except Exception as e:
            self.logger.error(f"Error decoding playlist data: {e}", exc_info=True)
            await interaction.followup.send(
                "Unable to decode playlist data. Please ensure it is valid.",
                ephemeral=True,
            )
            return None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Handles modal submission. Validates inputs, decodes data, and imports the playlist.
        """
        await interaction.response.defer(ephemeral=True)
        playlist_name = self.playlist_name_input.value.strip()

        validation_error = await self._validate_inputs(interaction)
        if validation_error:
            await interaction.followup.send(validation_error, ephemeral=True)
            return

        tracks_obj = await self._decode_playlist_data(interaction)
        if tracks_obj is None:
            return

        try:
            songs = tracks_obj.get("songs", [])
            playlist_name = tracks_obj.get("playlist_name", "Unknown")
            # playlist_owner = int(tracks_obj.get("playlist_owner", -1))

            self.logger.debug(f"Decoded data: {songs}, playlist_name: {playlist_name}")

            playlist_id = uuid.uuid4()

            await self.database.playlist.create(
                interaction.user.id, playlist_name, playlist_id=playlist_id
            )

            for song in songs:
                await self.database.track.create(
                    playlist_id,
                    song.get("title", "Unknown"),
                    song.get("url", "Unknown"),
                )

            await interaction.followup.send(
                f"Imported playlist `{playlist_name}` with {len(songs)} tracks. (Import logic not fully implemented yet!)",
                ephemeral=True,
            )
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            error_message = (
                "An unexpected error occurred during playlist import. Please report this.\n"
                f"Error details:\n```py\n{tb}\n```"
            )
            self.logger.error(
                f"Unexpected error during playlist import: {e}", exc_info=True
            )
            await interaction.followup.send(error_message, ephemeral=True)
        finally:
            self.stop()
