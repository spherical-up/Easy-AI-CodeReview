import os
import sqlite3
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import pymysql


class DatabaseConnection(ABC):
    """数据库连接抽象基类"""

    @abstractmethod
    def execute(self, query: str, params: Tuple = ()) -> Any:
        """执行SQL语句"""
        pass

    @abstractmethod
    def executemany(self, query: str, params_list: List[Tuple]) -> Any:
        """批量执行SQL语句"""
        pass

    @abstractmethod
    def fetchall(self, query: str, params: Tuple = ()) -> List[Tuple]:
        """查询所有结果"""
        pass

    @abstractmethod
    def fetchone(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """查询单条结果"""
        pass

    @abstractmethod
    def commit(self) -> None:
        """提交事务"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭连接"""
        pass

    @abstractmethod
    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        pass

    @abstractmethod
    def column_exists(self, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        pass

    @abstractmethod
    def get_connection_for_pandas(self) -> Any:
        """获取用于pandas的连接对象"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SQLiteConnection(DatabaseConnection):
    """SQLite数据库连接实现"""

    def __init__(self, db_file: str):
        self.db_file = db_file
        self.conn = None
        self.cursor = None
        self._connect()

    def _connect(self):
        """建立连接"""
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_file) if os.path.dirname(self.db_file) else '.', exist_ok=True)
        self.conn = sqlite3.connect(self.db_file)
        self.cursor = self.conn.cursor()

    def execute(self, query: str, params: Tuple = ()) -> Any:
        """执行SQL语句"""
        return self.cursor.execute(query, params)

    def executemany(self, query: str, params_list: List[Tuple]) -> Any:
        """批量执行SQL语句"""
        return self.cursor.executemany(query, params_list)

    def fetchall(self, query: str, params: Tuple = ()) -> List[Tuple]:
        """查询所有结果"""
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetchone(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """查询单条结果"""
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def commit(self) -> None:
        """提交事务"""
        self.conn.commit()

    def close(self) -> None:
        """关闭连接"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        result = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return result is not None

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        try:
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in self.cursor.fetchall()]
            return column_name in columns
        except sqlite3.Error:
            return False

    def get_connection_for_pandas(self) -> Any:
        """获取用于pandas的连接对象"""
        return self.conn


class MySQLConnection(DatabaseConnection):
    """MySQL数据库连接实现"""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.conn = None
        self.cursor = None
        self._connect()

    def _connect(self):
        """建立连接"""
        self.conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.Cursor,
            autocommit=False
        )
        self.cursor = self.conn.cursor()

    def execute(self, query: str, params: Tuple = ()) -> Any:
        """执行SQL语句"""
        # 转换SQLite的?占位符为%s
        query = self._convert_placeholders(query)
        return self.cursor.execute(query, params)

    def executemany(self, query: str, params_list: List[Tuple]) -> Any:
        """批量执行SQL语句"""
        query = self._convert_placeholders(query)
        return self.cursor.executemany(query, params_list)

    def fetchall(self, query: str, params: Tuple = ()) -> List[Tuple]:
        """查询所有结果"""
        query = self._convert_placeholders(query)
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetchone(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """查询单条结果"""
        query = self._convert_placeholders(query)
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def commit(self) -> None:
        """提交事务"""
        self.conn.commit()

    def close(self) -> None:
        """关闭连接"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        result = self.fetchone(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,)
        )
        return result is not None

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        result = self.fetchone(
            """SELECT column_name FROM information_schema.columns 
               WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
            (table_name, column_name)
        )
        return result is not None

    def get_connection_for_pandas(self) -> Any:
        """获取用于pandas的连接对象"""
        return self.conn

    @staticmethod
    def _convert_placeholders(query: str) -> str:
        """将SQLite的?占位符转换为MySQL的%s占位符"""
        # 替换?为%s，但要避免替换字符串中的?
        import re
        # 使用正则表达式替换不在引号内的?
        def replace_question_mark(match):
            # 检查是否在引号内
            before = query[:match.start()]
            # 计算前面单引号和双引号的数量（不考虑转义）
            single_quotes = before.count("'") - before.count("\\'")
            double_quotes = before.count('"') - before.count('\\"')
            # 如果在引号内，不替换
            if single_quotes % 2 == 1 or double_quotes % 2 == 1:
                return '?'
            return '%s'

        return re.sub(r'\?', replace_question_mark, query)


class DatabaseFactory:
    """数据库连接工厂类"""

    DB_TYPE_SQLITE = "sqlite"
    DB_TYPE_MYSQL = "mysql"

    _instance: Optional['DatabaseFactory'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._load_config()
        return cls._instance

    @classmethod
    def _load_config(cls):
        """从环境变量加载配置"""
        cls._config = {
            'db_type': os.getenv('DB_TYPE', cls.DB_TYPE_SQLITE).lower(),
            # SQLite配置
            'sqlite_file': os.getenv('DB_FILE', 'data/data.db'),
            # MySQL配置
            'mysql_host': os.getenv('DB_HOST', 'localhost'),
            'mysql_port': int(os.getenv('DB_PORT', '3306')),
            'mysql_user': os.getenv('DB_USER', 'root'),
            'mysql_password': os.getenv('DB_PASSWORD', ''),
            'mysql_database': os.getenv('DB_NAME', 'code_review'),
        }

    @classmethod
    def get_connection(cls) -> DatabaseConnection:
        """获取数据库连接"""
        config = cls._config

        if config['db_type'] == cls.DB_TYPE_MYSQL:
            return MySQLConnection(
                host=config['mysql_host'],
                port=config['mysql_port'],
                user=config['mysql_user'],
                password=config['mysql_password'],
                database=config['mysql_database']
            )
        else:
            return SQLiteConnection(db_file=config['sqlite_file'])

    @classmethod
    def get_db_type(cls) -> str:
        """获取当前数据库类型"""
        return cls._config.get('db_type', cls.DB_TYPE_SQLITE)

    @classmethod
    def is_mysql(cls) -> bool:
        """判断是否使用MySQL"""
        return cls.get_db_type() == cls.DB_TYPE_MYSQL

    @classmethod
    def is_sqlite(cls) -> bool:
        """判断是否使用SQLite"""
        return cls.get_db_type() == cls.DB_TYPE_SQLITE

    @classmethod
    def reload_config(cls):
        """重新加载配置（用于配置变更后）"""
        cls._load_config()


# 便捷函数
def get_db_connection() -> DatabaseConnection:
    """获取数据库连接"""
    return DatabaseFactory().get_connection()


def get_db_type() -> str:
    """获取数据库类型"""
    return DatabaseFactory().get_db_type()
