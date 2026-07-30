from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from .db import get_db
from .i18n import translate
from .security import (
    clear_failed_logins,
    client_address,
    login_fingerprint,
    login_is_limited,
    record_failed_login,
    safe_next_url,
)
from .settings import get_site_copy
from .turnstile import is_enabled, verify_token


bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None and request.method == "GET":
        return redirect(url_for("studio.workspace"))

    error = None
    username = request.form.get("username", "").strip()
    if request.method == "POST":
        fingerprint = login_fingerprint(username)
        if login_is_limited(fingerprint):
            error = translate("登录尝试过多，请稍后再试。")
        else:
            turnstile_valid, turnstile_reason = verify_token(
                request.form.get("cf-turnstile-response", ""),
                client_address(),
            )
            if not turnstile_valid:
                record_failed_login(fingerprint)
                if turnstile_reason == "siteverify-unavailable":
                    error = translate("人机验证暂时不可用，请稍后再试。")
                else:
                    error = translate("请完成人机验证后重试。")
            else:
                user = get_db().execute(
                    "SELECT * FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
                valid = (
                    user is not None
                    and user["status"] != "inactive"
                    and check_password_hash(
                        user["password_hash"], request.form.get("password", "")
                    )
                )
                if not valid:
                    record_failed_login(fingerprint)
                    error = translate("账号或密码不正确。")
                else:
                    clear_failed_logins(fingerprint)
                    connection = get_db()
                    if user["status"] == "pending":
                        connection.execute(
                            """
                            UPDATE users
                            SET status = 'active', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE id = ?
                            """,
                            (user["id"],),
                        )
                    connection.execute(
                        """
                        UPDATE users
                        SET last_login_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE id = ?
                        """,
                        (user["id"],),
                    )
                    connection.commit()
                    session.clear()
                    session["user_id"] = user["id"]
                    session["session_version"] = user["session_version"]
                    session["locale"] = user["locale"]
                    session.permanent = True
                    next_url = safe_next_url(request.args.get("next"))
                    if user["must_change_password"]:
                        flash(
                            translate("请先更换一次性临时密码"),
                            "warning",
                        )
                        return redirect(url_for("studio.workspace", tab="security"))
                    return redirect(next_url or url_for("studio.workspace"))

    return render_template(
        "login.html",
        error=error,
        username=username,
        site_copy=get_site_copy(),
        turnstile_enabled=is_enabled(),
        turnstile_site_key=current_app.config.get("TURNSTILE_SITE_KEY", ""),
    )


@bp.post("/logout")
def logout():
    locale = session.get("locale", "zh-CN")
    session.clear()
    session["locale"] = locale
    return redirect(url_for("public.index"))
