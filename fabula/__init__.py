from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, url_for
from werkzeug.security import generate_password_hash

from . import admin, auth, cli, db, i18n, public, security, studio
from .i18n import translate
from .media import HARD_MAX_IMAGE_PIXELS, drain_media_deletions
from .settings import get_site_copy, get_site_images


def _bounded_integer(value: object, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return parsed


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
    site_media_root = data_root / "site"
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
        SITE_MEDIA_ROOT=site_media_root,
        TEMP_ROOT=temp_root,
        MAX_CONTENT_LENGTH=int(os.environ.get("FABULA_MAX_UPLOAD_MB", "25")) * 1024 * 1024,
        SESSION_COOKIE_NAME="fabula_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FABULA_SECURE_COOKIE", "false").lower() == "true",
        ENVIRONMENT=os.environ.get("FABULA_ENV", "development").strip().lower(),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        LOGIN_MAX_ATTEMPTS=int(os.environ.get("FABULA_LOGIN_MAX_ATTEMPTS", "5")),
        LOGIN_WINDOW_SECONDS=int(os.environ.get("FABULA_LOGIN_WINDOW_SECONDS", "900")),
        TRUST_PROXY_HEADERS=os.environ.get("FABULA_TRUST_PROXY_HEADERS", "false").lower() == "true",
        TURNSTILE_SITE_KEY=os.environ.get("FABULA_TURNSTILE_SITE_KEY", "").strip(),
        TURNSTILE_SECRET_KEY=os.environ.get("FABULA_TURNSTILE_SECRET_KEY", "").strip(),
        TURNSTILE_EXPECTED_HOSTNAMES=os.environ.get(
            "FABULA_TURNSTILE_EXPECTED_HOSTNAMES", ""
        ),
        TURNSTILE_ACTION="login",
        TURNSTILE_TIMEOUT_SECONDS=float(
            os.environ.get("FABULA_TURNSTILE_TIMEOUT_SECONDS", "5")
        ),
        TURNSTILE_VERIFIER=None,
        TEMPORARY_PASSWORD_TTL_SECONDS=int(
            os.environ.get("FABULA_TEMPORARY_PASSWORD_TTL_SECONDS", "900")
        ),
        MAX_IMAGE_PIXELS=int(
            os.environ.get("FABULA_MAX_IMAGE_PIXELS", str(HARD_MAX_IMAGE_PIXELS))
        ),
        MAX_IMAGE_DIMENSION=int(
            os.environ.get("FABULA_MAX_IMAGE_DIMENSION", "12000")
        ),
        DUMMY_PASSWORD_HASH=generate_password_hash(secrets.token_urlsafe(32)),
    )
    if test_config:
        app.config.update(test_config)

    environment = str(app.config["ENVIRONMENT"]).strip().lower()
    if environment not in {"development", "production", "test"}:
        raise RuntimeError("FABULA_ENV must be development, production, or test")
    if environment == "production" and not app.config["SESSION_COOKIE_SECURE"]:
        raise RuntimeError("FABULA_SECURE_COOKIE must be true in production")
    app.config["ENVIRONMENT"] = environment

    turnstile_site_key = str(app.config["TURNSTILE_SITE_KEY"]).strip()
    turnstile_secret_key = str(app.config["TURNSTILE_SECRET_KEY"]).strip()
    if bool(turnstile_site_key) != bool(turnstile_secret_key):
        raise RuntimeError(
            "FABULA_TURNSTILE_SITE_KEY and FABULA_TURNSTILE_SECRET_KEY must be configured together"
        )
    turnstile_timeout = float(app.config["TURNSTILE_TIMEOUT_SECONDS"])
    if not 1 <= turnstile_timeout <= 30:
        raise RuntimeError(
            "FABULA_TURNSTILE_TIMEOUT_SECONDS must be between 1 and 30"
        )
    expected_hostnames = app.config["TURNSTILE_EXPECTED_HOSTNAMES"]
    if isinstance(expected_hostnames, str):
        expected_hostnames = {
            hostname.strip().lower()
            for hostname in expected_hostnames.split(",")
            if hostname.strip()
        }
    else:
        expected_hostnames = {
            str(hostname).strip().lower()
            for hostname in expected_hostnames
            if str(hostname).strip()
        }
    if turnstile_site_key and not expected_hostnames:
        raise RuntimeError(
            "FABULA_TURNSTILE_EXPECTED_HOSTNAMES is required when Turnstile is enabled"
        )
    app.config.update(
        TURNSTILE_SITE_KEY=turnstile_site_key,
        TURNSTILE_SECRET_KEY=turnstile_secret_key,
        TURNSTILE_EXPECTED_HOSTNAMES=frozenset(expected_hostnames),
        TURNSTILE_TIMEOUT_SECONDS=turnstile_timeout,
        TEMPORARY_PASSWORD_TTL_SECONDS=_bounded_integer(
            app.config["TEMPORARY_PASSWORD_TTL_SECONDS"],
            "FABULA_TEMPORARY_PASSWORD_TTL_SECONDS",
            60,
            86_400,
        ),
        MAX_IMAGE_PIXELS=_bounded_integer(
            app.config["MAX_IMAGE_PIXELS"],
            "FABULA_MAX_IMAGE_PIXELS",
            1_024,
            HARD_MAX_IMAGE_PIXELS,
        ),
        MAX_IMAGE_DIMENSION=_bounded_integer(
            app.config["MAX_IMAGE_DIMENSION"],
            "FABULA_MAX_IMAGE_DIMENSION",
            32,
            12_000,
        ),
    )

    for directory in (
        Path(app.config["DATABASE_PATH"]).parent,
        Path(app.config["MEDIA_ROOT"]) / "original",
        Path(app.config["MEDIA_ROOT"]) / "thumbs",
        Path(app.config["SITE_MEDIA_ROOT"]),
        Path(app.config["TEMP_ROOT"]),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        drain_media_deletions()
    security.init_app(app)
    i18n.init_app(app)
    cli.init_app(app)
    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(studio.bp)
    app.register_blueprint(admin.bp)

    @app.context_processor
    def inject_site_context():
        site_copy = get_site_copy()
        needs_site_images = request.endpoint in {"auth.login", "public.index"} or (
            request.endpoint == "studio.workspace"
            and getattr(g, "user", None) is not None
            and g.user["role"] == "admin"
        )
        configured_images = (
            get_site_images()
            if needs_site_images
            else {"home": None, "login": None}
        )
        needs_home_default = request.endpoint == "public.index" or (
            request.endpoint == "studio.workspace"
            and getattr(g, "user", None) is not None
            and g.user["role"] == "admin"
        )
        latest_photo = (
            db.get_db().execute(
                """
                SELECT p.storage_name
                FROM photos p
                JOIN albums a ON a.id = p.album_id AND a.user_id = p.user_id
                WHERE p.status = 'ready' AND a.status = 'published'
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 1
                """
            ).fetchone()
            if needs_home_default
            else None
        )
        default_home_url = (
            url_for(
                "public.media_file",
                variant="original",
                storage_name=latest_photo["storage_name"],
            )
            if latest_photo is not None
            else None
        )
        default_login_url = url_for("static", filename="images/login.webp")

        def image_context(slot: str, default_url: str | None) -> dict:
            storage_name = configured_images[slot]
            custom_url = (
                url_for(
                    "public.site_media_file",
                    slot=slot,
                    storage_name=storage_name,
                )
                if storage_name
                else None
            )
            return {
                "url": custom_url or default_url,
                "default_url": default_url,
                "custom": bool(custom_url),
            }

        return {
            "brand_title": site_copy["site_title"],
            "site_palette": site_copy["color_scheme"],
            "site_images": {
                "home": image_context("home", default_home_url),
                "login": image_context("login", default_login_url),
            },
        }

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/readyz")
    def readyz():
        try:
            db.get_db().execute("SELECT 1").fetchone()
            data_paths = (
                Path(app.config["DATABASE_PATH"]).parent,
                Path(app.config["MEDIA_ROOT"]),
                Path(app.config["SITE_MEDIA_ROOT"]),
                Path(app.config["TEMP_ROOT"]),
            )
            if not all(os.access(path, os.W_OK | os.X_OK) for path in data_paths):
                raise OSError("a required data path is not writable")
        except (OSError, sqlite3.Error):
            app.logger.exception("Readiness check failed")
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ready"})

    @app.errorhandler(400)
    def bad_request(_error):
        if security.wants_json():
            return jsonify({"success": False, "message": translate("请求无效")}), 400
        return render_template(
            "error.html", code=400, message=translate("请求无法完成。")
        ), 400

    @app.errorhandler(403)
    def forbidden(_error):
        if security.wants_json():
            return jsonify(
                {"success": False, "message": translate("没有执行此操作的权限")}
            ), 403
        return render_template(
            "error.html", code=403, message=translate("你没有访问这个页面的权限。")
        ), 403

    @app.errorhandler(404)
    def not_found(_error):
        if security.wants_json():
            return jsonify({"success": False, "message": translate("内容不存在")}), 404
        return render_template(
            "error.html", code=404, message=translate("没有找到这个页面。")
        ), 404

    @app.errorhandler(413)
    def too_large(_error):
        if security.wants_json():
            return jsonify(
                {"success": False, "message": translate("图片超过上传大小限制")}
            ), 413
        return render_template(
            "error.html", code=413, message=translate("上传文件超过大小限制。")
        ), 413

    return app
