import sqlite3
import os

DATABASE_PATH = 'gallery.db'

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Create albums table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create photos table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            album_id INTEGER,
            status TEXT NOT NULL DEFAULT 'ready',
            size_bytes INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (album_id) REFERENCES albums (id) ON DELETE SET NULL
        )
    ''')

    # Insert default "All Work" album if not exists
    cursor.execute("SELECT COUNT(*) FROM albums WHERE id = 0")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO albums (id, name) VALUES (0, 'All Work')")

    # Create settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Add missing columns for older databases
    cursor.execute("PRAGMA table_info(photos)")
    photo_columns = {row[1] for row in cursor.fetchall()}
    if "status" not in photo_columns:
        cursor.execute("ALTER TABLE photos ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'")
        cursor.execute("UPDATE photos SET status = 'ready' WHERE status IS NULL")
    if "size_bytes" not in photo_columns:
        cursor.execute("ALTER TABLE photos ADD COLUMN size_bytes INTEGER DEFAULT 0")
        cursor.execute("UPDATE photos SET size_bytes = 0 WHERE size_bytes IS NULL")

    # Indexes for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_photos_album_id ON photos(album_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_photos_created_at ON photos(created_at)")

    conn.commit()
    conn.close()

def get_db_connection():
    """Get a database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key):
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM site_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key, value):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO site_settings (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, value)
    )
    conn.commit()
    conn.close()
    return True

# Album operations
def get_all_albums():
    """Get all albums"""
    conn = get_db_connection()
    albums = conn.execute('SELECT * FROM albums ORDER BY id').fetchall()
    conn.close()
    return [dict(album) for album in albums]

def get_all_albums_with_counts():
    """Get all albums with photo counts in a single query"""
    conn = get_db_connection()
    albums = conn.execute('''
        SELECT a.id, a.name, a.created_at,
               COALESCE(COUNT(p.id), 0) as photo_count
        FROM albums a
        LEFT JOIN photos p ON p.album_id = a.id
        GROUP BY a.id
        ORDER BY a.id
    ''').fetchall()
    conn.close()
    return [dict(album) for album in albums]

def create_album(name):
    """Create a new album"""
    conn = get_db_connection()
    try:
        cursor = conn.execute('INSERT INTO albums (name) VALUES (?)', (name,))
        album_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return album_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def update_album(album_id, name):
    """Update album name"""
    conn = get_db_connection()
    try:
        conn.execute('UPDATE albums SET name = ? WHERE id = ?', (name, album_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def delete_album(album_id):
    """Delete an album (photos will have album_id set to NULL)"""
    if album_id == 0:  # Cannot delete "All Work"
        return False
    conn = get_db_connection()
    conn.execute('DELETE FROM albums WHERE id = ?', (album_id,))
    conn.commit()
    conn.close()
    return True

# Photo operations
def get_all_photos():
    """Get all photos with album info"""
    conn = get_db_connection()
    photos = conn.execute('''
        SELECT p.*, a.name as album_name
        FROM photos p
        LEFT JOIN albums a ON p.album_id = a.id
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()
    return [dict(photo) for photo in photos]

def get_photos_by_album(album_id):
    """Get photos by album ID"""
    conn = get_db_connection()
    if album_id == 0:  # "All Work" - return all photos
        photos = conn.execute('SELECT * FROM photos ORDER BY created_at DESC').fetchall()
    else:
        photos = conn.execute('SELECT * FROM photos WHERE album_id = ? ORDER BY created_at DESC', (album_id,)).fetchall()
    conn.close()
    return [dict(photo) for photo in photos]

def get_photos_paged(album_id=None, limit=20, offset=0, include_processing=False, include_album=False):
    """Get photos with pagination"""
    conn = get_db_connection()
    params = []
    where_clauses = []

    if album_id is not None and album_id != 0:
        where_clauses.append("p.album_id = ?")
        params.append(album_id)

    if not include_processing:
        where_clauses.append("p.status = 'ready'")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    select_fields = "p.*"
    join_sql = ""
    if include_album:
        select_fields = "p.*, a.name as album_name"
        join_sql = "LEFT JOIN albums a ON p.album_id = a.id"

    query = f'''
        SELECT {select_fields}
        FROM photos p
        {join_sql}
        {where_sql}
        ORDER BY p.created_at DESC
        LIMIT ? OFFSET ?
    '''
    params.extend([limit, offset])
    photos = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(photo) for photo in photos]

def get_photo_count(album_id=None, include_processing=False):
    """Get photo count for pagination"""
    conn = get_db_connection()
    params = []
    where_clauses = []

    if album_id is not None and album_id != 0:
        where_clauses.append("album_id = ?")
        params.append(album_id)

    if not include_processing:
        where_clauses.append("status = 'ready'")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    count = conn.execute(f'SELECT COUNT(*) FROM photos {where_sql}', params).fetchone()[0]
    conn.close()
    return count

def add_photo(filename, album_id=None, status='ready'):
    """Add a photo to database"""
    conn = get_db_connection()
    cursor = conn.execute(
        'INSERT INTO photos (filename, album_id, status) VALUES (?, ?, ?)',
        (filename, album_id, status)
    )
    photo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return photo_id

def update_photo_album(filename, album_id):
    """Update photo's album"""
    conn = get_db_connection()
    conn.execute('UPDATE photos SET album_id = ? WHERE filename = ?', (album_id, filename))
    conn.commit()
    conn.close()
    return True

def update_photo_status(filename, status):
    """Update photo status"""
    conn = get_db_connection()
    conn.execute('UPDATE photos SET status = ? WHERE filename = ?', (status, filename))
    conn.commit()
    conn.close()
    return True

def update_photo_size(filename, size_bytes):
    """Update photo file size"""
    conn = get_db_connection()
    conn.execute('UPDATE photos SET size_bytes = ? WHERE filename = ?', (size_bytes, filename))
    conn.commit()
    conn.close()
    return True

def delete_photo(filename):
    """Delete a photo from database"""
    conn = get_db_connection()
    conn.execute('DELETE FROM photos WHERE filename = ?', (filename,))
    conn.commit()
    conn.close()
    return True

def get_album_photo_count(album_id):
    """Get photo count for an album"""
    conn = get_db_connection()
    if album_id == 0:  # "All Work"
        count = conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
    else:
        count = conn.execute('SELECT COUNT(*) FROM photos WHERE album_id = ?', (album_id,)).fetchone()[0]
    conn.close()
    return count
