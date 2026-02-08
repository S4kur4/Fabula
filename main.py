import os
import random
import uuid
import json
import secrets
import io
import hashlib
import requests
import glob
import queue
import threading
from functools import wraps
from PIL import Image, ImageOps
from datetime import datetime
from urllib.parse import urljoin
from flask import make_response
from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for, session, Response, stream_with_context
from concurrent.futures import ThreadPoolExecutor
import database as db

app = Flask(__name__)
# Use a fixed secret key from environment or generate a consistent one
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

app.config['PHOTO_FOLDER'] = os.path.join(app.static_folder, 'photos')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')

# Ensure folders exist
os.makedirs(app.config['PHOTO_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Background image processing
executor = ThreadPoolExecutor(max_workers=2)

# SSE subscribers
sse_subscribers = []
sse_lock = threading.Lock()


def sse_publish(event, data):
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        for q in list(sse_subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

# Initialize database
db.init_db()

USERNAME = os.environ.get('ADMIN_USERNAME')
PASSWORD = os.environ.get('ADMIN_PASSWORD')
TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY')
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY')

def verify_turnstile(token):
     data = {
         "secret": TURNSTILE_SECRET_KEY,
         "response": token
     }
     response = requests.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data)
     return response.json()["success"]


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/sitemap.xml')
def sitemap():
    """Generate sitemap.xml"""
    pages = []
    base_url = request.url_root.rstrip('/')

    pages.append({
        'loc': base_url,
        'lastmod': datetime.now().strftime('%Y-%m-%d'),
        'changefreq': 'daily',
        'priority': '1.0'
    })

    pages.append({
            'loc': urljoin(base_url, '#about'),
            'lastmod': datetime.now().strftime('%Y-%m-%d'),
            'changefreq': 'monthly',
            'priority': '0.8'
    })

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for page in pages:
        xml += '  <url>\n'
        xml += f'    <loc>{page["loc"]}</loc>\n'
        xml += f'    <lastmod>{page["lastmod"]}</lastmod>\n'
        xml += f'    <changefreq>{page["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{page["priority"]}</priority>\n'
        xml += '  </url>\n'

    xml += '</urlset>'

    response = make_response(xml)
    response.headers["Content-Type"] = "application/xml"

    return response


@app.route('/robots.txt')
def robots():
    """Generate robots.txt"""
    base_url = request.url_root.rstrip('/')

    robots_txt = f"""User-agent: *
Allow: /
Allow: /static/photos/
Disallow: /login
Disallow: /manage
Disallow: /api/
Disallow: /logout

Sitemap: {base_url}/sitemap.xml
"""

    response = make_response(robots_txt)
    response.headers["Content-Type"] = "text/plain"

    return response


def get_about_data():
    defaults = {
        "heading": "",
        "me": "",
        "signature": "",
        "gear": "[]",
        "contact": "[]",
    }

    stored = db.get_setting("about")
    if not stored:
        data = defaults
    else:
        try:
            data = json.loads(stored)
        except Exception:
            data = defaults

    data["gear"] = json.loads(data.get("gear", "[]")) if isinstance(data.get("gear"), str) else data.get("gear", [])
    data["contact"] = json.loads(data.get("contact", "[]")) if isinstance(data.get("contact"), str) else data.get("contact", [])
    return data


@app.route('/')
def index():
    # Basic info
    tittle = os.environ.get('TITTLE')
    google_analytics_id = os.environ.get('GOOGLE_ANALYTICS_ID')
    umami_website_id = os.environ.get('UMAMI_WEBSITE_ID')

    about = get_about_data()

    return render_template('index.html',
                         tittle=tittle,
                         about_me=about.get("me", ""),
                         about_heading=about.get("heading", tittle),
                         about_signature=about.get("signature", ""),
                         about_gear=about.get("gear", []),
                         about_contact=about.get("contact", []),
                         google_analytics_id=google_analytics_id,
                         umami_website_id=umami_website_id)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY:
            turnstile_response = request.form.get('cf-turnstile-response')
            if not turnstile_response:
                return render_template('login.html',
                                    error='Please complete the Turnstile challenge',
                                    turnstile_site_key=TURNSTILE_SITE_KEY)

            if not verify_turnstile(turnstile_response):
                return render_template('login.html',
                                    error='Turnstile verification failed',
                                    turnstile_site_key=TURNSTILE_SITE_KEY)

        if (request.form['username'] == USERNAME and
            hashlib.sha256(request.form['password'].encode()).hexdigest() == PASSWORD):
            session['logged_in'] = True
            return redirect(url_for('manage'))
        else:
            return render_template('login.html',
                                error='Invalid credentials',
                                turnstile_site_key=TURNSTILE_SITE_KEY)
    return render_template('login.html', turnstile_site_key=TURNSTILE_SITE_KEY)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))


