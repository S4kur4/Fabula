from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from .db import get_db
from .i18n import translate
from .security import (
    admin_required,
    api_error,
    audit,
    refresh_current_user,
    valid_password,
    valid_username,
)
from .settings import SITE_PALETTES, get_site_copy, save_site_copy


bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def active_admin_count() -> int:
    return get_db().execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()[0]


def content_counts(user_id: int) -> dict:
    connection = get_db()
    return {
        "photos": connection.execute(
            "SELECT COUNT(*) FROM photos WHERE user_id = ?", (user_id,)
        ).fetchone()[0],
        "albums": connection.execute(
            "SELECT COUNT(*) FROM albums WHERE user_id = ?", (user_id,)
        ).fetchone()[0],
        "about": connection.execute(
            "SELECT COUNT(*) FROM about_blocks WHERE user_id = ?", (user_id,)
        ).fetchone()[0],
    }


def serialize_user(row) -> dict:
    counts = content_counts(row["id"])
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "must_change_password": bool(row["must_change_password"]),
        "initial_admin": bool(row["initial_admin"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "content": counts,
        "content_total": sum(counts.values()),
    }


@bp.get("/users")
@admin_required
def list_users():
    rows = get_db().execute("SELECT * FROM users ORDER BY id").fetchall()
    return jsonify({"items": [serialize_user(row) for row in rows]})


@bp.post("/users")
@admin_required
def create_user():
    values = request.get_json(silent=True) or {}
    username = str(values.get("username", "")).strip()
    display_name = str(values.get("display_name", "")).strip()[:80]
    role = str(values.get("role", "photographer"))
    temporary_password = str(values.get("temporary_password", ""))
    if not valid_username(username):
        return api_error(translate("用户名需为 3 到 32 位字母、数字、点或下划线"))
    if not display_name:
        return api_error(translate("公开显示名称不能为空"))
    if role not in {"photographer", "admin"}:
        return api_error(translate("用户角色无效"))
    if not valid_password(temporary_password):
        return api_error(translate("临时密码至少 12 个字符，并同时包含字母和数字"))
    connection = get_db()
    try:
        cursor = connection.execute(
            """
            INSERT INTO users (
                username, display_name, role, status, password_hash,
                must_change_password, initial_admin
            ) VALUES (?, ?, ?, 'pending', ?, 1, 0)
            """,
            (
                username,
                display_name,
                role,
                generate_password_hash(temporary_password),
            ),
        )
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            return api_error(translate("该用户名已经存在"))
        raise
    audit(
        "user.created",
        target_user_id=cursor.lastrowid,
        details={"role": role},
    )
    connection.commit()
    user = connection.execute(
        "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return jsonify({"success": True, "user": serialize_user(user)})


@bp.patch("/users/<int:user_id>")
@admin_required
def update_user(user_id: int):
    values = request.get_json(silent=True) or {}
    display_name = str(values.get("display_name", "")).strip()[:80]
    role = str(values.get("role", "photographer"))
    if not display_name:
        return api_error(translate("公开显示名称不能为空"))
    if role not in {"photographer", "admin"}:
        return api_error(translate("用户角色无效"))
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        connection.rollback()
        return api_error(translate("用户不存在"), 404)
    if (
        target["role"] == "admin"
        and target["status"] == "active"
        and role != "admin"
        and active_admin_count() <= 1
    ):
        connection.rollback()
        return api_error(translate("不能降级最后一位有效管理员"), 409)
    connection.execute(
        """
        UPDATE users
        SET display_name = ?, role = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (display_name, role, user_id),
    )
    audit(
        "user.updated",
        target_user_id=user_id,
        details={"old_role": target["role"], "new_role": role},
    )
    connection.commit()
    if user_id == g.user["id"]:
        refresh_current_user()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify({"success": True, "user": serialize_user(user)})


@bp.post("/users/<int:user_id>/status")
@admin_required
def update_status(user_id: int):
    values = request.get_json(silent=True) or {}
    status = str(values.get("status", ""))
    if status not in {"active", "inactive"}:
        return api_error(translate("账户状态无效"))
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        connection.rollback()
        return api_error(translate("用户不存在"), 404)
    if user_id == g.user["id"] and status == "inactive":
        connection.rollback()
        return api_error(translate("不能在当前会话中停用自己"), 409)
    if (
        target["role"] == "admin"
        and target["status"] == "active"
        and status == "inactive"
        and active_admin_count() <= 1
    ):
        connection.rollback()
        return api_error(translate("不能停用最后一位有效管理员"), 409)
    connection.execute(
        """
        UPDATE users
        SET status = ?, session_version = session_version + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (status, user_id),
    )
    audit(
        "user.status_changed",
        target_user_id=user_id,
        details={"old_status": target["status"], "new_status": status},
    )
    connection.commit()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify({"success": True, "user": serialize_user(user)})


@bp.post("/users/<int:user_id>/reset-password")
@admin_required
def reset_password(user_id: int):
    if user_id == g.user["id"]:
        return api_error(translate("请在账户安全页面修改自己的密码"), 409)
    values = request.get_json(silent=True) or {}
    temporary_password = str(values.get("temporary_password", ""))
    if not valid_password(temporary_password):
        return api_error(translate("临时密码至少 12 个字符，并同时包含字母和数字"))
    connection = get_db()
    target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        return api_error(translate("用户不存在"), 404)
    connection.execute(
        """
        UPDATE users
        SET password_hash = ?, must_change_password = 1,
            session_version = session_version + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (generate_password_hash(temporary_password), user_id),
    )
    audit("user.password_reset", target_user_id=user_id)
    connection.commit()
    return jsonify({"success": True, "message": translate("一次性临时密码已设置")})


@bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id: int):
    connection = get_db()
    connection.execute("BEGIN IMMEDIATE")
    target = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        connection.rollback()
        return api_error(translate("用户不存在"), 404)
    if user_id == g.user["id"]:
        connection.rollback()
        return api_error(translate("不能删除当前登录账号"), 409)
    if (
        target["role"] == "admin"
        and target["status"] == "active"
        and active_admin_count() <= 1
    ):
        connection.rollback()
        return api_error(translate("不能删除最后一位有效管理员"), 409)
    counts = content_counts(user_id)
    if sum(counts.values()) > 0:
        connection.rollback()
        return api_error(
            translate("该用户仍拥有内容，只能先停用，不能直接删除"), 409
        )
    audit(
        "user.deleted",
        target_user_id=user_id,
        details={"username": target["username"]},
    )
    connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.commit()
    return jsonify({"success": True, "message": translate("用户已删除")})


@bp.put("/site-copy")
@admin_required
def update_site_copy():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return api_error(translate("请求无效"))
    previous = get_site_copy()
    requested_palette = str(
        values.get("color_scheme", previous["color_scheme"])
    ).strip()
    if requested_palette not in SITE_PALETTES:
        return api_error(translate("站点配色方案无效"))
    values = {**values, "color_scheme": requested_palette}
    connection = get_db()
    saved = save_site_copy(values)
    audit(
        "site_copy.updated",
        details={
            "fields": sorted(saved),
            "old_color_scheme": previous["color_scheme"],
            "new_color_scheme": saved["color_scheme"],
        },
    )
    connection.commit()
    return jsonify({"success": True, "site_copy": saved})


@bp.get("/site-copy")
@admin_required
def read_site_copy():
    return jsonify({"site_copy": get_site_copy()})
