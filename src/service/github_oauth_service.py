import os
import sqlite3
import time

from src.utils.log import logger


class GitHubOAuthTokenStore:
    DB_FILE = "data/data.db"

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            os.makedirs(os.path.dirname(self.DB_FILE), exist_ok=True)
            with sqlite3.connect(self.DB_FILE) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS github_oauth_tokens (
                        repo_full_name TEXT PRIMARY KEY,
                        access_token TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to initialize github_oauth_tokens table: {error}")

    def save_token(self, repo_full_name: str, access_token: str):
        try:
            with sqlite3.connect(self.DB_FILE) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO github_oauth_tokens (repo_full_name, access_token, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (repo_full_name, access_token, int(time.time()))
                )
                conn.commit()
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to save GitHub OAuth token: {error}")

    def get_token(self, repo_full_name: str):
        try:
            with sqlite3.connect(self.DB_FILE) as conn:
                cursor = conn.execute(
                    "SELECT access_token FROM github_oauth_tokens WHERE repo_full_name = ?",
                    (repo_full_name,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.DatabaseError as error:
            logger.error(f"Failed to load GitHub OAuth token: {error}")
            return None