@app.route('/manage')
@login_required
def manage():
    return render_template('manage.html')


@app.route('/api/photo_list')
def photo_list():
    """Get all photos with album information"""
    album_id = request.args.get('album_id', type=int)
    full_info = request.args.get('full_info', 'false').lower() == 'true'
    include_processing = request.args.get('include_processing', 'false').lower() == 'true'
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', type=int, default=0)

    if limit is not None:
        photos = db.get_photos_paged(
            album_id=album_id,
            limit=limit,
            offset=offset,
            include_processing=include_processing,
            include_album=full_info
        )
        total = db.get_photo_count(album_id=album_id, include_processing=include_processing)
        if full_info:
            items = photos
        else:
            items = [photo['filename'] for photo in photos]
        next_offset = offset + limit if offset + limit < total else None
        return jsonify({'items': items, 'next_offset': next_offset, 'total': total})

    if album_id is not None:
        # Get photos for specific album
        photos = db.get_photos_by_album(album_id)
    else:
        # Get all photos
        photos = db.get_all_photos()

    if not include_processing:
        photos = [photo for photo in photos if photo.get('status') == 'ready']

    # Return full photo info for manage page, or just filenames for gallery
    if full_info:
        return jsonify(photos)
    else:
        return jsonify([photo['filename'] for photo in photos])


@app.route('/api/albums')
def get_albums():
    """Get all albums with photo counts"""
    albums = db.get_all_albums_with_counts()
    return jsonify(albums)


@app.route('/api/about', methods=['GET'])
@login_required
def get_about():
    return jsonify(get_about_data())


@app.route('/api/about', methods=['PUT'])
@login_required
def update_about():
    data = request.json or {}
    payload = {
        "heading": data.get("heading", ""),
        "me": data.get("me", ""),
        "signature": data.get("signature", ""),
        "gear": json.dumps(data.get("gear", [])),
        "contact": json.dumps(data.get("contact", [])),
    }
    db.set_setting("about", json.dumps(payload))
    return jsonify({'success': True, 'message': 'About updated'})


@app.route('/api/events')
@login_required
def events():
    """Server-Sent Events for admin updates"""
    q = queue.Queue(maxsize=100)
    with sse_lock:
        sse_subscribers.append(q)

    def stream():
        try:
            yield "event: init\ndata: {}\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with sse_lock:
                if q in sse_subscribers:
                    sse_subscribers.remove(q)

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


@app.route('/api/albums', methods=['POST'])
@login_required
def create_album():
    """Create a new album"""
    name = request.json.get('name')
    if not name:
        return jsonify({'success': False, 'message': 'Album name is required'}), 400

    album_id = db.create_album(name)
    if album_id:
        return jsonify({'success': True, 'album_id': album_id, 'message': 'Album created successfully'})
    else:
        return jsonify({'success': False, 'message': 'Album name already exists'}), 400


@app.route('/api/albums/<int:album_id>', methods=['PUT'])
@login_required
def update_album(album_id):
    """Update album name"""
    name = request.json.get('name')
    if not name:
        return jsonify({'success': False, 'message': 'Album name is required'}), 400

    if db.update_album(album_id, name):
        return jsonify({'success': True, 'message': 'Album updated successfully'})
    else:
        return jsonify({'success': False, 'message': 'Failed to update album'}), 400


@app.route('/api/albums/<int:album_id>', methods=['DELETE'])
@login_required
def delete_album(album_id):
    """Delete an album"""
    if db.delete_album(album_id):
        return jsonify({'success': True, 'message': 'Album deleted successfully'})
    else:
        return jsonify({'success': False, 'message': 'Cannot delete this album'}), 400


