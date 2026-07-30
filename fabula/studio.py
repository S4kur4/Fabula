from __future__ import annotations

import json
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .i18n import SUPPORTED_LOCALES, translate
from .media import InvalidImage, delete_media, process_image
from .security import (
    api_error,
    audit,
    login_required,
    password_ready,
    refresh_current_user,
    safe_next_url,
    valid_password,
)
from .settings import get_site_copy


bp = Blueprint("studio", __name__, url_prefix="/studio")


def album_rows(user_id: int) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT a.id, a.name, a.created_at, COUNT(p.id) AS photo_count
        FROM albums a
        LEFT JOIN photos p ON p.album_id = a.id AND p.user_id = a.user_id
        WHERE a.user_id = ?
        GROUP BY a.id
        ORDER BY a.created_at, a.id
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def serialize_photo(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "story": row["story"],
        "original_name": row["original_name"],
        "album_id": row["album_id"],
        "album_name": row["album_name"] or translate("未分类"),
        "status": row["status"],
        "width": row["width"],
        "height": row["height"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "thumb_url": (
            url_for(
                "public.media_file",
                variant="thumbs",
                storage_name=row["storage_name"],
            )
            if row["status"] == "ready"
            else None
        ),
    }


def studio_photos(user_id: int, limit: int = 24, offset: int = 0) -> list[dict]:
    rows = get_db().execute(
        """
        SELECT p.*, a.name AS album_name
        FROM photos p
        LEFT JOIN albums a ON a.id = p.album_id
        WHERE p.user_id = ?
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [serialize_photo(row) for row in rows]


def about_data(user_id: int) -> dict:
    row = get_db().execute(
        "SELECT * FROM about_blocks WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {
            "title": "",
            "bio": "",
            "signature": "",
            "gear": [],
            "contact": [],
        }
    data = dict(row)
    for key, output_key in (("gear_json", "gear"), ("contact_json", "contact")):
        try:
            data[output_key] = json.loads(data.pop(key))
        except (TypeError, json.JSONDecodeError):
            data[output_key] = []
    return data


def photo_revision(user_id: int) -> str:
    row = get_db().execute(
        """
        SELECT COUNT(*) AS total, COALESCE(MAX(updated_at), '') AS latest
        FROM photos
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return f"{row['total']}:{row['latest']}"


@bp.get("")
@login_required
def workspace():
    active_tab = request.args.get("tab", "photos")
    if g.user["must_change_password"]:
        active_tab = "security"
    allowed_tabs = {"photos", "about", "security"}
    if g.user["role"] == "admin":
        allowed_tabs.update({"site-copy", "users"})
    if active_tab not in allowed_tabs:
        active_tab = "photos"
    connection = get_db()
    photos = studio_photos(g.user["id"])
    return render_template(
        "studio.html",
        active_tab=active_tab,
        albums=album_rows(g.user["id"]),
        photos=photos,
        photo_total=connection.execute(
            "SELECT COUNT(*) FROM photos WHERE user_id = ?",
            (g.user["id"],),
        ).fetchone()[0],
        uncategorized_total=connection.execute(
            "SELECT COUNT(*) FROM photos WHERE user_id = ? AND album_id IS NULL",
            (g.user["id"],),
        ).fetchone()[0],
        about=about_data(g.user["id"]),
        site_copy=get_site_copy(),
        photo_revision=photo_revision(g.user["id"]),
    )


@bp.post("/locale")
@login_required
def update_locale():
    locale = str(request.form.get("locale", "")).strip()
    if locale not in SUPPORTED_LOCALES:
        abort(400)
    connection = get_db()
    connection.execute(
        """
        UPDATE users
        SET locale = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (locale, g.user["id"]),
    )
    connection.commit()
    session["locale"] = locale
    refresh_current_user()
    return redirect(
        safe_next_url(request.form.get("next")) or url_for("studio.workspace")
    )


@bp.get("/api/photos")
@password_ready
def photo_list():
    limit = min(max(request.args.get("limit", 24, type=int), 1), 24)
    offset = max(request.args.get("offset", 0, type=int), 0)
    items = studio_photos(g.user["id"], limit=limit, offset=offset)
    total = get_db().execute(
        "SELECT COUNT(*) FROM photos WHERE user_id = ?",
        (g.user["id"],),
    ).fetchone()[0]
    next_offset = offset + len(items)
    return jsonify(
        {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }
    )


@bp.get("/api/revision")
@password_ready
def revision():
    return jsonify({"photo_revision": photo_revision(g.user["id"])})


@bp.post("/api/albums")
@password_ready
def create_album():
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not name or len(name) > 40 or name.casefold() in {"未分类", "uncategorized"}:
        return api_error(translate("摄影集名称需为 1 到 40 个字符"))
    connection = get_db()
    try:
        cursor = connection.execute(
            "INSERT INTO albums (user_id, name) VALUES (?, ?)",
            (g.user["id"], name),
        )
        connection.commit()
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            return api_error(translate("你的摄影集中已经存在这个名称"))
        raise
    return jsonify({"success": True, "album": {"id": cursor.lastrowid, "name": name, "photo_count": 0}})


@bp.patch("/api/albums/<int:album_id>")
@password_ready
def rename_album(album_id: int):
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not name or len(name) > 40 or name.casefold() in {"未分类", "uncategorized"}:
        return api_error(translate("摄影集名称需为 1 到 40 个字符"))
    connection = get_db()
    album = connection.execute(
        "SELECT * FROM albums WHERE id = ? AND user_id = ?",
        (album_id, g.user["id"]),
    ).fetchone()
    if album is None:
        return api_error(translate("摄影集不存在或不属于当前用户"), 404)
    try:
        connection.execute(
            """
            UPDATE albums
            SET name = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND user_id = ?
            """,
            (name, album_id, g.user["id"]),
        )
        connection.commit()
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            return api_error(translate("你的摄影集中已经存在这个名称"))
        raise
    return jsonify({"success": True, "message": translate("摄影集已重命名")})


@bp.delete("/api/albums/<int:album_id>")
@password_ready
def delete_album(album_id: int):
    connection = get_db()
    delete_photos = (request.get_json(silent=True) or {}).get("delete_photos") is True
    connection.execute("BEGIN IMMEDIATE")
    album = connection.execute(
        "SELECT * FROM albums WHERE id = ? AND user_id = ?",
        (album_id, g.user["id"]),
    ).fetchone()
    if album is None:
        connection.rollback()
        return api_error(translate("摄影集不存在或不属于当前用户"), 404)
    photos = connection.execute(
        "SELECT storage_name FROM photos WHERE album_id = ? AND user_id = ?",
        (album_id, g.user["id"]),
    ).fetchall()
    if delete_photos:
        connection.execute(
            "DELETE FROM photos WHERE album_id = ? AND user_id = ?",
            (album_id, g.user["id"]),
        )
    else:
        connection.execute(
            "UPDATE photos SET album_id = NULL WHERE album_id = ? AND user_id = ?",
            (album_id, g.user["id"]),
        )
    connection.execute(
        "DELETE FROM albums WHERE id = ? AND user_id = ?",
        (album_id, g.user["id"]),
    )
    connection.commit()
    if delete_photos:
        for photo in photos:
            delete_media(photo["storage_name"])
        return jsonify(
            {
                "success": True,
                "deleted_photos": len(photos),
                "message": translate(
                    "摄影集及其中 {count} 张照片已删除", count=len(photos)
                ),
            }
        )
    return jsonify(
        {
            "success": True,
            "deleted_photos": 0,
            "message": translate(
                "摄影集已删除，其中 {count} 张照片已移到未分类",
                count=len(photos),
            ),
        }
    )


def owned_album(album_id: int | None):
    if album_id is None:
        return None
    return get_db().execute(
        "SELECT id FROM albums WHERE id = ? AND user_id = ?",
        (album_id, g.user["id"]),
    ).fetchone()


@bp.post("/api/photos")
@password_ready
def upload_photo():
    uploaded = request.files.get("photo")
    if uploaded is None or not uploaded.filename:
        return api_error(translate("请选择图片文件"))
    album_id = request.form.get("album_id", type=int)
    if album_id is not None and owned_album(album_id) is None:
        return api_error(translate("不能向其他用户的摄影集上传照片"), 403)
    try:
        processed = process_image(uploaded.stream)
    except InvalidImage as error:
        return api_error(str(error))
    original_name = Path(uploaded.filename).name[:180]
    title = Path(original_name).stem[:80]
    connection = get_db()
    try:
        cursor = connection.execute(
            """
            INSERT INTO photos (
                user_id, album_id, storage_name, original_name, title,
                status, mime_type, width, height, size_bytes
            ) VALUES (?, ?, ?, ?, ?, 'ready', 'image/webp', ?, ?, ?)
            """,
            (
                g.user["id"],
                album_id,
                processed["storage_name"],
                original_name,
                title,
                processed["width"],
                processed["height"],
                processed["size_bytes"],
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        delete_media(processed["storage_name"])
        raise
    photo = connection.execute(
        """
        SELECT p.*, a.name AS album_name
        FROM photos p
        LEFT JOIN albums a ON a.id = p.album_id
        WHERE p.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify({"success": True, "photo": serialize_photo(photo)})


@bp.patch("/api/photos/<int:photo_id>")
@password_ready
def update_photo(photo_id: int):
    values = request.get_json(silent=True) or {}
    title = str(values.get("title", "")).strip()[:80]
    story = str(values.get("story", "")).strip()[:1200]
    album_id = values.get("album_id")
    if album_id in {"", None}:
        album_id = None
    else:
        try:
            album_id = int(album_id)
        except (TypeError, ValueError):
            return api_error(translate("摄影集无效"))
        if owned_album(album_id) is None:
            return api_error(translate("不能把照片加入其他用户的摄影集"), 403)
    connection = get_db()
    cursor = connection.execute(
        """
        UPDATE photos
        SET title = ?, story = ?, album_id = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ? AND user_id = ?
        """,
        (title, story, album_id, photo_id, g.user["id"]),
    )
    if cursor.rowcount != 1:
        return api_error(translate("照片不存在或不属于当前用户"), 404)
    connection.commit()
    return jsonify({"success": True, "message": translate("照片内容已更新")})


@bp.delete("/api/photos/<int:photo_id>")
@password_ready
def delete_photo(photo_id: int):
    connection = get_db()
    photo = connection.execute(
        "SELECT storage_name FROM photos WHERE id = ? AND user_id = ?",
        (photo_id, g.user["id"]),
    ).fetchone()
    if photo is None:
        return api_error(translate("照片不存在或不属于当前用户"), 404)
    connection.execute(
        "DELETE FROM photos WHERE id = ? AND user_id = ?",
        (photo_id, g.user["id"]),
    )
    connection.commit()
    delete_media(photo["storage_name"])
    return jsonify({"success": True, "message": translate("照片已删除")})


@bp.post("/api/photos/bulk-delete")
@password_ready
def bulk_delete():
    values = request.get_json(silent=True) or {}
    identifiers = values.get("ids", [])
    if not isinstance(identifiers, list) or not identifiers:
        return api_error(translate("请选择需要删除的照片"))
    identifiers = [int(value) for value in identifiers if str(value).isdigit()]
    if not identifiers:
        return api_error(translate("请选择需要删除的照片"))
    placeholders = ",".join("?" for _ in identifiers)
    connection = get_db()
    rows = connection.execute(
        f"""
        SELECT id, storage_name FROM photos
        WHERE user_id = ? AND id IN ({placeholders})
        """,
        [g.user["id"], *identifiers],
    ).fetchall()
    if not rows:
        return api_error(translate("没有可删除的照片"), 404)
    owned_ids = [row["id"] for row in rows]
    owned_placeholders = ",".join("?" for _ in owned_ids)
    connection.execute(
        f"DELETE FROM photos WHERE user_id = ? AND id IN ({owned_placeholders})",
        [g.user["id"], *owned_ids],
    )
    connection.commit()
    for row in rows:
        delete_media(row["storage_name"])
    return jsonify({"success": True, "deleted": len(rows)})


@bp.put("/api/about")
@password_ready
def update_about():
    values = request.get_json(silent=True) or {}
    display_name = str(values.get("display_name", "")).strip()[:80]
    title = str(values.get("title", "")).strip()[:180]
    bio = str(values.get("bio", "")).strip()[:2400]
    signature = str(values.get("signature", "")).strip()[:100]
    gear = values.get("gear", [])
    contact = values.get("contact", [])
    if not display_name:
        return api_error(translate("公开显示名称不能为空"))
    if not isinstance(gear, list) or not isinstance(contact, list):
        return api_error(translate("器材和联系方式格式无效"))
    gear = [str(item).strip()[:120] for item in gear if str(item).strip()][:12]
    contact = [str(item).strip()[:180] for item in contact if str(item).strip()][:12]
    connection = get_db()
    connection.execute(
        """
        UPDATE users
        SET display_name = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (display_name, g.user["id"]),
    )
    connection.execute(
        """
        INSERT INTO about_blocks (
            user_id, title, bio, signature, gear_json, contact_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            title = excluded.title,
            bio = excluded.bio,
            signature = excluded.signature,
            gear_json = excluded.gear_json,
            contact_json = excluded.contact_json,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            g.user["id"],
            title,
            bio,
            signature,
            json.dumps(gear, ensure_ascii=False),
            json.dumps(contact, ensure_ascii=False),
        ),
    )
    connection.commit()
    refresh_current_user()
    return jsonify({"success": True, "message": translate("你的 About 已保存")})


@bp.post("/api/account/password")
@login_required
def change_password():
    values = request.get_json(silent=True) or {}
    current_password = str(values.get("current_password", ""))
    new_password = str(values.get("new_password", ""))
    confirmation = str(values.get("confirmation", ""))
    if not check_password_hash(g.user["password_hash"], current_password):
        return api_error(translate("当前密码不正确"))
    if not valid_password(new_password):
        return api_error(translate("新密码至少 12 个字符，并同时包含字母和数字"))
    if new_password == current_password:
        return api_error(translate("新密码不能与当前密码相同"))
    if new_password != confirmation:
        return api_error(translate("两次输入的新密码不一致"))
    connection = get_db()
    connection.execute(
        """
        UPDATE users
        SET password_hash = ?, must_change_password = 0, status = 'active',
            session_version = session_version + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (generate_password_hash(new_password), g.user["id"]),
    )
    audit("password.changed", target_user_id=g.user["id"])
    connection.commit()
    refresh_current_user()
    session["session_version"] = g.user["session_version"]
    return jsonify(
        {"success": True, "message": translate("密码已更新，其他会话已撤销")}
    )
