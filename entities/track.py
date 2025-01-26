import duckdb
import uuid
from typing import Optional, List, Dict, Any


class Track:
    def __init__(self, db_manager: "DatabaseManager"):
        from database import DatabaseManager

        if not isinstance(db_manager, DatabaseManager):
            raise TypeError("db_manager must be an instance of DatabaseManager")
        self.db_manager = db_manager

    async def create(
        self,
        playlist_id: uuid.UUID,
        title: str,
        url: str,
        extra: Optional[Dict[str, Any]] = None,
        track_id: Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """Creates a new track record, returns the track_id."""
        if track_id is None:
            track_id = uuid.uuid4()
        await self.db_manager.query(
            "INSERT INTO track (track_id, playlist_id, title, url, extra) VALUES (?, ?, ?, ?, ?)",
            (track_id, playlist_id, title, url, extra),
        )
        return track_id

    async def get(self, track_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Retrieves a track record by track_id."""
        results = await self.db_manager.query(
            "SELECT * FROM track WHERE track_id = ?", (track_id,)
        )
        if results:
            result = results[0]
            columns = ["track_id", "playlist_id", "title", "url", "extra"]
            return dict(zip(columns, result))
        return None

    async def update(
        self,
        track_id: uuid.UUID,
        title: Optional[str] = None,
        url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Updates a track record by track_id."""
        update_pairs = []
        params = []
        if title is not None:
            update_pairs.append("title = ?")
            params.append(title)
        if url is not None:
            update_pairs.append("url = ?")
            params.append(url)
        if extra is not None:
            update_pairs.append("extra = ?")
            params.append(extra)

        if update_pairs:
            params.append(track_id)
            set_clause = ", ".join(update_pairs)
            sql = f"UPDATE track SET {set_clause} WHERE track_id = ?"
            await self.db_manager.query(sql, tuple(params))

    async def delete(self, track_id: uuid.UUID) -> None:
        """Deletes a track record by track_id."""
        await self.db_manager.query("DELETE FROM track WHERE track_id = ?", (track_id,))

    async def list_by_playlist(self, playlist_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Lists all tracks for a given playlist_id."""
        results = await self.db_manager.query(
            "SELECT * FROM track WHERE playlist_id = ?", (playlist_id,)
        )
        tracks = []
        columns = ["track_id", "playlist_id", "title", "url", "extra"]
        for row in results:
            tracks.append(dict(zip(columns, row)))
        return tracks
