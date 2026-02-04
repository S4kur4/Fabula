import os
import random
import uuid
import json
import secrets
import io
import hashlib
import requests
from functools import wraps
from PIL import Image
from datetime import datetime
from urllib.parse import urljoin
from flask import make_response
from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for, session
import database as db

app = Flask(__name__)
# Use a fixed secret key from environment or generate a consistent one
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

app.config['PHOTO_FOLDER'] = os.path.join(app.static_folder, 'photos')

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


@app.route('/')
def index():
    # Basic info
    tittle = os.environ.get('TITTLE')
    google_analytics_id = os.environ.get('GOOGLE_ANALYTICS_ID')
    umami_website_id = os.environ.get('UMAMI_WEBSITE_ID')

    # About page data
    about_heading = os.environ.get('ABOUT_HEADING', tittle)
    about_me = json.loads(os.environ.get('ABOUT_ME', '[]'))
    about_signature = os.environ.get('ABOUT_SIGNATURE', '')

    # Parse JSON arrays for about page sections
    about_clients = json.loads(os.environ.get('ABOUT_CLIENTS', '[]'))
    about_gear = json.loads(os.environ.get('ABOUT_GEAR', '[]'))
    about_contact = json.loads(os.environ.get('ABOUT_CONTACT', '[]'))

    return render_template('index.html',
                         tittle=tittle,
                         about_me=about_me,
                         about_heading=about_heading,
                         about_signature=about_signature,
                         about_clients=about_clients,
                         about_gear=about_gear,
                         about_contact=about_contact,
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
    full_info = request.args.get('full_info', type=bool, default=False)

    if album_id is not None:
        # Get photos for specific album
        photos = db.get_photos_by_album(album_id)
    else:
        # Get all photos
        photos = db.get_all_photos()

    # Return full photo info for manage page, or just filenames for gallery
    if full_info:
        return jsonify(photos)
    else:
        return jsonify([photo['filename'] for photo in photos])


@app.route('/api/albums')
def get_albums():
    """Get all albums with photo counts"""
    albums = db.get_all_albums()
    # Add photo count to each album
    for album in albums:
        album['photo_count'] = db.get_album_photo_count(album['id'])
    return jsonify(albums)


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
        file_path = os.path.join(app.config['PHOTO_FOLDER'], filename)
        thumbnail_path = os.path.join(
            app.config['PHOTO_FOLDER'], filename.replace('.webp', '-thumbnail.webp'))
        deleted = False
        if os.path.exists(file_path):
            os.remove(file_path)
            deleted = True
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
            deleted = True
        if deleted:
            # Remove from database
            db.delete_photo(filename)
            return jsonify({'success': True, 'message': 'Photo deleted successfully'})
    return jsonify({'success': False, 'message': 'Failed to delete photo'}), 400


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
        filename = str(uuid.uuid4()) + '.webp'
        file_path = os.path.join(app.config['PHOTO_FOLDER'], filename)
        thumbnail_path = os.path.join(
            app.config['PHOTO_FOLDER'], filename.replace('.webp', '-thumbnail.webp'))

        # Save and convert to webp
        img = Image.open(file)
        img.save(file_path, 'WEBP')

        # Create thumbnail
        width, height = img.size
        thumbnail_size = (int(width * 0.6), int(height * 0.6))
        img.thumbnail(thumbnail_size)
        img.save(thumbnail_path, 'WEBP')

        # Add to database
        album_id = request.form.get('album_id', type=int)
        db.add_photo(filename, album_id)

        return jsonify({'success': True, 'message': 'Photo uploaded successfully', 'filename': filename})
    return jsonify({'success': False, 'message': 'File type not allowed'}), 400


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
