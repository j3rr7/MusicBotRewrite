import duckdb
import uuid
from typing import Optional, List, Dict, Any


class Playlist:
    def __init__(self, db_manager: "DatabaseManager"):
        from database import DatabaseManager

        if not isinstance(db_manager, DatabaseManager):
            raise TypeError("db_manager must be an instance of DatabaseManager")
        self.db_manager = db_manager

    async def create(
        self,
        user_id: int,
        name: str,
        description: Optional[str] = None,
        public: bool = True,
        locked: bool = False,
        playlist_id: Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """Creates a new playlist record, returns the playlist_id."""
        if playlist_id is None:
            playlist_id = uuid.uuid4()
        await self.db_manager.query(
            "INSERT INTO playlist (playlist_id, user_id, name, description, public, locked) VALUES (?, ?, ?, ?, ?, ?)",
            (playlist_id, user_id, name, description, public, locked),
        )
        return playlist_id

    async def get(self, playlist_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Retrieves a playlist record by playlist_id."""
        results = await self.db_manager.query(
            "SELECT * FROM playlist WHERE playlist_id = ?", (playlist_id,)
        )
        if results:
            result = results[0]
            columns = [
                "playlist_id",
                "user_id",
                "name",
                "description",
                "public",
                "locked",
            ]
            return dict(zip(columns, result))
        return None

    async def update(
        self,
        playlist_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        public: Optional[bool] = None,
        locked: Optional[bool] = None,
    ) -> None:
        """Updates a playlist record by playlist_id."""
        update_pairs = []
        params = []
        if name is not None:
            update_pairs.append("name = ?")
            params.append(name)
        if description is not None:
            update_pairs.append("description = ?")
            params.append(description)
        if public is not None:
            update_pairs.append("public = ?")
            params.append(public)
        if locked is not None:
            update_pairs.append("locked = ?")
            params.append(locked)

        if update_pairs:
            params.append(playlist_id)
            set_clause = ", ".join(update_pairs)
            sql = f"UPDATE playlist SET {set_clause} WHERE playlist_id = ?"
            await self.db_manager.query(sql, tuple(params))

    async def delete(self, playlist_id: uuid.UUID) -> None:
        """Deletes a playlist record by playlist_id."""
        await self.db_manager.query(
            "DELETE FROM playlist WHERE playlist_id = ?", (playlist_id,)
        )

    async def list_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Lists all playlists for a given user_id."""
        results = await self.db_manager.query(
            "SELECT * FROM playlist WHERE user_id = ?", (user_id,)
        )
        playlists = []
        columns = ["playlist_id", "user_id", "name", "description", "public", "locked"]
        for row in results:
            playlists.append(dict(zip(columns, row)))
        return playlists
