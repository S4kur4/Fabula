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
    temporary_password_expires_at INTEGER
        CHECK (temporary_password_expires_at IS NULL OR temporary_password_expires_at >= 0),
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
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published')),
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (user_id, name),
    UNIQUE (id, user_id)
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    album_id INTEGER,
    album_position INTEGER CHECK (album_position IS NULL OR album_position >= 0),
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

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS photo_revisions (
    user_id INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media_cleanup_queue (
    storage_name TEXT NOT NULL,
    media_kind TEXT NOT NULL CHECK (media_kind IN ('photo', 'site')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (storage_name, media_kind)
);

CREATE INDEX IF NOT EXISTS idx_albums_user ON albums(user_id);
CREATE INDEX IF NOT EXISTS idx_photos_user_created ON photos(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_photos_album ON photos(album_id);
CREATE INDEX IF NOT EXISTS idx_photos_status_created ON photos(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_fingerprint_time
    ON login_attempts(fingerprint, attempted_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);

CREATE TRIGGER IF NOT EXISTS photos_revision_after_insert
AFTER INSERT ON photos
BEGIN
    INSERT INTO photo_revisions (user_id, revision)
    VALUES (NEW.user_id, 1)
    ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1;
END;

CREATE TRIGGER IF NOT EXISTS photos_revision_after_update
AFTER UPDATE ON photos
BEGIN
    INSERT INTO photo_revisions (user_id, revision)
    VALUES (NEW.user_id, 1)
    ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1;
END;

CREATE TRIGGER IF NOT EXISTS photos_revision_after_delete
AFTER DELETE ON photos
BEGIN
    INSERT INTO photo_revisions (user_id, revision)
    VALUES (OLD.user_id, 1)
    ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1;
END;
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


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _migration_user_locale(connection: sqlite3.Connection) -> None:
    if "locale" in _column_names(connection, "users"):
        return
    connection.execute(
        """
        ALTER TABLE users
        ADD COLUMN locale TEXT NOT NULL DEFAULT 'zh-CN'
            CHECK (locale IN ('zh-CN', 'en'))
        """
    )


def _migration_album_position(connection: sqlite3.Connection) -> None:
    if "album_position" not in _column_names(connection, "photos"):
        connection.execute(
            """
            ALTER TABLE photos
            ADD COLUMN album_position INTEGER
                CHECK (album_position IS NULL OR album_position >= 0)
            """
        )
        rows = connection.execute(
            """
            SELECT id, album_id
            FROM photos
            WHERE album_id IS NOT NULL
            ORDER BY album_id, created_at DESC, id DESC
            """
        ).fetchall()
        positions: dict[int, int] = {}
        for row in rows:
            position = positions.get(row["album_id"], 0)
            connection.execute(
                "UPDATE photos SET album_position = ? WHERE id = ?",
                (position, row["id"]),
            )
            positions[row["album_id"]] = position + 1
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_photos_album_position
        ON photos(album_id, album_position, id)
        """
    )


def _migration_temporary_password_expiry(connection: sqlite3.Connection) -> None:
    if "temporary_password_expires_at" in _column_names(connection, "users"):
        return
    connection.execute(
        """
        ALTER TABLE users
        ADD COLUMN temporary_password_expires_at INTEGER
            CHECK (temporary_password_expires_at IS NULL OR temporary_password_expires_at >= 0)
        """
    )


def _migration_revision_and_cleanup_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO photo_revisions (user_id, revision)
        SELECT user_id, COUNT(*)
        FROM photos
        GROUP BY user_id
        ON CONFLICT(user_id) DO NOTHING
        """
    )


def _migration_album_publication(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "albums")
    migrated_existing_albums = "status" not in columns
    if migrated_existing_albums:
        connection.execute(
            """
            ALTER TABLE albums
            ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published'))
            """
        )
    if "published_at" not in columns:
        connection.execute("ALTER TABLE albums ADD COLUMN published_at TEXT")
    if migrated_existing_albums:
        connection.execute(
            """
            UPDATE albums
            SET status = 'published', published_at = COALESCE(updated_at, created_at)
            """
        )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_albums_status_created
        ON albums(status, created_at, id)
        """
    )


MIGRATIONS = (
    (1, _migration_user_locale),
    (2, _migration_album_position),
    (3, _migration_temporary_password_expiry),
    (4, _migration_revision_and_cleanup_tables),
    (5, _migration_album_publication),
)


def _apply_migrations(connection: sqlite3.Connection) -> None:
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, migration in MIGRATIONS:
        if version in applied:
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def init_db() -> None:
    connection = get_db()
    connection.executescript(SCHEMA)
    _apply_migrations(connection)


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
