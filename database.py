# database.py
import sqlite3
import os
import logging
import psycopg2
from urllib.parse import urlparse
from config import DB_NAME

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.conn = None
        self.is_postgres = bool(self.database_url)
        self.placeholder = "%s" if self.is_postgres else "?"
        self.connect()
        self.create_tables()

    def connect(self):
        try:
            if self.is_postgres:
                self.conn = psycopg2.connect(self.database_url, sslmode='require')
                self.conn.autocommit = True
            else:
                self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise e

    def get_cursor(self):
        # Reconnect if connection is closed (esp for Postgres)
        try:
            if self.is_postgres:
                if self.conn.closed:
                    self.connect()
            return self.conn.cursor()
        except:
            self.connect()
            return self.conn.cursor()

    def create_tables(self):
        cursor = self.get_cursor()
        
        # ID Auto-increment syntax difference
        id_type = "SERIAL PRIMARY KEY" if self.is_postgres else "INTEGER PRIMARY KEY"
        
        # Table for selected chats (channels/groups)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                username TEXT,
                chat_type TEXT,
                adder_id BIGINT,
                adder_name TEXT
            )
        ''')
        # Table for indexed files
        # Note: Postgres doesn't support 'OR IGNORE', we use 'ON CONFLICT DO NOTHING'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS files (
                id {id_type},
                file_id TEXT,
                file_name TEXT,
                file_size TEXT,
                file_type TEXT,
                chat_id BIGINT,
                message_id BIGINT,
                UNIQUE(chat_id, message_id)
            )
        ''')
        # Table for bot users
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                username TEXT,
                last_seen TIMESTAMP,
                is_banned INTEGER DEFAULT 0
            )
        ''')

        # Table for general settings (like Google tokens)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Migrations (Handle columns if they don't exist)
        alter_commands = [
            'ALTER TABLE files ADD COLUMN file_size TEXT',
            'ALTER TABLE chats ADD COLUMN chat_type TEXT',
            'ALTER TABLE chats ADD COLUMN username TEXT',
            'ALTER TABLE chats ADD COLUMN adder_id BIGINT',
            'ALTER TABLE chats ADD COLUMN adder_name TEXT',
            'ALTER TABLE users ADD COLUMN last_seen TIMESTAMP',
            'ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0'
        ]
        
        for cmd in alter_commands:
            try:
                cursor.execute(cmd)
                if not self.is_postgres:
                    self.conn.commit()
            except Exception:
                # Column likely exists
                if self.is_postgres:
                    self.conn.rollback() 
                pass

        if not self.is_postgres:
            self.conn.commit()

    def execute_query(self, query, params=(), fetch_one=False, fetch_all=False, commit=False):
        """Helper to execute queries with correct placeholder and error handling."""
        cursor = self.get_cursor()
        try:
            # Replace ? with %s if using Postgres
            if self.is_postgres and "?" in query:
                query = query.replace("?", "%s")
                
            cursor.execute(query, params)
            
            if commit and not self.is_postgres:
                self.conn.commit()
                
            if fetch_one:
                return cursor.fetchone()
            if fetch_all:
                return cursor.fetchall()
            return cursor
        except Exception as e:
            logger.error(f"Query Error: {e} | Query: {query}")
            if self.is_postgres:
                self.conn.rollback()
            return None

    def add_chat(self, chat_id, title, username=None, chat_type=None, adder_id=None, adder_name=None):
        query = 'INSERT INTO chats (chat_id, title, username, chat_type, adder_id, adder_name) VALUES (?, ?, ?, ?, ?, ?)'
        if self.is_postgres:
            query = 'INSERT INTO chats (chat_id, title, username, chat_type, adder_id, adder_name) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, username = EXCLUDED.username, chat_type = EXCLUDED.chat_type, adder_id = EXCLUDED.adder_id, adder_name = EXCLUDED.adder_name'
        else:
             query = 'INSERT OR REPLACE INTO chats (chat_id, title, username, chat_type, adder_id, adder_name) VALUES (?, ?, ?, ?, ?, ?)'
             
        self.execute_query(query, (chat_id, title, username, chat_type, adder_id, adder_name), commit=True)

    def is_chat_selected(self, chat_id):
        res = self.execute_query('SELECT 1 FROM chats WHERE chat_id = ?', (chat_id,), fetch_one=True)
        return res is not None

    def get_all_chats(self):
        rows = self.execute_query('SELECT chat_id FROM chats', fetch_all=True)
        return [row[0] for row in rows] if rows else []

    def get_all_chats_detailed(self):
        """Returns list of (chat_id, title, username, chat_type, adder_id, adder_name)"""
        return self.execute_query('SELECT chat_id, title, username, chat_type, adder_id, adder_name FROM chats', fetch_all=True) or []

    def add_file(self, file_id, file_name, file_size, file_type, chat_id, message_id):
        if self.is_postgres:
            query = '''
                INSERT INTO files (file_id, file_name, file_size, file_type, chat_id, message_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (chat_id, message_id) DO NOTHING
            '''
        else:
            query = '''
                INSERT OR IGNORE INTO files (file_id, file_name, file_size, file_type, chat_id, message_id)
                VALUES (?, ?, ?, ?, ?, ?)
            '''
        self.execute_query(query, (file_id, file_name, file_size, file_type, chat_id, message_id), commit=True)

    def search_files(self, query):
        sql = '''
            SELECT file_id, file_name, file_size, file_type, chat_id, message_id 
            FROM files 
            WHERE file_name LIKE ? 
            LIMIT 50
        '''
        return self.execute_query(sql, (f'%{query}%',), fetch_all=True) or []

    def add_user(self, user_id, name=None, username=None):
        if self.is_postgres:
            query = '''
                INSERT INTO users (user_id, name, username, last_seen) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    username = EXCLUDED.username,
                    last_seen = CURRENT_TIMESTAMP
            '''
        else:
            query = '''
                INSERT INTO users (user_id, name, username, last_seen) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    username = excluded.username,
                    last_seen = CURRENT_TIMESTAMP
            '''
        self.execute_query(query, (user_id, name, username), commit=True)

    def get_all_users(self):
        rows = self.execute_query('SELECT user_id FROM users', fetch_all=True)
        return [row[0] for row in rows] if rows else []

    def increment_search_count(self):
        if self.is_postgres:
            query = "INSERT INTO settings (key, value) VALUES ('total_searches', '1') ON CONFLICT (key) DO UPDATE SET value = (settings.value::int + 1)::text"
        else:
            query = "INSERT OR REPLACE INTO settings (key, value) VALUES ('total_searches', COALESCE((SELECT CAST(value AS INTEGER) FROM settings WHERE key = 'total_searches'), 0) + 1)"
        
        self.execute_query(query, commit=True)

    def get_total_searches(self):
        res = self.get_setting('total_searches', '0')
        try:
            return int(res)
        except:
            return 0

    def get_user_count(self):
        res = self.execute_query('SELECT COUNT(*) FROM users', fetch_one=True)
        return res[0] if res else 0

    def set_ban_status(self, identifier, status):
        """identifier can be user_id (int) or username (str)"""
        if isinstance(identifier, int) or str(identifier).isdigit():
            user_id = int(identifier)
            cursor = self.execute_query('UPDATE users SET is_banned = ? WHERE user_id = ?', (status, user_id), commit=True)
        else:
            username = str(identifier).replace("@", "")
            cursor = self.execute_query('UPDATE users SET is_banned = ? WHERE LOWER(username) = LOWER(?)', (status, username), commit=True)
        
        return cursor.rowcount > 0 if cursor else False

    def is_user_banned(self, user_id):
        res = self.execute_query('SELECT is_banned FROM users WHERE user_id = ?', (user_id,), fetch_one=True)
        return res[0] == 1 if res else False

    def get_user_by_id_or_username(self, identifier):
        if isinstance(identifier, int) or str(identifier).isdigit():
            return self.execute_query('SELECT user_id, name, username FROM users WHERE user_id = ?', (int(identifier),), fetch_one=True)
        else:
            username = str(identifier).replace("@", "")
            return self.execute_query('SELECT user_id, name, username FROM users WHERE LOWER(username) = LOWER(?)', (username,), fetch_one=True)

    def get_monthly_user_count(self):
        # Postgres uses slightly different syntax for date math
        if self.is_postgres:
            query = "SELECT COUNT(*) FROM users WHERE last_seen >= NOW() - INTERVAL '30 days'"
        else:
            query = "SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-30 days')"
            
        res = self.execute_query(query, fetch_one=True)
        return res[0] if res else 0

    def get_chat_stats(self):
        total = self.execute_query("SELECT COUNT(*) FROM chats", fetch_one=True)[0]
        groups = self.execute_query("SELECT COUNT(*) FROM chats WHERE chat_type IN ('group', 'supergroup')", fetch_one=True)[0]
        channels = self.execute_query("SELECT COUNT(*) FROM chats WHERE chat_type = 'channel'", fetch_one=True)[0]
        return total, groups, channels

    def get_file_count(self):
        res = self.execute_query("SELECT COUNT(*) FROM files", fetch_one=True)
        return res[0] if res else 0

    def set_setting(self, key, value):
        if self.is_postgres:
            query = "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        else:
            query = "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
        self.execute_query(query, (key, value), commit=True)

    def get_setting(self, key, default=None):
        res = self.execute_query("SELECT value FROM settings WHERE key = ?", (key,), fetch_one=True)
        return res[0] if res else default

db = Database()
