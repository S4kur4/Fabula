from __future__ import annotations

import re
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pillow_heif import options as heif_options
from werkzeug.security import check_password_hash, generate_password_hash

from fabula import create_app
from fabula.cli import bootstrap_admin
from fabula.db import get_db
from fabula.media import drain_media_deletions, process_image
from fabula.security import reserve_login_attempt


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

    @staticmethod
    def image_stream(width=120, height=180):
        stream = BytesIO()
        Image.new("RGB", (width, height), "#806f62").save(stream, "JPEG")
        stream.seek(0)
        return stream

    @staticmethod
    def heif_stream(width=120, height=180):
        stream = BytesIO()
        Image.new("RGB", (width, height), "#806f62").save(
            stream,
            "HEIF",
            quality=90,
        )
        stream.seek(0)
        return stream

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
        with self.app.app_context():
            get_db().execute(
                """
                UPDATE albums
                SET status = 'published', published_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self.album_one_id,),
            )
            get_db().execute(
                "UPDATE photos SET story = ? WHERE id = ?",
                ("第一段。\n\n第二段。", self.photo_one_id),
            )
            get_db().commit()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("所有者的照片", html)
        self.assertIn("只属于摄影师一的介绍", html)
        self.assertIn("登录", html)
        self.assertIn('rel="icon"', html)
        self.assertIn('data-palette="cinnabar"', html)
        self.assertNotIn("共同影像档案", html)
        self.assertEqual(html.count("影像版权归各自摄影师所有"), 2)
        self.assertNotIn("每一种声音都保留自己的方向", html)
        self.assertNotIn("data-lightbox-fullscreen", html)
        self.assertIn('draggable="false"', html)
        self.assertIn("第一段。\n\n第二段。", html)

        public_css_response = self.client.get("/static/css/app.css")
        public_css = public_css_response.get_data(as_text=True)
        public_css_response.close()
        self.assertIn(".public-site button,", public_css)
        self.assertIn(".public-site img {", public_css)
        self.assertIn(".lightbox-story {", public_css)
        self.assertIn("white-space: pre-wrap;", public_css)
        self.assertNotIn(".public-site {\n  -webkit-user-select: none", public_css)

    def test_empty_public_album_uses_upload_copy(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertIn("上传作品后，它们会出现在这里。", html)
        self.assertNotIn("摄影师发布作品后，它们会出现在这里。", html)

    def test_album_publication_controls_public_feed_and_media_access(self):
        storage_name = "a" * 32 + ".webp"
        original = self.data_root / "media" / "original" / storage_name
        original.write_bytes(b"private-draft-image")
        anonymous_client = self.app.test_client()

        self.assertEqual(
            anonymous_client.get("/api/public/photos").get_json()["total"],
            0,
        )
        self.assertEqual(
            anonymous_client.get(f"/media/original/{storage_name}").status_code,
            404,
        )

        token = self.login("user.one", "user-password-2026")
        private_media = self.client.get(f"/media/original/{storage_name}")
        self.assertEqual(private_media.status_code, 200)
        self.assertEqual(private_media.headers["Cache-Control"], "private, no-store")
        private_media.close()

        published = self.api(
            "PATCH",
            f"/studio/api/albums/{self.album_one_id}/publication",
            token,
            json={"status": "published"},
        )
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.get_json()["album"]["status"], "published")
        self.assertIsNotNone(published.get_json()["album"]["published_at"])
        public_feed = anonymous_client.get("/api/public/photos").get_json()
        self.assertEqual(public_feed["total"], 1)
        self.assertEqual(public_feed["items"][0]["id"], self.photo_one_id)
        public_media = anonymous_client.get(f"/media/original/{storage_name}")
        self.assertEqual(public_media.status_code, 200)
        self.assertEqual(
            public_media.headers["Cache-Control"],
            "public, max-age=0, must-revalidate",
        )
        public_media.close()

        unpublished = self.api(
            "PATCH",
            f"/studio/api/albums/{self.album_one_id}/publication",
            token,
            json={"status": "draft"},
        )
        self.assertEqual(unpublished.status_code, 200)
        self.assertEqual(unpublished.get_json()["album"]["status"], "draft")
        self.assertIsNone(unpublished.get_json()["album"]["published_at"])
        self.assertEqual(
            anonymous_client.get("/api/public/photos").get_json()["total"],
            0,
        )
        self.assertEqual(
            anonymous_client.get(f"/media/original/{storage_name}").status_code,
            404,
        )

    def test_new_album_is_draft_and_empty_album_cannot_be_published(self):
        token = self.login("user.one", "user-password-2026")
        created = self.api(
            "POST",
            "/studio/api/albums",
            token,
            json={"name": "尚未完成"},
        )
        self.assertEqual(created.status_code, 200)
        album = created.get_json()["album"]
        self.assertEqual(album["status"], "draft")
        rejected = self.api(
            "PATCH",
            f"/studio/api/albums/{album['id']}/publication",
            token,
            json={"status": "published"},
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertIn("空摄影集不能发布", rejected.get_json()["message"])

    def test_published_album_is_locked_and_foreign_album_stays_inaccessible(self):
        token = self.login("user.one", "user-password-2026")
        published = self.api(
            "PATCH",
            f"/studio/api/albums/{self.album_one_id}/publication",
            token,
            json={"status": "published"},
        )
        self.assertEqual(published.status_code, 200)

        requests = (
            self.api(
                "PATCH",
                f"/studio/api/albums/{self.album_one_id}",
                token,
                json={"name": "不应修改"},
            ),
            self.api(
                "PUT",
                f"/studio/api/albums/{self.album_one_id}/order",
                token,
                json={"photo_ids": [self.photo_one_id]},
            ),
            self.api(
                "PATCH",
                f"/studio/api/photos/{self.photo_one_id}",
                token,
                json={"title": "不应修改", "story": "", "album_id": self.album_one_id},
            ),
            self.api(
                "DELETE",
                f"/studio/api/photos/{self.photo_one_id}",
                token,
            ),
            self.api(
                "POST",
                "/studio/api/photos/bulk-delete",
                token,
                json={"ids": [self.photo_one_id]},
            ),
            self.api(
                "DELETE",
                f"/studio/api/albums/{self.album_one_id}",
                token,
                json={"delete_photos": False},
            ),
        )
        self.assertTrue(all(response.status_code == 409 for response in requests))

        upload = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={
                "album_id": str(self.album_one_id),
                "photo": (BytesIO(b"not-an-image"), "test.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 409)

        foreign = self.api(
            "PATCH",
            f"/studio/api/albums/{self.album_two_id}/publication",
            token,
            json={"status": "published"},
        )
        self.assertEqual(foreign.status_code, 404)

    def test_login_image_caption_is_removed_but_configurable_intro_remains(self):
        login_page = self.client.get("/login")
        login_html = login_page.get_data(as_text=True)
        self.assertIn('class="site-header login-header"', login_html)
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
        ready = self.client.get("/readyz")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.get_json(), {"status": "ready"})
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

    def test_new_album_photo_is_appended_after_existing_photos(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={
                "album_id": str(self.album_one_id),
                "photo": (self.image_stream(), "new-photo.jpg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        uploaded_id = response.get_json()["photo"]["id"]
        with self.app.app_context():
            rows = get_db().execute(
                """
                SELECT id, album_position
                FROM photos
                WHERE album_id = ? AND user_id = ?
                ORDER BY album_position
                """,
                (self.album_one_id, self.user_one_id),
            ).fetchall()
            self.assertEqual(
                [(row["id"], row["album_position"]) for row in rows],
                [(self.photo_one_id, 0), (uploaded_id, 1)],
            )

    def test_heif_photo_upload_is_safely_reencoded_as_webp(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={"photo": (self.heif_stream(96, 144), "IMG_0317.HEIC")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        uploaded_id = response.get_json()["photo"]["id"]

        with self.app.app_context():
            row = get_db().execute(
                """
                SELECT storage_name, original_name, mime_type, width, height
                FROM photos
                WHERE id = ?
                """,
                (uploaded_id,),
            ).fetchone()
            self.assertEqual(row["original_name"], "IMG_0317.HEIC")
            self.assertEqual(row["mime_type"], "image/webp")
            self.assertEqual((row["width"], row["height"]), (96, 144))
            original_path = self.data_root / "media" / "original" / row["storage_name"]
            thumb_path = self.data_root / "media" / "thumbs" / row["storage_name"]
            for stored_path in (original_path, thumb_path):
                with Image.open(stored_path) as stored:
                    self.assertEqual(stored.format, "WEBP")

    def test_heif_decoder_uses_restricted_options(self):
        self.assertEqual(heif_options.DECODE_THREADS, 1)
        self.assertFalse(heif_options.THUMBNAILS)
        self.assertFalse(heif_options.DEPTH_IMAGES)
        self.assertFalse(heif_options.AUX_IMAGES)
        self.assertFalse(heif_options.DISABLE_SECURITY_LIMITS)

    def test_studio_advertises_heif_upload_support(self):
        self.login("user.one", "user-password-2026")
        html = self.client.get("/studio").get_data(as_text=True)
        self.assertIn("支持 JPEG、PNG、WebP 和 HEIF", html)
        self.assertIn("image/heic,image/heif,.heic,.heif", html)

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
                "SELECT album_id, album_position FROM photos WHERE id = ?",
                (self.photo_one_id,),
            ).fetchone()
            self.assertIsNone(album)
            self.assertIsNotNone(photo)
            self.assertIsNone(photo["album_id"])
            self.assertIsNone(photo["album_position"])

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

    def test_owner_can_reorder_album_photos_for_public_display(self):
        with self.app.app_context():
            connection = get_db()
            second_id = self._insert_photo(
                connection,
                self.user_one_id,
                self.album_one_id,
                "d" * 32 + ".webp",
                "第二张照片",
            )
            third_id = self._insert_photo(
                connection,
                self.user_one_id,
                self.album_one_id,
                "e" * 32 + ".webp",
                "第三张照片",
            )
            connection.commit()

        token = self.login("user.one", "user-password-2026")
        read_response = self.api(
            "GET",
            f"/studio/api/albums/{self.album_one_id}/order",
            token,
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in read_response.get_json()["items"]},
            {self.photo_one_id, second_id, third_id},
        )

        incomplete = self.api(
            "PUT",
            f"/studio/api/albums/{self.album_one_id}/order",
            token,
            json={"photo_ids": [third_id, self.photo_one_id]},
        )
        self.assertEqual(incomplete.status_code, 409)

        expected = [second_id, self.photo_one_id, third_id]
        saved = self.api(
            "PUT",
            f"/studio/api/albums/{self.album_one_id}/order",
            token,
            json={"photo_ids": expected},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["message"], "照片顺序已保存")
        self.assertTrue(saved.get_json()["photo_revision"])

        published = self.api(
            "PATCH",
            f"/studio/api/albums/{self.album_one_id}/publication",
            token,
            json={"status": "published"},
        )
        self.assertEqual(published.status_code, 200)

        public_feed = self.client.get(
            f"/api/public/photos?album_id={self.album_one_id}&limit=24"
        )
        self.assertEqual(
            [item["id"] for item in public_feed.get_json()["items"]],
            expected,
        )
        with self.app.app_context():
            rows = get_db().execute(
                """
                SELECT id, album_position
                FROM photos
                WHERE album_id = ?
                ORDER BY album_position
                """,
                (self.album_one_id,),
            ).fetchall()
            self.assertEqual(
                [(row["id"], row["album_position"]) for row in rows],
                list(zip(expected, range(len(expected)))),
            )

    def test_user_cannot_read_or_reorder_another_users_album(self):
        token = self.login("user.one", "user-password-2026")
        read_response = self.api(
            "GET",
            f"/studio/api/albums/{self.album_two_id}/order",
            token,
        )
        self.assertEqual(read_response.status_code, 404)
        update_response = self.api(
            "PUT",
            f"/studio/api/albums/{self.album_two_id}/order",
            token,
            json={"photo_ids": [self.photo_two_id]},
        )
        self.assertEqual(update_response.status_code, 404)

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
        self.assertNotIn("已登录:", html)
        self.assertNotIn("data-context-sort-album", html)
        self.assertNotIn("sort-album-dialog", html)
        self.assertIn('id="inline-order-status"', html)
        self.assertIn('class="photo-order-heading">顺序</span>', html)
        self.assertIn("data-context-publication", html)
        self.assertIn('data-album-status="draft"', html)
        self.assertNotIn('class="status-text"', html)
        self.assertNotIn('class="manage-photo is-published"', html)
        self.assertIn('class="dialog photo-editor-dialog"', html)
        self.assertIn('class="modal-form photo-editor-form"', html)
        self.assertIn('class="photo-editor-scroll"', html)
        self.assertIn('class="modal-actions photo-editor-actions"', html)

        css_response = self.client.get("/static/css/app.css")
        css = css_response.get_data(as_text=True)
        css_response.close()
        self.assertIn(".photo-editor-scroll {", css)
        self.assertIn("overscroll-behavior: contain;", css)
        self.assertIn("max(14px, env(safe-area-inset-bottom))", css)

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
        self.assertIn('class="photo-order-heading">Order</span>', english_html)
        self.assertIn("Changes are saved automatically", english_html)
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
                "temporary_password": "welcome-2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        user = payload["user"]
        generated_password = payload["temporary_password"]
        self.assertEqual(user["status"], "pending")
        self.assertTrue(user["must_change_password"])
        self.assertEqual(user["role"], "photographer")
        self.assertNotEqual(generated_password, "welcome-2026")
        self.assertGreaterEqual(payload["temporary_password_expires_in"], 60)
        with self.app.app_context():
            stored = get_db().execute(
                "SELECT * FROM users WHERE username = 'new.user'"
            ).fetchone()
            self.assertTrue(check_password_hash(stored["password_hash"], generated_password))
            self.assertGreater(stored["temporary_password_expires_at"], int(time.time()))

        anonymous_client = self.app.test_client()
        login_page = anonymous_client.get("/login")
        csrf_token = CSRF_PATTERN.search(login_page.data).group(1).decode()
        rejected = anonymous_client.post(
            "/login",
            data={
                "username": "new.user",
                "password": "welcome-2026",
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(rejected.status_code, 200)
        accepted = anonymous_client.post(
            "/login",
            data={
                "username": "new.user",
                "password": generated_password,
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(accepted.status_code, 302)

        studio_html = self.client.get("/studio?tab=users").get_data(as_text=True)
        self.assertNotIn("welcome-2026", studio_html)
        self.assertNotIn("temporary-2026", studio_html)

    def test_admin_password_reset_uses_a_unique_expiring_server_secret(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "POST",
            f"/api/admin/users/{self.user_one_id}/reset-password",
            token,
            json={"temporary_password": "temporary-2026"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        generated_password = payload["temporary_password"]
        self.assertNotEqual(generated_password, "temporary-2026")
        self.assertGreaterEqual(payload["temporary_password_expires_in"], 60)

        with self.app.app_context():
            user = get_db().execute(
                "SELECT * FROM users WHERE id = ?", (self.user_one_id,)
            ).fetchone()
            self.assertTrue(check_password_hash(user["password_hash"], generated_password))
            self.assertGreater(user["temporary_password_expires_at"], int(time.time()))

        reset_client = self.app.test_client()
        login_page = reset_client.get("/login")
        csrf_token = CSRF_PATTERN.search(login_page.data).group(1).decode()
        rejected = reset_client.post(
            "/login",
            data={
                "username": "user.one",
                "password": "temporary-2026",
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(rejected.status_code, 200)
        accepted = reset_client.post(
            "/login",
            data={
                "username": "user.one",
                "password": generated_password,
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(accepted.status_code, 302)

    def test_expired_temporary_password_cannot_authenticate(self):
        token = self.login("admin.user", "admin-password-2026")
        response = self.api(
            "POST",
            f"/api/admin/users/{self.user_two_id}/reset-password",
            token,
            json={},
        )
        generated_password = response.get_json()["temporary_password"]
        with self.app.app_context():
            get_db().execute(
                "UPDATE users SET temporary_password_expires_at = 0 WHERE id = ?",
                (self.user_two_id,),
            )
            get_db().commit()

        reset_client = self.app.test_client()
        login_page = reset_client.get("/login")
        csrf_token = CSRF_PATTERN.search(login_page.data).group(1).decode()
        rejected = reset_client.post(
            "/login",
            data={
                "username": "user.two",
                "password": generated_password,
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertIn("账号或密码不正确。", rejected.get_data(as_text=True))

    def test_login_hash_work_is_uniform_for_existing_and_missing_users(self):
        login_page = self.client.get("/login")
        csrf_token = self.csrf_from(login_page)
        with patch("fabula.auth.check_password_hash", return_value=False) as verifier:
            existing = self.client.post(
                "/login",
                data={
                    "username": "user.one",
                    "password": "wrong-password-2026",
                    "csrf_token": csrf_token,
                },
            )
            missing = self.client.post(
                "/login",
                data={
                    "username": "missing.user",
                    "password": "wrong-password-2026",
                    "csrf_token": csrf_token,
                },
            )
        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(verifier.call_count, 2)
        self.assertEqual(
            verifier.call_args_list[1].args[0],
            self.app.config["DUMMY_PASSWORD_HASH"],
        )

    def test_login_attempt_reservation_is_atomic(self):
        fingerprint = "f" * 64
        self.app.config["LOGIN_MAX_ATTEMPTS"] = 5
        with self.app.app_context():
            get_db().executemany(
                "INSERT INTO login_attempts (fingerprint, attempted_at) VALUES (?, ?)",
                [(fingerprint, int(time.time()))] * 4,
            )
            get_db().commit()

        def reserve():
            with self.app.app_context():
                return reserve_login_attempt(fingerprint)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _index: reserve(), range(4)))
        self.assertEqual(sum(results), 1)
        with self.app.app_context():
            count = get_db().execute(
                "SELECT COUNT(*) FROM login_attempts WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()[0]
        self.assertEqual(count, 5)

    def test_image_pixel_budget_rejects_before_processing(self):
        token = self.login("user.one", "user-password-2026")
        self.app.config["MAX_IMAGE_PIXELS"] = 10_000
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={"photo": (self.image_stream(101, 100), "over-budget.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], "图片像素数量超过安全处理限制")

    def test_iphone_resolution_jpeg_is_downsampled_and_stored(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={"photo": (self.image_stream(5712, 4284), "IMG_0797.jpeg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        uploaded_id = response.get_json()["photo"]["id"]

        with self.app.app_context():
            row = get_db().execute(
                "SELECT storage_name, width, height FROM photos WHERE id = ?",
                (uploaded_id,),
            ).fetchone()
            stored_path = self.data_root / "media" / "original" / row["storage_name"]
            with Image.open(stored_path) as stored:
                self.assertLessEqual(max(stored.size), 2400)
                self.assertEqual(stored.size, (row["width"], row["height"]))

    def test_pillow_bomb_error_uses_pixel_limit_message(self):
        token = self.login("user.one", "user-password-2026")
        with patch.object(Image, "MAX_IMAGE_PIXELS", 10_000):
            response = self.api(
                "POST",
                "/studio/api/photos",
                token,
                data={"photo": (self.image_stream(201, 101), "too-large.jpg")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["message"], "图片像素数量超过安全处理限制")

    def test_image_variants_are_bounded_before_encoding(self):
        self.app.config["MAX_IMAGE_PIXELS"] = 4_000_000
        encoded_sizes = []

        def fake_save(image, destination, quality):
            encoded_sizes.append((image.size, quality))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"test")

        with self.app.app_context(), patch("fabula.media._save_webp", side_effect=fake_save):
            process_image(self.image_stream(3000, 1000))
        self.assertEqual(encoded_sizes, [((2400, 800), 84), ((1000, 333), 78)])

    def test_bulk_delete_rejects_oversized_identifier_lists(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/studio/api/photos/bulk-delete",
            token,
            json={"ids": list(range(10_000, 10_501))},
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("一次最多删除 500 张照片", response.get_json()["message"])

    def test_failed_media_cleanup_is_queued_and_retried(self):
        token = self.login("user.one", "user-password-2026")
        with patch("fabula.media.delete_media", side_effect=OSError("busy filesystem")):
            response = self.api(
                "DELETE",
                f"/studio/api/photos/{self.photo_one_id}",
                token,
            )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            connection = get_db()
            self.assertIsNone(
                connection.execute(
                    "SELECT id FROM photos WHERE id = ?",
                    (self.photo_one_id,),
                ).fetchone()
            )
            queued = connection.execute(
                "SELECT attempts FROM media_cleanup_queue"
            ).fetchone()
            self.assertEqual(queued["attempts"], 1)
            self.assertEqual(drain_media_deletions(), 1)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM media_cleanup_queue"
                ).fetchone()[0],
                0,
            )

    def test_user_list_uses_aggregate_counts_without_per_user_queries(self):
        token = self.login("admin.user", "admin-password-2026")
        with patch("fabula.admin.content_counts", side_effect=AssertionError("N+1 query")):
            response = self.api("GET", "/api/admin/users", token)
        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        user_one = next(item for item in items if item["id"] == self.user_one_id)
        self.assertEqual(user_one["content"], {"photos": 1, "albums": 1, "about": 1})

    def test_schema_migrations_are_versioned(self):
        with self.app.app_context():
            versions = {
                row["version"]
                for row in get_db().execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
        self.assertEqual(versions, {1, 2, 3, 4, 5})

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

    def test_admin_can_manage_home_and_login_images(self):
        token = self.login("admin.user", "admin-password-2026")
        studio_html = self.client.get("/studio?tab=site-copy").get_data(as_text=True)
        self.assertIn("站点照片", studio_html)
        self.assertIn('data-site-image-input="home"', studio_html)
        self.assertIn('data-site-image-input="login"', studio_html)

        home_response = self.api(
            "POST",
            "/api/admin/site-images/home",
            token,
            data={"image": (self.image_stream(120, 240), "portrait.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(home_response.status_code, 200)
        home_payload = home_response.get_json()
        self.assertTrue(home_payload["image"]["custom"])
        home_url = home_payload["image"]["url"]
        self.assertRegex(home_url, r"^/site-media/home/home-[a-f0-9]{32}\.webp$")
        home_storage_name = home_url.rsplit("/", 1)[-1]
        home_path = self.data_root / "site" / home_storage_name
        self.assertTrue(home_path.is_file())
        with Image.open(home_path) as stored_home:
            self.assertEqual(stored_home.format, "WEBP")
            self.assertEqual(stored_home.size, (120, 240))
        media_response = self.client.get(home_url)
        self.assertEqual(media_response.status_code, 200)
        media_response.close()
        public_html = self.client.get("/").get_data(as_text=True)
        self.assertIn(home_url, public_html)
        self.assertIn('class="hero-image"', public_html)

        login_response = self.api(
            "POST",
            "/api/admin/site-images/login",
            token,
            data={"image": (self.image_stream(240, 120), "landscape.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(login_response.status_code, 200)
        login_url = login_response.get_json()["image"]["url"]
        anonymous_client = self.app.test_client()
        login_html = anonymous_client.get("/login").get_data(as_text=True)
        self.assertIn(login_url, login_html)
        self.assertIn("登录页视觉", login_html)

        reset_response = self.api(
            "DELETE",
            "/api/admin/site-images/home",
            token,
        )
        self.assertEqual(reset_response.status_code, 200)
        self.assertFalse(reset_response.get_json()["image"]["custom"])
        self.assertFalse(home_path.exists())
        self.assertEqual(self.client.get(home_url).status_code, 404)
        with self.app.app_context():
            actions = [
                row["action"]
                for row in get_db().execute(
                    "SELECT action FROM audit_events ORDER BY id"
                ).fetchall()
            ]
            self.assertEqual(
                actions,
                ["site_image.updated", "site_image.updated", "site_image.reset"],
            )

    def test_regular_user_cannot_manage_site_images(self):
        token = self.login("user.one", "user-password-2026")
        response = self.api(
            "POST",
            "/api/admin/site-images/home",
            token,
            data={"image": (self.image_stream(), "site.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(any((self.data_root / "site").iterdir()))

    def test_studio_upload_limit_error_is_json(self):
        token = self.login("user.one", "user-password-2026")
        self.app.config["MAX_CONTENT_LENGTH"] = 256
        response = self.api(
            "POST",
            "/studio/api/photos",
            token,
            data={"photo": (BytesIO(b"x" * 2048), "large.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json()["message"], "图片超过上传大小限制")

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


class ResetAdminPasswordCliTestCase(unittest.TestCase):
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
                "TURNSTILE_SITE_KEY": "",
                "TURNSTILE_SECRET_KEY": "",
                "TURNSTILE_EXPECTED_HOSTNAMES": "",
            }
        )
        with self.app.app_context():
            bootstrap_admin(
                "first.admin",
                "首位管理员",
                "initial-password-2026",
            )
            get_db().execute(
                "UPDATE users SET must_change_password = 0 WHERE username = 'first.admin'"
            )
            get_db().commit()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_reset_admin_password_revokes_sessions_and_writes_audit_event(self):
        new_password = "replacement-password-2026"
        result = self.app.test_cli_runner().invoke(
            args=["reset-admin-password", "--username", "FIRST.ADMIN"],
            input=f"{new_password}\n{new_password}\n",
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(new_password, result.output)
        self.assertIn("现有会话已撤销", result.output)
        with self.app.app_context():
            connection = get_db()
            admin = connection.execute(
                "SELECT * FROM users WHERE username = 'first.admin'"
            ).fetchone()
            event = connection.execute(
                """
                SELECT actor_user_id, target_user_id, action, details_json
                FROM audit_events
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

            self.assertTrue(check_password_hash(admin["password_hash"], new_password))
            self.assertFalse(
                check_password_hash(
                    admin["password_hash"],
                    "initial-password-2026",
                )
            )
            self.assertEqual(admin["must_change_password"], 1)
            self.assertEqual(admin["session_version"], 2)
            self.assertIsNone(event["actor_user_id"])
            self.assertEqual(event["target_user_id"], admin["id"])
            self.assertEqual(event["action"], "user.password_reset")
            self.assertEqual(event["details_json"], '{"source": "cli-recovery"}')

    def test_reset_admin_password_refuses_inactive_admin(self):
        with self.app.app_context():
            connection = get_db()
            original_hash = connection.execute(
                "SELECT password_hash FROM users WHERE username = 'first.admin'"
            ).fetchone()["password_hash"]
            connection.execute(
                "UPDATE users SET status = 'inactive' WHERE username = 'first.admin'"
            )
            connection.commit()

        result = self.app.test_cli_runner().invoke(
            args=["reset-admin-password", "--username", "first.admin"],
            input="replacement-password-2026\nreplacement-password-2026\n",
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("管理员账号已停用", result.output)
        with self.app.app_context():
            connection = get_db()
            admin = connection.execute(
                "SELECT password_hash, session_version FROM users "
                "WHERE username = 'first.admin'"
            ).fetchone()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0]
            self.assertEqual(admin["password_hash"], original_hash)
            self.assertEqual(admin["session_version"], 1)
            self.assertEqual(event_count, 0)


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

    def test_existing_database_gets_album_photo_positions(self):
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
                    locale TEXT NOT NULL DEFAULT 'zh-CN',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TEXT
                );
                CREATE TABLE albums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, name),
                    UNIQUE (id, user_id)
                );
                CREATE TABLE photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    album_id INTEGER,
                    storage_name TEXT NOT NULL UNIQUE,
                    original_name TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    story TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'ready',
                    mime_type TEXT NOT NULL DEFAULT 'image/webp',
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (album_id, user_id) REFERENCES albums(id, user_id)
                );
                INSERT INTO users (
                    id, username, display_name, role, status, password_hash,
                    must_change_password
                ) VALUES (
                    1, 'legacy.user', '旧用户', 'photographer', 'active',
                    'not-used-in-this-test', 0
                );
                INSERT INTO albums (id, user_id, name) VALUES (1, 1, '旧摄影集');
                INSERT INTO photos (
                    id, user_id, album_id, storage_name, original_name, title,
                    created_at
                ) VALUES
                    (1, 1, 1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp', 'old.webp', '旧照片', '2025-01-01T00:00:00Z'),
                    (2, 1, 1, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.webp', 'new.webp', '新照片', '2025-02-01T00:00:00Z');
                """
            )
            connection.close()

            app = create_app(self.app_config(data_root))
            with app.app_context():
                database = get_db()
                columns = {
                    row["name"]
                    for row in database.execute("PRAGMA table_info(photos)").fetchall()
                }
                positions = database.execute(
                    "SELECT id, album_position FROM photos ORDER BY album_position"
                ).fetchall()
                migrated_album = database.execute(
                    "SELECT status, published_at FROM albums WHERE id = 1"
                ).fetchone()
                self.assertIn("album_position", columns)
                self.assertEqual(
                    [(row["id"], row["album_position"]) for row in positions],
                    [(2, 0), (1, 1)],
                )
                self.assertEqual(migrated_album["status"], "published")
                self.assertIsNotNone(migrated_album["published_at"])

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

    def test_production_requires_secure_session_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            config = self.app_config(data_root)
            config.update(
                ENVIRONMENT="production",
                SESSION_COOKIE_SECURE=False,
            )
            with self.assertRaisesRegex(RuntimeError, "must be true in production"):
                create_app(config)

    def test_image_and_temporary_password_limits_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            config = self.app_config(data_root)
            config["MAX_IMAGE_PIXELS"] = 50_000_001
            with self.assertRaisesRegex(RuntimeError, "FABULA_MAX_IMAGE_PIXELS"):
                create_app(config)

            config = self.app_config(data_root)
            config["TEMPORARY_PASSWORD_TTL_SECONDS"] = 59
            with self.assertRaisesRegex(
                RuntimeError,
                "FABULA_TEMPORARY_PASSWORD_TTL_SECONDS",
            ):
                create_app(config)

    def test_demo_seed_rolls_back_database_and_generated_media(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            app = create_app(self.app_config(data_root))
            processed = {
                "storage_name": "a" * 32 + ".webp",
                "width": 1200,
                "height": 800,
                "size_bytes": 1024,
            }
            with (
                patch("fabula.cli.process_image", return_value=processed),
                patch("fabula.cli.delete_media") as delete_media,
            ):
                result = app.test_cli_runner().invoke(args=["seed-demo"])

            self.assertNotEqual(result.exit_code, 0)
            with app.app_context():
                self.assertEqual(
                    get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0],
                    0,
                )
            self.assertEqual(delete_media.call_count, 12)


if __name__ == "__main__":
    unittest.main()
