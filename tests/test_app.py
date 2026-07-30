from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.security import generate_password_hash

from fabula import create_app
from fabula.cli import bootstrap_admin
from fabula.db import get_db


CSRF_PATTERN = re.compile(rb'<meta name="csrf-token" content="([^"]+)">')


class FabulaTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary_directory.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_ROOT": self.data_root,
                "SECRET_KEY": "test-secret-key",
                "DATABASE_PATH": self.data_root / "fabula.db",
                "MEDIA_ROOT": self.data_root / "media",
                "TEMP_ROOT": self.data_root / "tmp",
                "LOGIN_MAX_ATTEMPTS": 20,
                "TURNSTILE_SITE_KEY": "",
                "TURNSTILE_SECRET_KEY": "",
                "TURNSTILE_EXPECTED_HOSTNAMES": "",
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            connection = get_db()
            self.admin_id = self._insert_user(
                connection, "admin.user", "管理员", "admin", "admin-password-2026"
            )
            self.user_one_id = self._insert_user(
                connection, "user.one", "摄影师一", "photographer", "user-password-2026"
            )
            self.user_two_id = self._insert_user(
                connection, "user.two", "摄影师二", "photographer", "user-password-2026"
            )
            self.album_one_id = connection.execute(
                "INSERT INTO albums (user_id, name) VALUES (?, '第一册')",
                (self.user_one_id,),
            ).lastrowid
            self.album_two_id = connection.execute(
                "INSERT INTO albums (user_id, name) VALUES (?, '第二册')",
                (self.user_two_id,),
            ).lastrowid
            self.photo_one_id = self._insert_photo(
                connection,
                self.user_one_id,
                self.album_one_id,
                "a" * 32 + ".webp",
                "所有者的照片",
            )
            self.photo_two_id = self._insert_photo(
                connection,
                self.user_two_id,
                self.album_two_id,
                "b" * 32 + ".webp",
                "他人的照片",
            )
            connection.execute(
                """
                INSERT INTO about_blocks (user_id, title, bio)
                VALUES (?, '看见日常', '只属于摄影师一的介绍')
                """,
                (self.user_one_id,),
            )
            connection.commit()

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _insert_user(connection, username, display_name, role, password):
        return connection.execute(
            """
            INSERT INTO users (
                username, display_name, role, status, password_hash,
                must_change_password
            ) VALUES (?, ?, ?, 'active', ?, 0)
            """,
            (username, display_name, role, generate_password_hash(password)),
        ).lastrowid

    @staticmethod
    def _insert_photo(connection, user_id, album_id, storage_name, title):
        return connection.execute(
            """
            INSERT INTO photos (
                user_id, album_id, storage_name, original_name, title, story,
                width, height, size_bytes
            ) VALUES (?, ?, ?, 'test.webp', ?, '测试故事背景', 1200, 800, 1024)
            """,
            (user_id, album_id, storage_name, title),
        ).lastrowid

    def csrf_from(self, response):
        match = CSRF_PATTERN.search(response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def login(self, username, password):
        login_page = self.client.get("/login")
        token = self.csrf_from(login_page)
        response = self.client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        studio_page = self.client.get("/studio")
        self.assertEqual(studio_page.status_code, 200)
        return self.csrf_from(studio_page)

    def api(self, method, path, token, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-CSRF-Token"] = token
        return self.client.open(path, method=method, headers=headers, **kwargs)

    def test_public_page_aggregates_ready_content_and_about(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("所有者的照片", html)
        self.assertIn("只属于摄影师一的介绍", html)
        self.assertIn("登录", html)
        self.assertIn('rel="icon"', html)
        self.assertIn('data-palette="cinnabar"', html)
        self.assertNotIn("共同影像档案", html)
        self.assertNotIn("data-lightbox-fullscreen", html)

    def test_login_image_caption_is_removed_but_configurable_intro_remains(self):
        login_page = self.client.get("/login")
        login_html = login_page.get_data(as_text=True)
        self.assertIn('class="login-intro"', login_html)
        self.assertIn("进入只属于你的工作台", login_html)
        self.assertNotIn("整理照片，也是重新确认自己站在哪里。", login_html)

        token = self.login("admin.user", "admin-password-2026")
        site_copy = self.api("GET", "/api/admin/site-copy", token).get_json()["site_copy"]
        self.assertIn("login_intro", site_copy)
        studio_html = self.client.get("/studio?tab=site-copy").get_data(as_text=True)
        self.assertIn("登录页简介", studio_html)
        self.assertIn("copy-login-intro", studio_html)

    def test_empty_photo_state_uses_album_copy(self):
        self.login("admin.user", "admin-password-2026")
        studio_html = self.client.get("/studio").get_data(as_text=True)
        self.assertIn("你的摄影集还是空的", studio_html)
        self.assertNotIn("你的档案还是空的", studio_html)

    def test_health_endpoint_and_security_headers(self):
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json(), {"status": "ok"})
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_owner_can_edit_own_photo_but_not_another_users_photo(self):
        token = self.login("user.one", "user-password-2026")
        own_response = self.api(
            "PATCH",
            f"/studio/api/photos/{self.photo_one_id}",
            token,
            json={"title": "新的标题", "story": "新的故事", "album_id": self.album_one_id},
        )
        self.assertEqual(own_response.status_code, 200)
        foreign_response = self.api(
            "PATCH",
            f"/studio/api/photos/{self.photo_two_id}",
            token,
            json={"title": "越权修改", "story": "", "album_id": ""},
        )
        self.assertEqual(foreign_response.status_code, 404)
        with self.app.app_context():
            title = get_db().execute(
                "SELECT title FROM photos WHERE id = ?", (self.photo_two_id,)
            ).fetchone()[0]
            self.assertEqual(title, "他人的照片")

    def test_foreign_album_rejected_before_image_processing(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={
                "album_id": str(self.album_two_id),
                "photo": (BytesIO(b"not-an-image"), "test.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)

    def test_database_also_rejects_cross_owner_album_relation(self):
        with self.app.app_context():
            connection = get_db()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO photos (
                        user_id, album_id, storage_name, original_name, title
                    ) VALUES (?, ?, ?, 'cross.webp', '数据库边界')
                    """,
                    (self.user_one_id, self.album_two_id, "c" * 32 + ".webp"),
                )
            connection.rollback()

    def test_album_delete_can_keep_photos_as_uncategorized(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "DELETE",
            f"/studio/api/albums/{self.album_one_id}",
            token,
            json={"delete_photos": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("已移到未分类", response.get_json()["message"])
        with self.app.app_context():
            connection = get_db()
            album = connection.execute(
                "SELECT id FROM albums WHERE id = ?", (self.album_one_id,)
            ).fetchone()
            photo = connection.execute(
                "SELECT album_id FROM photos WHERE id = ?", (self.photo_one_id,)
            ).fetchone()
            self.assertIsNone(album)
            self.assertIsNotNone(photo)
            self.assertIsNone(photo["album_id"])

    def test_album_delete_can_remove_owned_photos(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "DELETE",
            f"/studio/api/albums/{self.album_one_id}",
            token,
            json={"delete_photos": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_photos"], 1)
        with self.app.app_context():
            connection = get_db()
            album = connection.execute(
                "SELECT id FROM albums WHERE id = ?", (self.album_one_id,)
            ).fetchone()
            photo = connection.execute(
                "SELECT id FROM photos WHERE id = ?", (self.photo_one_id,)
            ).fetchone()
            self.assertIsNone(album)
            self.assertIsNone(photo)

    def test_album_delete_cannot_target_another_users_album(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "DELETE",
            f"/studio/api/albums/{self.album_two_id}",
            token,
            json={"delete_photos": True},
        )
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            connection = get_db()
            self.assertIsNotNone(
                connection.execute(
                    "SELECT id FROM albums WHERE id = ?", (self.album_two_id,)
                ).fetchone()
            )
            self.assertIsNotNone(
                connection.execute(
                    "SELECT id FROM photos WHERE id = ?", (self.photo_two_id,)
                ).fetchone()
            )

    def test_workspace_uses_album_first_chinese_navigation(self):
        self.login("user.one", "user-password-2026")
        response = self.client.get("/studio?tab=about")
        html = response.get_data(as_text=True)
        self.assertLess(html.index("我的摄影集"), html.index("个人空间"))
        self.assertIn("我的介绍", html)
        self.assertIn("账户安全", html)
        self.assertIn("<h1>我的介绍</h1>", html)
        self.assertIn("<h1>账户安全</h1>", html)
        self.assertIn('<h1 id="photo-panel-title">全部照片</h1>', html)
        self.assertNotIn('data-studio-tab="photos"', html)
        self.assertNotIn("你的介绍段落", html)
        self.assertNotIn("上传到本摄影集", html)
        self.assertIn("编辑或删除", html)

    def test_language_switch_is_saved_and_keeps_custom_content_unchanged(self):
        token = self.login("user.one", "user-password-2026")
        chinese_page = self.client.get("/studio?tab=about")
        chinese_html = chinese_page.get_data(as_text=True)
        self.assertIn('<html lang="zh-CN"', chinese_html)
        self.assertIn('action="/studio/locale"', chinese_html)
        self.assertIn('value="en"', chinese_html)
        self.assertIn(">English</button>", chinese_html)

        response = self.client.post(
            "/studio/locale",
            data={
                "csrf_token": token,
                "locale": "en",
                "next": "/studio?tab=about",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/studio?tab=about"))

        english_page = self.client.get("/studio?tab=about")
        english_html = english_page.get_data(as_text=True)
        self.assertIn('<html lang="en"', english_html)
        self.assertIn("<h1>My profile</h1>", english_html)
        self.assertIn(">My albums<", english_html)
        self.assertIn(">Account security<", english_html)
        self.assertIn(">中文</button>", english_html)
        self.assertIn("看见日常", english_html)
        self.assertIn("只属于摄影师一的介绍", english_html)

        english_token = self.csrf_from(english_page)
        api_response = self.api(
            "POST",
            "/studio/api/albums",
            english_token,
            json={"name": ""},
        )
        self.assertEqual(api_response.status_code, 400)
        self.assertEqual(
            api_response.get_json()["message"],
            "Album name must contain 1 to 40 characters.",
        )
        with self.app.app_context():
            locale = get_db().execute(
                "SELECT locale FROM users WHERE id = ?", (self.user_one_id,)
            ).fetchone()["locale"]
            self.assertEqual(locale, "en")

        logout_response = self.client.post(
            "/logout",
            data={"csrf_token": english_token},
        )
        self.assertEqual(logout_response.status_code, 302)
        logged_out_page = self.client.get("/login").get_data(as_text=True)
        self.assertIn('<html lang="en"', logged_out_page)
        self.assertIn(">Username<", logged_out_page)
        self.assertIn("进入只属于你的工作台", logged_out_page)

    def test_invalid_language_is_rejected_without_changing_preference(self):
        token = self.login("user.one", "user-password-2026")
        response = self.client.post(
            "/studio/locale",
            data={
                "csrf_token": token,
                "locale": "fr",
                "next": "/studio",
            },
        )
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            locale = get_db().execute(
                "SELECT locale FROM users WHERE id = ?", (self.user_one_id,)
            ).fetchone()["locale"]
            self.assertEqual(locale, "zh-CN")

    def test_turnstile_is_verified_server_side_before_login(self):
        calls = []

        def verifier(token, remote_ip):
            calls.append((token, remote_ip))
            return {
                "success": token == "valid-token",
                "action": "login",
                "hostname": "TEST.LOCAL",
            }

        self.app.config.update(
            TURNSTILE_SITE_KEY="test-site-key",
            TURNSTILE_SECRET_KEY="test-secret-key",
            TURNSTILE_EXPECTED_HOSTNAMES=frozenset({"test.local"}),
            TURNSTILE_VERIFIER=verifier,
        )
        login_page = self.client.get("/login")
        login_html = login_page.get_data(as_text=True)
        token = self.csrf_from(login_page)
        self.assertIn("https://challenges.cloudflare.com/turnstile/v0/api.js", login_html)
        self.assertIn('class="cf-turnstile"', login_html)
        self.assertIn('data-action="login"', login_html)
        csp = login_page.headers["Content-Security-Policy"]
        self.assertIn(
            "script-src 'self' https://challenges.cloudflare.com",
            csp,
        )
        self.assertIn("frame-src https://challenges.cloudflare.com", csp)

        missing = self.client.post(
            "/login",
            data={
                "username": "user.one",
                "password": "user-password-2026",
                "csrf_token": token,
            },
        )
        self.assertEqual(missing.status_code, 200)
        self.assertIn("请完成人机验证后重试。", missing.get_data(as_text=True))
        self.assertEqual(calls, [])

        rejected = self.client.post(
            "/login",
            data={
                "username": "user.one",
                "password": "user-password-2026",
                "csrf_token": token,
                "cf-turnstile-response": "invalid-token",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertIn("请完成人机验证后重试。", rejected.get_data(as_text=True))

        accepted = self.client.post(
            "/login",
            data={
                "username": "user.one",
                "password": "user-password-2026",
                "csrf_token": token,
                "cf-turnstile-response": "valid-token",
            },
        )
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(
            calls,
            [
                ("invalid-token", "127.0.0.1"),
                ("valid-token", "127.0.0.1"),
            ],
        )

    def test_turnstile_rejects_action_and_hostname_mismatches(self):
        responses = {
            "wrong-action": {
                "success": True,
                "action": "other",
                "hostname": "test.local",
            },
            "wrong-hostname": {
                "success": True,
                "action": "login",
                "hostname": "attacker.example",
            },
        }
        self.app.config.update(
            TURNSTILE_SITE_KEY="test-site-key",
            TURNSTILE_SECRET_KEY="test-secret-key",
            TURNSTILE_EXPECTED_HOSTNAMES=frozenset({"test.local"}),
            TURNSTILE_VERIFIER=lambda token, _remote_ip: responses[token],
        )
        login_page = self.client.get("/login")
        csrf_token = self.csrf_from(login_page)
        for turnstile_token in responses:
            with self.subTest(turnstile_token=turnstile_token):
                response = self.client.post(
                    "/login",
                    data={
                        "username": "user.one",
                        "password": "user-password-2026",
                        "csrf_token": csrf_token,
                        "cf-turnstile-response": turnstile_token,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    "请完成人机验证后重试。",
                    response.get_data(as_text=True),
                )

    def test_regular_user_cannot_access_admin_api(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api("GET", "/api/admin/users", token)
        self.assertEqual(response.status_code, 403)

    def test_admin_role_does_not_override_photo_ownership(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "PATCH",
            f"/studio/api/photos/{self.photo_one_id}",
            token,
            json={"title": "管理员越权", "story": "", "album_id": ""},
        )
        self.assertEqual(response.status_code, 404)

    def test_last_active_admin_cannot_be_demoted(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "PATCH",
            f"/api/admin/users/{self.admin_id}",
            token,
            json={"display_name": "管理员", "role": "photographer"},
        )
        self.assertEqual(response.status_code, 409)

    def test_user_with_content_cannot_be_deleted(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "DELETE",
            f"/api/admin/users/{self.user_one_id}",
            token,
        )
        self.assertEqual(response.status_code, 409)

    def test_admin_can_create_pending_user_with_forced_password_change(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "POST",
            "/api/admin/users",
            token,
            json={
                "username": "new.user",
                "display_name": "新摄影师",
                "role": "photographer",
                "temporary_password": "temporary-2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        user = response.get_json()["user"]
        self.assertEqual(user["status"], "pending")
        self.assertTrue(user["must_change_password"])
        self.assertEqual(user["role"], "photographer")

    def test_admin_can_update_public_copy(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "PUT",
            "/api/admin/site-copy",
            token,
            json={
                "site_title": "浮光",
                "hero_before": "光落在这里，",
                "hero_accent": "时间",
                "color_scheme": "celadon",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["site_copy"]["site_title"], "浮光")
        self.assertEqual(response.get_json()["site_copy"]["hero_accent"], "时间")
        self.assertEqual(response.get_json()["site_copy"]["color_scheme"], "celadon")
        public_page = self.client.get("/")
        public_html = public_page.get_data(as_text=True)
        self.assertIn("光落在这里", public_html)
        self.assertIn("<title>浮光</title>", public_html)
        self.assertIn('data-palette="celadon"', public_html)
        studio_html = self.client.get("/studio?tab=site-copy").get_data(as_text=True)
        self.assertIn("<h1>站点设置</h1>", studio_html)
        self.assertIn('name="site-color-scheme"', studio_html)
        self.assertIn('value="celadon" checked', studio_html)
        self.assertIn("<h1>用户管理</h1>", studio_html)

    def test_admin_cannot_save_an_unknown_site_palette(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "PUT",
            "/api/admin/site-copy",
            token,
            json={"color_scheme": "untrusted-css-value"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], "站点配色方案无效")
        public_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-palette="cinnabar"', public_html)
        self.assertNotIn("untrusted-css-value", public_html)

    def test_unsafe_request_without_csrf_is_rejected(self):
        self.login("user.one", "user-password-2026")
        response = self.client.patch(
            f"/studio/api/photos/{self.photo_one_id}",
            json={"title": "无令牌", "story": "", "album_id": ""},
        )
        self.assertEqual(response.status_code, 400)

    def test_password_change_revokes_other_sessions(self):
        second_client = self.app.test_client()
        token = self.login("user.one", "user-password-2026")

        second_login_page = second_client.get("/login")
        second_token = CSRF_PATTERN.search(second_login_page.data).group(1).decode()
        second_client.post(
            "/login",
            data={
                "username": "user.one",
                "password": "user-password-2026",
                "csrf_token": second_token,
            },
        )
        self.assertEqual(second_client.get("/studio").status_code, 200)

        response = self.api(
            "POST",
            "/studio/api/account/password",
            token,
            json={
                "current_password": "user-password-2026",
                "new_password": "changed-password-2026",
                "confirmation": "changed-password-2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        invalidated = second_client.get("/studio")
        self.assertEqual(invalidated.status_code, 302)
        self.assertIn("/login", invalidated.headers["Location"])


class BootstrapAdminTestCase(unittest.TestCase):
    def test_bootstrap_admin_is_one_time_and_not_implicit(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            app = create_app(
                {
                    "TESTING": True,
                    "DATA_ROOT": data_root,
                    "SECRET_KEY": "test-secret-key",
                    "DATABASE_PATH": data_root / "fabula.db",
                    "MEDIA_ROOT": data_root / "media",
                    "TEMP_ROOT": data_root / "tmp",
                    "TURNSTILE_SITE_KEY": "",
                    "TURNSTILE_SECRET_KEY": "",
                    "TURNSTILE_EXPECTED_HOSTNAMES": "",
                }
            )
            with app.app_context():
                bootstrap_admin("first.admin", "首位管理员", "initial-password-2026")
                user = get_db().execute("SELECT * FROM users").fetchone()
                self.assertEqual(user["role"], "admin")
                self.assertEqual(user["initial_admin"], 1)
                self.assertEqual(user["must_change_password"], 1)
                with self.assertRaises(Exception):
                    bootstrap_admin("second.admin", "第二位", "initial-password-2026")


class ApplicationConfigurationTestCase(unittest.TestCase):
    def app_config(self, data_root):
        return {
            "TESTING": True,
            "DATA_ROOT": data_root,
            "SECRET_KEY": "test-secret-key",
            "DATABASE_PATH": data_root / "fabula.db",
            "MEDIA_ROOT": data_root / "media",
            "TEMP_ROOT": data_root / "tmp",
            "TURNSTILE_SITE_KEY": "",
            "TURNSTILE_SECRET_KEY": "",
            "TURNSTILE_EXPECTED_HOSTNAMES": "",
        }

    def test_existing_database_gets_default_chinese_locale(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            database_path = data_root / "fabula.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'photographer',
                    status TEXT NOT NULL DEFAULT 'pending',
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    initial_admin INTEGER NOT NULL DEFAULT 0,
                    session_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TEXT
                );
                INSERT INTO users (
                    username, display_name, role, status, password_hash,
                    must_change_password
                ) VALUES (
                    'legacy.user', '旧用户', 'photographer', 'active',
                    'not-used-in-this-test', 0
                );
                """
            )
            connection.close()

            app = create_app(self.app_config(data_root))
            with app.app_context():
                migrated_user = get_db().execute(
                    "SELECT locale FROM users WHERE username = 'legacy.user'"
                ).fetchone()
                self.assertEqual(migrated_user["locale"], "zh-CN")

    def test_turnstile_keys_must_be_configured_together(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            config = self.app_config(data_root)
            config.update(
                TURNSTILE_SITE_KEY="test-site-key",
                TURNSTILE_SECRET_KEY="",
            )
            with self.assertRaisesRegex(RuntimeError, "must be configured together"):
                create_app(config)

    def test_turnstile_requires_expected_hostnames(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            config = self.app_config(data_root)
            config.update(
                TURNSTILE_SITE_KEY="test-site-key",
                TURNSTILE_SECRET_KEY="test-secret-key",
                TURNSTILE_EXPECTED_HOSTNAMES="",
            )
            with self.assertRaisesRegex(RuntimeError, "EXPECTED_HOSTNAMES is required"):
                create_app(config)

    def test_turnstile_timeout_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            config = self.app_config(data_root)
            config["TURNSTILE_TIMEOUT_SECONDS"] = 31
            with self.assertRaisesRegex(RuntimeError, "must be between 1 and 30"):
                create_app(config)


if __name__ == "__main__":
    unittest.main()
