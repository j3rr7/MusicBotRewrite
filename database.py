import duckdb
import asyncio
from typing import List, Dict, Any, Optional


class DatabaseManager:
    def __init__(self, database_path: str = ":memory:"):
        self.database_path = database_path

    async def query(self, query: str, params: Optional[tuple] = None) -> List[Any]:
        """
        Asynchronously execute a SQL query against the database.

        Args:
            query: The SQL query to execute.
            params: Optional parameters to pass to the query.

        Returns:
            A list of results from the query execution.

        """
        return await asyncio.to_thread(self._execute_query, query, params)

    def _execute_query(self, query: str, params: Optional[tuple] = None) -> List[Any]:
        """Execute a SQL query against the database, and return the results.

        Args:
            query: The SQL query to execute.
            params: Optional parameters to pass to the query.

        Returns:
            A list of results, or an empty list if no results.

        """

        with duckdb.connect(self.database_path) as conn:
            return conn.execute(query, params or ()).fetchall() or []

    async def create_table(self, table_name: str, schema: str):
        """Creates a table."""
        await self.query(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})")

    # async def insert(self, table_name: str, data: List[Dict]):
    #     """Inserts data into a table."""
    #     if not data:
    #         return

    #     columns = ", ".join(data[0].keys())
    #     placeholders = ", ".join(["?"] * len(data[0]))
    #     query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

    #     for row in data:
    #         values = tuple(row.values())
    #         await self.query(query, values)
    async def insert(self, table_name: str, data: List[Dict], mode: str = "normal"):
        """Inserts data into a table with optional IGNORE/REPLACE modes.

        Args:
            table_name: Name of the target table
            data: List of dictionaries containing row data
            mode: 'normal', 'ignore', or 'replace'
        """
        if not data:
            return

        columns = ", ".join(data[0].keys())
        placeholders = ", ".join(["?"] * len(data[0]))

        insert_type = {
            "normal": "INSERT",
            "ignore": "INSERT OR IGNORE",
            "replace": "INSERT OR REPLACE",
        }.get(mode.lower(), "INSERT")

        query = f"{insert_type} INTO {table_name} ({columns}) VALUES ({placeholders})"

        for row in data:
            values = tuple(row.values())
            await self.query(query, values)

    async def update(
        self,
        table_name: str,
        data: Dict,
        where_clause: str,
        where_params: Optional[tuple] = None,
    ):
        """Updates data in a table."""
        set_clause = ", ".join([f"{key} = ?" for key in data])
        query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"
        values = tuple(data.values()) + (where_params or ())
        await self.query(query, values)

    async def delete(
        self, table_name: str, where_clause: str, where_params: Optional[tuple] = None
    ):
        """Deletes data from a table."""
        query = f"DELETE FROM {table_name} WHERE {where_clause}"
        await self.query(query, where_params)

    async def get(
        self,
        table_name: str,
        where_clause: str = "1=1",
        where_params: Optional[tuple] = None,
    ) -> List[Any]:
        """Retrieves data based on a where clause."""
        query = f"SELECT * FROM {table_name} WHERE {where_clause}"
        return await self.query(query, where_params)

    async def get_one(
        self, table_name: str, where_clause: str, where_params: Optional[tuple] = None
    ) -> Optional[Any]:
        """Retrieves a single row based on criteria. Returns None if not found."""
        results = await self.get(table_name, where_clause, where_params)
        return results[0] if results else None

    async def table_exists(self, table_name: str) -> bool:
        """Checks if a table exists."""
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name = ?"  # Use sqlite_master for DuckDB
        result = await self.query(query, (table_name,))
        return bool(result)


async def on_setup_tables(db_name: str = "database.db"):
    with duckdb.connect(db_name) as conn:
        conn.sql(
            """
CREATE TABLE IF NOT EXISTS guilds (
  id BIGINT PRIMARY KEY,
  last_channel_id BIGINT
);
  
CREATE TABLE IF NOT EXISTS members (
  id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id BIGINT PRIMARY KEY,
  volume INTEGER DEFAULT 100,
  filters TEXT DEFAULT '',
  autoplay TEXT DEFAULT 'disabled',
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT volume_range CHECK (volume BETWEEN 0 AND 1000),
  CONSTRAINT autoplay_state CHECK (autoplay IN ('enabled', 'disabled', 'partial')),
);

CREATE TABLE IF NOT EXISTS playlists (
  id UUID PRIMARY KEY DEFAULT uuid(),
  user_id BIGINT,
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  is_public BOOLEAN DEFAULT false,
);

CREATE TABLE IF NOT EXISTS tracks (
  id UUID PRIMARY KEY DEFAULT uuid(),
  playlist_id UUID,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  artist TEXT,
  duration BIGINT,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  position INTEGER,
);
"""
        )
        conn.commit()


async def main():
    await on_setup_tables("database.db")
    await on_setup_tables("test.db")
    db_manager = DatabaseManager("test.db")

    # # Create tests
    # await db_manager.create_table("guilds", "id BIGINT PRIMARY KEY")
    # await db_manager.create_table("members", "id BIGINT PRIMARY KEY")
    # await db_manager.create_table("user_settings", "user_id BIGINT PRIMARY KEY")
    # await db_manager.create_table("playlists", "id UUID PRIMARY KEY")
    # await db_manager.create_table("playlist_items", "id UUID PRIMARY KEY")

    # # Insert test data
    # await db_manager.insert("guilds", [{"id": 1}])
    # await db_manager.insert("members", [{"id": 1}])
    # await db_manager.insert("user_settings", [{"user_id": 1}])

    # # Query tests
    # await db_manager.get("guilds")

    # # Update tests
    # await db_manager.update("guilds", {"id": 2}, "id = ?", (1,))

    # # Delete tests
    # await db_manager.delete("guilds", "id = ?", (2,))

    # # Get one tests
    # await db_manager.get_one("guilds", "id = ?", (1,))

    # # Table exists tests
    # await db_manager.table_exists("guilds")

    # print all tables
    # result = await db_manager.query("SELECT name FROM sqlite_master WHERE type='table'")
    # print(result)

    # result = await db_manager.get_one("user_settings", "user_id = ?", (1,))
    # print(result)
    # if result is None:
    #     await db_manager.insert(
    #         "user_settings", [{"user_id": 1, "volume": 30, "autoplay": "partial"}]
    #     )

    # result = await db_manager.get_one("user_settings", "user_id = ?", (1,))
    # print(result)

    # await db_manager.update("user_settings", {"volume": 50}, "user_id = ?", (1,))

    # result = await db_manager.get_one("user_settings", "user_id = ?", (1,))
    # print(result)

    # await db_manager.insert("playlists", [{"user_id": 1, "name": "test", "is_public": True}], mode="ignore")

    results = await db_manager.get("playlists", "user_id = ?", (1,))
    playlists_name = []
    for result in results:
        playlists_name.append(result[5])
    print(playlists_name)


if __name__ == "__main__":
    asyncio.run(main())
