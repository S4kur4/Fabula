from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from .db import get_db


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{3,32}$")


def valid_username(value: str) -> bool:
    return bool(USERNAME_PATTERN.fullmatch(value))


def valid_password(value: str) -> bool:
    return (
        len(value) >= 12
        and any(character.isalpha() for character in value)
        and any(character.isdigit() for character in value)
    )


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> bool:
    supplied = request.headers.get("X-CSRF-Token")
    if not supplied:
        supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


def wants_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def api_error(message: str, status: int = 400):
    return jsonify({"success": False, "message": message}), status


def load_logged_in_user() -> None:
    g.user = None
    user_id = session.get("user_id")
    if not user_id:
        return
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if (
        user is None
        or user["status"] == "inactive"
        or user["session_version"] != session.get("session_version")
    ):
        session.clear()
        return
    g.user = user


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            if wants_json():
                return api_error("需要登录后继续", 401)
            return redirect(url_for("auth.login", next=request.full_path))
        return view(**kwargs)

    return wrapped


def password_ready(view):
    @wraps(view)
    @login_required
    def wrapped(**kwargs):
        if g.user["must_change_password"]:
            if wants_json():
                return api_error("请先更换一次性临时密码", 403)
            flash("请先更换一次性临时密码", "warning")
            return redirect(url_for("studio.workspace", tab="security"))
        return view(**kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @password_ready
    def wrapped(**kwargs):
        if g.user["role"] != "admin":
            if wants_json():
                return api_error("只有管理员可以执行此操作", 403)
            abort(403)
        return view(**kwargs)

    return wrapped


def safe_next_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return None
    return value


def client_address() -> str:
    if current_app.config["TRUST_PROXY_HEADERS"]:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def login_fingerprint(username: str) -> str:
    secret = current_app.secret_key.encode("utf-8")
    payload = f"{client_address()}|{username.casefold()}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def login_is_limited(fingerprint: str) -> bool:
    now = int(time.time())
    cutoff = now - current_app.config["LOGIN_WINDOW_SECONDS"]
    connection = get_db()
    connection.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
    count = connection.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE fingerprint = ? AND attempted_at >= ?",
        (fingerprint, cutoff),
    ).fetchone()[0]
    connection.commit()
    return count >= current_app.config["LOGIN_MAX_ATTEMPTS"]


def record_failed_login(fingerprint: str) -> None:
    connection = get_db()
    connection.execute(
        "INSERT INTO login_attempts (fingerprint, attempted_at) VALUES (?, ?)",
        (fingerprint, int(time.time())),
    )
    connection.commit()


def clear_failed_logins(fingerprint: str) -> None:
    connection = get_db()
    connection.execute("DELETE FROM login_attempts WHERE fingerprint = ?", (fingerprint,))
    connection.commit()


def audit(action: str, target_user_id: int | None = None, details: dict | None = None) -> None:
    connection = get_db()
    actor_id = g.user["id"] if getattr(g, "user", None) is not None else None
    connection.execute(
        """
        INSERT INTO audit_events (actor_user_id, target_user_id, action, details_json)
        VALUES (?, ?, ?, ?)
        """,
        (actor_id, target_user_id, action, json.dumps(details or {}, ensure_ascii=False)),
    )


def refresh_current_user() -> None:
    if g.user is None:
        return
    g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    session["session_version"] = g.user["session_version"]


def init_app(app) -> None:
    app.before_request(load_logged_in_user)

    @app.before_request
    def protect_unsafe_methods():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not validate_csrf():
            if wants_json():
                return api_error("安全令牌已失效，请刷新页面后重试", 400)
            abort(400)
        return None

    @app.context_processor
    def inject_security_context():
        return {"csrf_token": csrf_token, "current_user": getattr(g, "user", None)}

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "img-src 'self' blob: data:; "
            "object-src 'none'; "
            "script-src 'self'; "
            "style-src 'self'",
        )
        if request.path.startswith(("/studio", "/api/", "/login")):
            response.headers["Cache-Control"] = "no-store"
        return response
