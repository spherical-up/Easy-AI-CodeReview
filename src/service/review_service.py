import pandas as pd

from src.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from src.service.db_factory import get_db_connection, DatabaseFactory


class ReviewService:

    @staticmethod
    def _get_create_table_sql(table_name: str) -> str:
        """获取创建表的SQL语句（兼容MySQL和SQLite）"""
        is_mysql = DatabaseFactory.is_mysql()

        if table_name == "mr_review_log":
            if is_mysql:
                return '''
                    CREATE TABLE IF NOT EXISTS mr_review_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        project_name VARCHAR(255),
                        author VARCHAR(255),
                        source_branch VARCHAR(255),
                        target_branch VARCHAR(255),
                        updated_at BIGINT,
                        commit_messages TEXT,
                        score INT,
                        url TEXT,
                        review_result LONGTEXT,
                        additions INT DEFAULT 0,
                        deletions INT DEFAULT 0,
                        INDEX idx_author (author),
                        INDEX idx_project_name (project_name),
                        INDEX idx_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                '''
            else:
                return '''
                    CREATE TABLE IF NOT EXISTS mr_review_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_name TEXT,
                        author TEXT,
                        source_branch TEXT,
                        target_branch TEXT,
                        updated_at INTEGER,
                        commit_messages TEXT,
                        score INTEGER,
                        url TEXT,
                        review_result TEXT,
                        additions INTEGER DEFAULT 0,
                        deletions INTEGER DEFAULT 0
                    )
                '''
        elif table_name == "push_review_log":
            if is_mysql:
                return '''
                    CREATE TABLE IF NOT EXISTS push_review_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        project_name VARCHAR(255),
                        author VARCHAR(255),
                        branch VARCHAR(255),
                        updated_at BIGINT,
                        commit_messages TEXT,
                        score INT,
                        review_result LONGTEXT,
                        additions INT DEFAULT 0,
                        deletions INT DEFAULT 0,
                        INDEX idx_author (author),
                        INDEX idx_project_name (project_name),
                        INDEX idx_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                '''
            else:
                return '''
                    CREATE TABLE IF NOT EXISTS push_review_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_name TEXT,
                        author TEXT,
                        branch TEXT,
                        updated_at INTEGER,
                        commit_messages TEXT,
                        score INTEGER,
                        review_result TEXT,
                        additions INTEGER DEFAULT 0,
                        deletions INTEGER DEFAULT 0
                    )
                '''
        return ""

    @staticmethod
    def init_db():
        """初始化数据库及表结构"""
        try:
            with get_db_connection() as conn:
                # 创建mr_review_log表
                conn.execute(ReviewService._get_create_table_sql("mr_review_log"))

                # 创建push_review_log表
                conn.execute(ReviewService._get_create_table_sql("push_review_log"))

                # 确保旧版本的表添加additions、deletions列（仅SQLite需要，MySQL在创建时已包含）
                if DatabaseFactory.is_sqlite():
                    tables = ["mr_review_log", "push_review_log"]
                    columns = ["additions", "deletions"]
                    for table in tables:
                        for column in columns:
                            if not conn.column_exists(table, column):
                                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER DEFAULT 0")

                conn.commit()
                print(f"Database initialized successfully using {DatabaseFactory.get_db_type()}")
        except Exception as e:
            print(f"Database initialization failed: {e}")

    @staticmethod
    def insert_mr_review_log(entity: MergeRequestReviewEntity):
        """插入合并请求审核日志"""
        try:
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO mr_review_log (project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result, additions, deletions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (entity.project_name, entity.author, entity.source_branch,
                      entity.target_branch, entity.updated_at, entity.commit_messages,
                      entity.score, entity.url, entity.review_result, entity.additions, entity.deletions))
                conn.commit()
                print(f"[ReviewService] MR review log inserted successfully: {entity.project_name} by {entity.author}")
        except Exception as e:
            import traceback
            print(f"[ReviewService] Error inserting MR review log: {e}")
            print(f"[ReviewService] Traceback: {traceback.format_exc()}")

    @staticmethod
    def get_mr_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                           updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的合并请求审核日志"""
        try:
            with get_db_connection() as conn:
                query = """
                    SELECT project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result, additions, deletions
                    FROM mr_review_log
                    WHERE 1=1
                """
                params = []

                if authors:
                    placeholders = ','.join(['%s'] * len(authors))
                    query += f" AND author IN ({placeholders})"
                    params.extend(authors)

                if project_names:
                    placeholders = ','.join(['%s'] * len(project_names))
                    query += f" AND project_name IN ({placeholders})"
                    params.extend(project_names)

                if updated_at_gte is not None:
                    query += " AND updated_at >= %s"
                    params.append(updated_at_gte)

                if updated_at_lte is not None:
                    query += " AND updated_at <= %s"
                    params.append(updated_at_lte)

                query += " ORDER BY updated_at DESC"

                # 使用pandas读取数据
                pandas_conn = conn.get_connection_for_pandas()
                df = pd.read_sql_query(sql=query, con=pandas_conn, params=params)

                print(df)
                return df
        except Exception as e:
            print(f"Error retrieving review logs: {e}")
            return pd.DataFrame()

    @staticmethod
    def insert_push_review_log(entity: PushReviewEntity):
        """插入推送审核日志"""
        try:
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO push_review_log (project_name, author, branch, updated_at, commit_messages, score, review_result, additions, deletions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (entity.project_name, entity.author, entity.branch,
                      entity.updated_at, entity.commit_messages, entity.score,
                      entity.review_result, entity.additions, entity.deletions))
                conn.commit()
                print(f"[ReviewService] Push review log inserted successfully: {entity.project_name} by {entity.author}")
        except Exception as e:
            import traceback
            print(f"[ReviewService] Error inserting push review log: {e}")
            print(f"[ReviewService] Traceback: {traceback.format_exc()}")

    @staticmethod
    def get_push_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                             updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的推送审核日志"""
        try:
            with get_db_connection() as conn:
                query = """
                    SELECT project_name, author, branch, updated_at, commit_messages, score, review_result, additions, deletions
                    FROM push_review_log
                    WHERE 1=1
                """
                params = []

                if authors:
                    placeholders = ','.join(['?'] * len(authors))
                    query += f" AND author IN ({placeholders})"
                    params.extend(authors)

                if project_names:
                    placeholders = ','.join(['?'] * len(project_names))
                    query += f" AND project_name IN ({placeholders})"
                    params.extend(project_names)

                if updated_at_gte is not None:
                    query += " AND updated_at >= ?"
                    params.append(updated_at_gte)

                if updated_at_lte is not None:
                    query += " AND updated_at <= ?"
                    params.append(updated_at_lte)

                query += " ORDER BY updated_at DESC"

                # 使用pandas读取数据
                pandas_conn = conn.get_connection_for_pandas()
                df = pd.read_sql_query(sql=query, con=pandas_conn, params=params)
                return df
        except Exception as e:
            print(f"Error retrieving push review logs: {e}")
            return pd.DataFrame()


# Initialize database
ReviewService.init_db()
