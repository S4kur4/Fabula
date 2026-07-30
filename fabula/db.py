from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'photographer'
        CHECK (role IN ('photographer', 'admin')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'inactive')),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 1
        CHECK (must_change_password IN (0, 1)),
    initial_admin INTEGER NOT NULL DEFAULT 0
        CHECK (initial_admin IN (0, 1)),
    session_version INTEGER NOT NULL DEFAULT 1,
    locale TEXT NOT NULL DEFAULT 'zh-CN'
        CHECK (locale IN ('zh-CN', 'en')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (user_id, name),
    UNIQUE (id, user_id)
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    album_id INTEGER,
    storage_name TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    story TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('processing', 'ready', 'failed')),
    mime_type TEXT NOT NULL DEFAULT 'image/webp',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (album_id, user_id) REFERENCES albums(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS about_blocks (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    title TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    signature TEXT NOT NULL DEFAULT '',
    gear_json TEXT NOT NULL DEFAULT '[]',
    contact_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS site_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    attempted_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_albums_user ON albums(user_id);
CREATE INDEX IF NOT EXISTS idx_photos_user_created ON photos(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_photos_album ON photos(album_id);
CREATE INDEX IF NOT EXISTS idx_photos_status_created ON photos(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_fingerprint_time
    ON login_attempts(fingerprint, attempted_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE_PATH"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    connection = get_db()
    connection.executescript(SCHEMA)
    user_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "locale" not in user_columns:
        connection.execute(
            """
            ALTER TABLE users
            ADD COLUMN locale TEXT NOT NULL DEFAULT 'zh-CN'
                CHECK (locale IN ('zh-CN', 'en'))
            """
        )
    connection.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
