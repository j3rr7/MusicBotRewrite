import duckdb
import asyncio
import datetime
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

    async def insert(
        self,
        table_name: str,
        data: List[Dict],
        mode: str = "normal",
        conflict_columns: Optional[List[str]] = None,
    ):
        """
        Inserts data into a table with optional IGNORE/REPLACE modes or ON CONFLICT resolution.

        Args:
            table_name: Name of the target table
            data: List of dictionaries containing row data
            mode: 'normal', 'ignore', 'replace', or 'upsert'
            conflict_columns: List of column names to use as conflict target (required for upsert mode)
        """
        if not data:
            return

        columns = list(data[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        columns_str = ", ".join(columns)
        if mode.lower() == "upsert":
            if not conflict_columns:
                raise ValueError(
                    "conflict_columns must be specified when using upsert mode"
                )

            # Create the ON CONFLICT clause
            conflict_target = ", ".join(conflict_columns)

            # Create the SET clause for updating all columns except the conflict columns
            update_columns = [col for col in columns if col not in conflict_columns]
            set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)

            query = f"""
                INSERT INTO {table_name} ({columns_str}) 
                VALUES ({placeholders})
                ON CONFLICT ({conflict_target}) DO UPDATE SET {set_clause}
            """
        else:
            insert_type = {
                "normal": "INSERT",
                "ignore": "INSERT OR IGNORE",
                "replace": "INSERT OR REPLACE",
            }.get(mode.lower(), "INSERT")

            query = f"{insert_type} INTO {table_name} ({columns_str}) VALUES ({placeholders})"

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

    # async def update(
    #     self,
    #     table_name: str,
    #     data: Dict,
    #     where_clause: str,
    #     where_params: Optional[tuple] = None,
    #     exclude_keys: Optional[List[str]] = None,
    # ):
    #     """Updates data in a table, optionally excluding specific keys."""

    #     exclude_keys = exclude_keys or []
    #     filtered_data = {k: v for k, v in data.items() if k not in exclude_keys}

    #     set_clause = ", ".join([f"{key} = ?" for key in filtered_data])
    #     query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause}"
    #     values = tuple(filtered_data.values()) + (where_params or ())

    #     await self.query(query, values)

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
  name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  is_public BOOLEAN DEFAULT false,
  tracks_amount INTEGER DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS issues (
  id UUID PRIMARY KEY DEFAULT uuid(),
  user_id BIGINT,
  issue TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
);
"""
        )
        conn.commit()


async def main():
    await on_setup_tables("database.db")
    await on_setup_tables("test.db")
    db_manager = DatabaseManager("test.db")

if __name__ == "__main__":
    asyncio.run(main())