@app.route('/static/photos/<path:filename>')
def serve_photo(filename):
    # Cache for 30 days
    return send_from_directory(app.config['PHOTO_FOLDER'], filename, max_age=604800)


@app.route('/api/delete_photo', methods=['POST'])
@login_required
def delete_photo():
    filename = request.json.get('filename')
    if filename:
        deleted = delete_photo_files(filename)
        if deleted:
            # Remove from database
            db.delete_photo(filename)
            sse_publish('photo_deleted', {'filename': filename})
            return jsonify({'success': True, 'message': 'Photo deleted successfully'})
    return jsonify({'success': False, 'message': 'Failed to delete photo'}), 400


@app.route('/api/delete_photos', methods=['POST'])
@login_required
def delete_photos():
    data = request.json or {}
    filenames = data.get('filenames', [])
    if not isinstance(filenames, list) or not filenames:
        return jsonify({'success': False, 'message': 'No files provided'}), 400

    deleted_any = False
    for filename in filenames:
        if not isinstance(filename, str):
            continue
        deleted = delete_photo_files(filename)
        if deleted:
            db.delete_photo(filename)
            sse_publish('photo_deleted', {'filename': filename})
            deleted_any = True

    if deleted_any:
        return jsonify({'success': True, 'message': 'Photos deleted successfully'})
    return jsonify({'success': False, 'message': 'Failed to delete photos'}), 400


@app.route('/api/photos/<filename>/album', methods=['PUT'])
@login_required
def update_photo_album(filename):
    """Update photo's album"""
    album_id = request.json.get('album_id')
    if album_id is not None:
        db.update_photo_album(filename, album_id if album_id != '' else None)
        return jsonify({'success': True, 'message': 'Photo album updated successfully'})
    return jsonify({'success': False, 'message': 'Album ID is required'}), 400


@app.route('/api/upload_photo', methods=['POST'])
@login_required
def upload_photo():
    if 'photo' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'}), 400
    file = request.files['photo']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        filename = str(uuid.uuid4()) + '.webp'
        temp_filename = filename.replace('.webp', f'.{file_ext}')
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)

        # Save original upload to temp path
        file.save(temp_path)

        # Add to database with processing status
        album_id = request.form.get('album_id', type=int)
        db.add_photo(filename, album_id, status='processing')
        sse_publish('photo_status', {'filename': filename, 'status': 'processing'})

        # Process in background
        executor.submit(process_photo, temp_path, filename)

        return jsonify({'success': True, 'message': 'Photo uploaded successfully', 'filename': filename})
    return jsonify({'success': False, 'message': 'File type not allowed'}), 400


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def delete_photo_files(filename):
    file_path = os.path.join(app.config['PHOTO_FOLDER'], filename)
    thumbnail_path = os.path.join(
        app.config['PHOTO_FOLDER'], filename.replace('.webp', '-thumbnail.webp'))
    upload_glob = os.path.join(app.config['UPLOAD_FOLDER'], filename.replace('.webp', '.*'))
    deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        deleted = True
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
        deleted = True
    for path in glob.glob(upload_glob):
        os.remove(path)
        deleted = True
    return deleted


def process_photo(temp_path, filename):
    """Convert to webp + create optimized thumbnail in background"""
    file_path = os.path.join(app.config['PHOTO_FOLDER'], filename)
    thumbnail_path = os.path.join(
        app.config['PHOTO_FOLDER'], filename.replace('.webp', '-thumbnail.webp'))

    try:
        with Image.open(temp_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            # Main image: limit max dimension
            main_img = img.copy()
            main_img.thumbnail((2400, 2400), Image.LANCZOS)
            main_img.save(file_path, 'WEBP', quality=82, method=6, optimize=True)

            # Thumbnail: larger and higher quality for sharper gallery
            thumb = img.copy()
            thumb.thumbnail((900, 900), Image.LANCZOS)
            thumb.save(thumbnail_path, 'WEBP', quality=78, method=6, optimize=True)

        db.update_photo_status(filename, 'ready')
        try:
            size_bytes = os.path.getsize(file_path)
            db.update_photo_size(filename, size_bytes)
        except Exception:
            pass
        sse_publish('photo_status', {'filename': filename, 'status': 'ready'})
    except Exception:
        db.update_photo_status(filename, 'failed')
        sse_publish('photo_status', {'filename': filename, 'status': 'failed'})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
