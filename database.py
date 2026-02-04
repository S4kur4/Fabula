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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (album_id) REFERENCES albums (id) ON DELETE SET NULL
        )
    ''')

    # Insert default "All Work" album if not exists
    cursor.execute("SELECT COUNT(*) FROM albums WHERE id = 0")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO albums (id, name) VALUES (0, 'All Work')")

    conn.commit()
    conn.close()

def get_db_connection():
    """Get a database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Album operations
def get_all_albums():
    """Get all albums"""
    conn = get_db_connection()
    albums = conn.execute('SELECT * FROM albums ORDER BY id').fetchall()
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

def add_photo(filename, album_id=None):
    """Add a photo to database"""
    conn = get_db_connection()
    cursor = conn.execute('INSERT INTO photos (filename, album_id) VALUES (?, ?)', (filename, album_id))
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
