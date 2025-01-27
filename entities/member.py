import duckdb
from typing import Optional, List, Dict, Any


class Member:
    def __init__(self, db_manager: "DatabaseManager"):
        from database import DatabaseManager

        if not isinstance(db_manager, DatabaseManager):
            raise TypeError("db_manager must be an instance of DatabaseManager")
        self.db_manager = db_manager

    async def create(
        self,
        user_id: int,
        volume: int = 30,
        filters: Optional[str] = None,
        autoplay: str = "disabled",
        loop: str = "normal",
    ) -> None:
        """Creates a new member record."""
        await self.db_manager.query(
            "INSERT INTO member (user_id, volume, filters, autoplay, loop) VALUES (?, ?, ?, ?, ?)",
            (user_id, volume, filters, autoplay, loop),
        )

    async def get(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a member record by user_id."""
        results = await self.db_manager.query(
            "SELECT * FROM member WHERE user_id = ?", (user_id,)
        )
        if results:
            result = results[0]
            columns = ["user_id", "volume", "filters", "autoplay", "loop"]
            return dict(zip(columns, result))
        return

    async def update(
        self,
        user_id: int,
        volume: Optional[int] = None,
        filters: Optional[str] = None,
        autoplay: Optional[str] = None,
        loop: Optional[str] = None,
    ) -> None:
        """Updates a member record by user_id."""
        update_pairs = []
        params = []
        if volume is not None:
            update_pairs.append("volume = ?")
            params.append(volume)
        if filters is not None:
            update_pairs.append("filters = ?")
            params.append(filters)
        if autoplay is not None:
            update_pairs.append("autoplay = ?")
            params.append(autoplay)
        if loop is not None:
            update_pairs.append("loop = ?")
            params.append(loop)

        if update_pairs:
            params.append(user_id)
            set_clause = ", ".join(update_pairs)
            sql = f"UPDATE member SET {set_clause} WHERE user_id = ?"
            await self.db_manager.query(sql, tuple(params))

    async def delete(self, user_id: int) -> None:
        """Deletes a member record by user_id."""
        await self.db_manager.query("DELETE FROM member WHERE user_id = ?", (user_id,))
