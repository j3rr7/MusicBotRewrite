import duckdb
from typing import Optional, List, Dict, Any


class Guild:
    def __init__(self, db_manager: "DatabaseManager"):
        from database import DatabaseManager

        if not isinstance(db_manager, DatabaseManager):
            raise TypeError("db_manager must be an instance of DatabaseManager")
        self.db_manager = db_manager

    async def create(
        self,
        guild_id: int,
        twenty_four_online: bool = False,
        music_channel_id: Optional[int] = None,
    ) -> None:
        """Create a new guild record."""
        await self.db_manager.query(
            "INSERT INTO guild (guild_id, twenty_four_online, music_channel_id) VALUES (?, ?, ?)",
            (
                guild_id,
                twenty_four_online,
                music_channel_id,
            ),
        )

    async def create_or_ignore(
        self,
        guild_id: int,
        twenty_four_online: bool = False,
        music_channel_id: Optional[int] = None,
    ) -> None:
        """Create a new guild record, ignoring if it already exists."""
        await self.db_manager.query(
            "INSERT OR IGNORE INTO guild (guild_id, twenty_four_online, music_channel_id) VALUES (?, ?, ?)",
            (
                guild_id,
                twenty_four_online,
                music_channel_id,
            ),
        )

    async def get(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a guild record by guild_id."""

        results = await self.db_manager.query(
            "SELECT * FROM guild WHERE guild_id = ?", (guild_id,)
        )

        if results:
            result = results[0]
            columns = ["guild_id", "twenty_four_online", "music_channel_id"]
            return dict(zip(columns, result))

        return None

    async def update(
        self,
        guild_id: int,
        twenty_four_online: Optional[bool] = None,
        music_channel_id: Optional[int] = None,
    ) -> None:
        """Updates a guild record by guild_id."""

        update_pairs = []
        params = []

        if twenty_four_online is not None:
            update_pairs.append("twenty_four_online = ?")
            params.append(twenty_four_online)

        if music_channel_id is not None:
            update_pairs.append("music_channel_id = ?")
            params.append(music_channel_id)

        if update_pairs:
            params.append(guild_id)
            set_clause = ", ".join(update_pairs)
            sql = f"UPDATE guild SET {set_clause} WHERE guild_id = ?"
            await self.db_manager.query(sql, tuple(params))

    async def delete(self, guild_id: int) -> None:
        """Deletes a guild record by guild_id."""
        await self.db_manager.query("DELETE FROM guild WHERE guild_id = ?", (guild_id,))
