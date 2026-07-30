from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from . import admin, auth, cli, db, public, security, studio
from .settings import get_site_copy


def persistent_secret(data_root: Path) -> str:
    configured = os.environ.get("FABULA_SECRET_KEY")
    if configured:
        return configured
    secret_path = data_root / "secret.key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    data_root.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return secret_path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
        secret_file.write(value)
    return value


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    configured_data_root = (
        test_config.get("DATA_ROOT")
        if test_config and test_config.get("DATA_ROOT")
        else os.environ.get("FABULA_DATA_DIR", project_root / "var")
    )
    data_root = Path(configured_data_root).resolve()
    media_root = data_root / "media"
    temp_root = data_root / "tmp"
    secret_key = (
        test_config.get("SECRET_KEY")
        if test_config and test_config.get("SECRET_KEY")
        else persistent_secret(data_root)
    )

    app = Flask(__name__, instance_relative_config=False)
    app.config.from_mapping(
        SECRET_KEY=secret_key,
        DATABASE_PATH=data_root / "fabula.db",
        MEDIA_ROOT=media_root,
        TEMP_ROOT=temp_root,
        MAX_CONTENT_LENGTH=int(os.environ.get("FABULA_MAX_UPLOAD_MB", "25")) * 1024 * 1024,
        SESSION_COOKIE_NAME="fabula_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FABULA_SECURE_COOKIE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        LOGIN_MAX_ATTEMPTS=int(os.environ.get("FABULA_LOGIN_MAX_ATTEMPTS", "5")),
        LOGIN_WINDOW_SECONDS=int(os.environ.get("FABULA_LOGIN_WINDOW_SECONDS", "900")),
        TRUST_PROXY_HEADERS=os.environ.get("FABULA_TRUST_PROXY_HEADERS", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)

    for directory in (
        Path(app.config["DATABASE_PATH"]).parent,
        Path(app.config["MEDIA_ROOT"]) / "original",
        Path(app.config["MEDIA_ROOT"]) / "thumbs",
        Path(app.config["TEMP_ROOT"]),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    security.init_app(app)
    cli.init_app(app)
    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(studio.bp)
    app.register_blueprint(admin.bp)

    @app.context_processor
    def inject_brand_title():
        return {"brand_title": get_site_copy()["site_title"]}

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.errorhandler(400)
    def bad_request(_error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "请求无效"}), 400
        return render_template("error.html", code=400, message="请求无法完成。"), 400

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "没有执行此操作的权限"}), 403
        return render_template("error.html", code=403, message="你没有访问这个页面的权限。"), 403

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "内容不存在"}), 404
        return render_template("error.html", code=404, message="没有找到这个页面。"), 404

    @app.errorhandler(413)
    def too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "图片超过上传大小限制"}), 413
        return render_template("error.html", code=413, message="上传文件超过大小限制。"), 413

    return app
