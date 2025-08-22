import sqlite3
from datetime import datetime, timezone

DB_PATH = "threads_db.sqlite"  # archivo SQLite nuevo, separado de shelve

def utc_iso_now():
    return datetime.now(tz=timezone.utc).isoformat()

def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = connect()
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS threads (
        wa_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used  TEXT NOT NULL,
        retention_days INTEGER NOT NULL DEFAULT 30
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wa_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (wa_id) REFERENCES threads(wa_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_messages_waid_created ON messages(wa_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON messages(thread_id, created_at);
    """)
    conn.commit()
    conn.close()

def upsert_thread(wa_id: str, thread_id: str, retention_days: int = 30):
    now = utc_iso_now()
    conn, cur = connect(), None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO threads (wa_id, thread_id, created_at, last_used, retention_days)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(wa_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                last_used  = excluded.last_used,
                retention_days = excluded.retention_days
        """, (wa_id, thread_id, now, now, retention_days))
        conn.commit()
    finally:
        conn.close()

def touch_thread(wa_id: str):
    conn = connect(); cur = conn.cursor()
    cur.execute("UPDATE threads SET last_used = ? WHERE wa_id = ?", (utc_iso_now(), wa_id))
    conn.commit(); conn.close()

def insert_message(wa_id: str, thread_id: str, role: str, content: str):
    conn = connect(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (wa_id, thread_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (wa_id, thread_id, role, content, utc_iso_now()))
    conn.commit(); conn.close()

def get_thread_rec(wa_id: str):
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT wa_id, thread_id, created_at, last_used, retention_days
        FROM threads
        WHERE wa_id = ?
        LIMIT 1
    """, (wa_id,))
    row = cur.fetchone()
    conn.close()
    return row
