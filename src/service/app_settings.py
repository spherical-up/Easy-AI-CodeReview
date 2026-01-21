import os
import sqlite3
import time

from src.utils.log import logger


class AppSettingsStore:
    DB_FILE = "data/data.db"

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            os.makedirs(os.path.dirname(self.DB_FILE), exist_ok=True)
            with sqlite3.connect(self.DB_FILE) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to initialize app_settings table: {error}")

    def get(self, key: str):
        try:
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.execute(
                    "SELECT value FROM app_settings WHERE key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to load setting {key}: {error}")
            return None

    def set(self, key: str, value: str):
        try:
            with sqlite3.connect(self.DB_FILE) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO app_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, int(time.time()))
                )
                conn.commit()
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to save setting {key}: {error}")
