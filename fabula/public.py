from __future__ import annotations

import re
from datetime import date

from flask import (
    Blueprint,
    Response,
    abort,
    g,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .db import get_db
from .i18n import translate
from .media import SITE_IMAGE_SLOTS, SITE_STORAGE_PATTERN, STORAGE_PATTERN
from .settings import get_site_copy, get_site_images


bp = Blueprint("public", __name__)


def serialize_photo(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "story": row["story"],
        "photographer": row["photographer"],
        "owner_id": row["user_id"],
        "album_id": row["album_id"],
        "album": row["album_name"] or translate("未分类"),
        "width": row["width"],
        "height": row["height"],
        "image_url": url_for("public.media_file", variant="original", storage_name=row["storage_name"]),
        "thumb_url": url_for("public.media_file", variant="thumbs", storage_name=row["storage_name"]),
    }


def public_photos(album_id: int | None, limit: int, offset: int) -> list[dict]:
    parameters: list[object] = []
    where = ["p.status = 'ready'", "a.status = 'published'"]
    order_by = "p.created_at DESC, p.id DESC"
    if album_id is not None:
        where.append("p.album_id = ?")
        parameters.append(album_id)
        order_by = (
            "CASE WHEN p.album_position IS NULL THEN 1 ELSE 0 END, "
            "p.album_position, p.created_at DESC, p.id DESC"
        )
    parameters.extend([limit, offset])
    rows = get_db().execute(
        f"""
        SELECT p.*, u.display_name AS photographer, a.name AS album_name
        FROM photos p
        JOIN users u ON u.id = p.user_id
        JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
        WHERE {" AND ".join(where)}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        parameters,
    ).fetchall()
    return [serialize_photo(row) for row in rows]


def public_albums() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT a.id, a.name, u.display_name AS photographer, COUNT(p.id) AS photo_count
        FROM albums a
        JOIN users u ON u.id = a.user_id
        JOIN photos p
            ON p.album_id = a.id
            AND p.user_id = a.user_id
            AND p.status = 'ready'
        WHERE a.status = 'published'
        GROUP BY a.id
        ORDER BY a.created_at, a.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def public_profiles() -> list[dict]:
    rows = get_db().execute(
        """
        WITH ranked_photos AS (
            SELECT
                p.user_id,
                p.storage_name,
                COUNT(*) OVER (PARTITION BY p.user_id) AS photo_count,
                ROW_NUMBER() OVER (
                    PARTITION BY p.user_id
                    ORDER BY p.created_at DESC, p.id DESC
                ) AS row_number
            FROM photos p
            JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
            WHERE p.status = 'ready' AND a.status = 'published'
        )
        SELECT
            u.id,
            u.display_name,
            ab.title,
            ab.bio,
            ab.signature,
            ab.gear_json,
            ab.contact_json,
            rp.storage_name AS cover_name,
            COALESCE(rp.photo_count, 0) AS photo_count
        FROM users u
        JOIN about_blocks ab ON ab.user_id = u.id
        LEFT JOIN ranked_photos rp
            ON rp.user_id = u.id AND rp.row_number = 1
        WHERE trim(ab.title) <> '' OR trim(ab.bio) <> ''
        ORDER BY u.id
        """
    ).fetchall()
    import json

    profiles = []
    for row in rows:
        item = dict(row)
        try:
            item["gear"] = json.loads(item.pop("gear_json"))
        except (TypeError, json.JSONDecodeError):
            item["gear"] = []
        try:
            item["contact"] = json.loads(item.pop("contact_json"))
        except (TypeError, json.JSONDecodeError):
            item["contact"] = []
        item["paragraphs"] = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n|\r?\n", item["bio"] or "")
            if paragraph.strip()
        ]
        item["gear"] = [structured_item(value) for value in item["gear"]]
        item["contact"] = [structured_item(value) for value in item["contact"]]
        if item["cover_name"]:
            item["cover_url"] = url_for(
                "public.media_file",
                variant="original",
                storage_name=item["cover_name"],
            )
        else:
            item["cover_url"] = None
        profiles.append(item)
    return profiles


def structured_item(value: object) -> dict:
    text = str(value).strip()
    for separator in (" / ", "：", ":"):
        if separator in text:
            label, detail = text.split(separator, 1)
            return {"label": label.strip(), "value": detail.strip()}
    return {"label": "", "value": text}


@bp.get("/")
def index():
    albums = public_albums()
    initial_album_id = albums[0]["id"] if albums else None
    initial_photo_total = albums[0]["photo_count"] if albums else 0
    photos = public_photos(album_id=initial_album_id, limit=24, offset=0)
    total = get_db().execute(
        """
        SELECT COUNT(*)
        FROM photos p
        JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
        WHERE p.status = 'ready' AND a.status = 'published'
        """
    ).fetchone()[0]
    return render_template(
        "public.html",
        site_copy=get_site_copy(),
        photos=photos,
        total_photos=total,
        initial_photo_total=initial_photo_total,
        albums=albums,
        profiles=public_profiles(),
        current_year=date.today().year,
    )


@bp.get("/api/public/photos")
def photo_feed():
    limit = min(max(request.args.get("limit", 24, type=int), 1), 24)
    offset = max(request.args.get("offset", 0, type=int), 0)
    album_id = request.args.get("album_id", type=int)
    items = public_photos(album_id=album_id, limit=limit, offset=offset)
    count_parameters: list[object] = []
    count_where = ["p.status = 'ready'", "a.status = 'published'"]
    if album_id is not None:
        count_where.append("p.album_id = ?")
        count_parameters.append(album_id)
    total = get_db().execute(
        f"""
        SELECT COUNT(*)
        FROM photos p
        JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
        WHERE {' AND '.join(count_where)}
        """,
        count_parameters,
    ).fetchone()[0]
    next_offset = offset + len(items)
    return jsonify(
        {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }
    )


@bp.get("/media/<variant>/<storage_name>")
def media_file(variant: str, storage_name: str):
    if variant not in {"original", "thumbs"} or not STORAGE_PATTERN.fullmatch(storage_name):
        abort(404)
    row = get_db().execute(
        """
        SELECT p.status, p.user_id, a.status AS album_status
        FROM photos p
        LEFT JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
        WHERE p.storage_name = ?
        """,
        (storage_name,),
    ).fetchone()
    if row is None or row["status"] != "ready":
        abort(404)
    publicly_available = row["album_status"] == "published"
    owned_by_current_user = (
        getattr(g, "user", None) is not None and g.user["id"] == row["user_id"]
    )
    if not publicly_available and not owned_by_current_user:
        abort(404)
    directory = current_media_directory(variant)
    response = send_from_directory(
        directory,
        storage_name,
        max_age=0,
        conditional=True,
    )
    if publicly_available:
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    else:
        response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/site-media/<slot>/<storage_name>")
def site_media_file(slot: str, storage_name: str):
    if (
        slot not in SITE_IMAGE_SLOTS
        or not SITE_STORAGE_PATTERN.fullmatch(storage_name)
        or get_site_images().get(slot) != storage_name
    ):
        abort(404)
    return send_from_directory(
        current_site_media_directory(),
        storage_name,
        max_age=31536000,
        conditional=True,
    )


def current_media_directory(variant: str) -> str:
    from flask import current_app

    return str(current_app.config["MEDIA_ROOT"] / variant)


def current_site_media_directory() -> str:
    from flask import current_app

    return str(current_app.config["SITE_MEDIA_ROOT"])


@bp.get("/sitemap.xml")
def sitemap():
    base_url = request.url_root.rstrip("/")
    today = date.today().isoformat()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base_url}/</loc><lastmod>{today}</lastmod></url>\n"
        f"  <url><loc>{base_url}/#about</loc><lastmod>{today}</lastmod></url>\n"
        "</urlset>\n"
    )
    return Response(xml, content_type="application/xml")


@bp.get("/robots.txt")
def robots():
    base_url = request.url_root.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /login\n"
        "Disallow: /studio\n"
        "Disallow: /api/\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    return Response(body, content_type="text/plain")
