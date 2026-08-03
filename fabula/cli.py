from __future__ import annotations

import json
import time
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from .db import get_db, init_db
from .media import delete_media, process_image
from .security import audit, valid_password, valid_username
from .settings import save_site_copy


DEMO_USERS = [
    ("lin.qiu", "林秋", "admin", "active", "fabula-demo-2026", 0, 1),
    ("zhou.wang", "周望", "photographer", "active", "fabula-user-2026", 0, 0),
    ("chen.cheng", "陈澄", "photographer", "active", "fabula-user-2026", 0, 0),
    ("he.yan", "何言", "photographer", "active", "fabula-user-2026", 0, 0),
]

DEMO_PROFILES = {
    "lin.qiu": {
        "title": "在日常与远方之间，寻找光停下来的片刻。",
        "bio": "我长期拍摄那些没有被特别命名的时刻：放学后的广场、雨前的站台、陌生城市里短暂亮起的窗。对我来说，摄影不是证明到过哪里，而是认真保留当时如何看见。",
        "signature": "Lin Qiu",
        "gear": ["Leica M6", "Fujifilm GFX 50R", "35mm / 50mm"],
        "contact": ["Email: lin@example.test", "Instagram: @linqiu.demo"],
    },
    "zhou.wang": {
        "title": "把城市当作一部可以缓慢翻阅的书。",
        "bio": "我关注建筑、秩序和人在巨大结构里的尺度。镜头常常向上，也会停在一扇普通的窗前。那些线条并不冷漠，它们只是用另一种方式记录人如何生活。",
        "signature": "Zhou Wang",
        "gear": ["Hasselblad 500CM", "80mm"],
        "contact": ["Email: zhou@example.test"],
    },
    "chen.cheng": {
        "title": "在风改变方向以前，记下旷野的呼吸。",
        "bio": "我在城市之外拍摄河流、动物、旧房子和季节变化。照片里的自然不是远离人的风景，它也保留劳作、迁徙与等待留下的细小痕迹。",
        "signature": "Chen Cheng",
        "gear": ["Pentax 67", "105mm"],
        "contact": ["Email: chen@example.test"],
    },
}

DEMO_PHOTOS = [
    ("lin.qiu", "日常缓慢", "after-school.webp", "放学以后", "下午四点十七分，广场上只剩下两个孩子。她们没有急着回家，长长的影子先一步走到画面之外。"),
    ("lin.qiu", "日常缓慢", "crossing-light.webp", "穿过明暗", "正午的地面被建筑切成两种温度。她从亮处走进阴影，又在下一秒离开。"),
    ("lin.qiu", "沿途", "near-rain.webp", "雨还没有落下", "站台的广播反复提醒晚点。远处第一盏灯亮起时，铁轨仍然是干的。"),
    ("lin.qiu", "沿途", "late-platform.webp", "夜车抵达以前", "我们在没有名字的小站等了四十分钟。后来回看这张照片，等待本身已经成为目的地。"),
    ("zhou.wang", "城市垂直", "vertical-city.webp", "向上的城市", "站在楼脚时，城市只剩下一条向上的路。窗户像重复的标点。"),
    ("zhou.wang", "城市垂直", "last-light.webp", "最后一层光", "太阳落到楼群之后，玻璃还留着几分钟的金色。"),
    ("zhou.wang", "建筑之间", "quiet-frame.webp", "安静的框", "窗、门、路口和墙面，把庞大的城市切成可以慢慢阅读的小段落。"),
    ("zhou.wang", "建筑之间", "night-window.webp", "陌生人的灯", "深夜经过一排住宅，只看见一扇窗还亮着。"),
    ("chen.cheng", "野地笔记", "autumn-yard.webp", "院子里的秋天", "木屋旁的羊并不怕镜头。风吹过旧屋顶，发出像纸张翻页一样的声音。"),
    ("chen.cheng", "野地笔记", "pale-morning.webp", "白色早晨", "雾把远处的坡地擦得很淡，一棵树从白色里慢慢显出来。"),
    ("chen.cheng", "另一片岸", "river-road.webp", "河流知道方向", "地图在山里失去信号以后，我们只好跟着水走。"),
    ("chen.cheng", "另一片岸", "another-shore.webp", "另一片岸", "傍晚的风把水面吹得发白。对岸很近，却没有桥。"),
]


def bootstrap_admin(username: str, display_name: str, password: str) -> None:
    if not valid_username(username):
        raise click.ClickException("用户名需为 3 到 32 位字母、数字、点或下划线")
    if not display_name.strip():
        raise click.ClickException("公开显示名称不能为空")
    if not valid_password(password):
        raise click.ClickException("密码至少 12 个字符，并同时包含字母和数字")
    connection = get_db()
    expires_at = int(time.time()) + current_app.config[
        "TEMPORARY_PASSWORD_TTL_SECONDS"
    ]
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
            raise click.ClickException("系统中已经存在用户，初始管理员流程已关闭")
        connection.execute(
            """
            INSERT INTO users (
                username, display_name, role, status, password_hash,
                must_change_password, temporary_password_expires_at, initial_admin
            ) VALUES (?, ?, 'admin', 'active', ?, 1, ?, 1)
            """,
            (
                username,
                display_name.strip(),
                generate_password_hash(password),
                expires_at,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def reset_admin_password(username: str, password: str) -> None:
    username = username.strip()
    if not valid_username(username):
        raise click.ClickException("管理员用户名格式无效")
    if not valid_password(password):
        raise click.ClickException("密码至少 12 个字符，并同时包含字母和数字")

    connection = get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        admin = connection.execute(
            """
            SELECT id, status
            FROM users
            WHERE username = ? COLLATE NOCASE AND role = 'admin'
            """,
            (username,),
        ).fetchone()
        if admin is None:
            raise click.ClickException("管理员账号不存在")
        if admin["status"] == "inactive":
            raise click.ClickException("管理员账号已停用，请先通过独立治理流程恢复账号")

        expires_at = int(time.time()) + current_app.config[
            "TEMPORARY_PASSWORD_TTL_SECONDS"
        ]

        connection.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 1,
                temporary_password_expires_at = ?,
                session_version = session_version + 1,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (generate_password_hash(password), expires_at, admin["id"]),
        )
        audit(
            "user.password_reset",
            target_user_id=admin["id"],
            details={"source": "cli-recovery"},
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


@click.command("init-db")
@with_appcontext
def init_db_command():
    init_db()
    click.echo("数据库结构已初始化。")


@click.command("bootstrap-admin")
@click.option("--username", prompt="管理员用户名")
@click.option("--display-name", prompt="公开显示名称")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def bootstrap_admin_command(username: str, display_name: str, password: str):
    bootstrap_admin(username, display_name, password)
    click.echo("首位管理员已创建，首次登录后必须更换密码。")


@click.command("reset-admin-password")
@click.option("--username", prompt="管理员用户名")
@with_appcontext
def reset_admin_password_command(username: str):
    password = click.prompt(
        "新临时密码",
        hide_input=True,
        confirmation_prompt=True,
    )
    reset_admin_password(username, password)
    click.echo("管理员密码已重置，现有会话已撤销；下次登录必须更换临时密码。")


@click.command("seed-demo")
@with_appcontext
def seed_demo_command():
    if current_app.config["ENVIRONMENT"] == "production":
        raise click.ClickException("生产环境禁止写入演示账号和演示内容")
    asset_root = Path(current_app.root_path).parent / "demo_assets"
    sources = []
    for username, album_name, filename, title, story in DEMO_PHOTOS:
        source = asset_root / filename
        if not source.exists():
            raise click.ClickException(f"缺少演示图片：{filename}")
        sources.append((username, album_name, filename, title, story, source))

    processed_photos = []
    connection = get_db()
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
        raise click.ClickException("数据库中已经存在用户，拒绝覆盖现有数据")
    try:
        for username, album_name, filename, title, story, source in sources:
            with source.open("rb") as image_file:
                processed = process_image(image_file)
            processed_photos.append(
                (username, album_name, filename, title, story, processed)
            )

        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
            raise click.ClickException("数据库中已经存在用户，拒绝覆盖现有数据")

        user_ids = {}
        for username, name, role, status, password, must_change, initial in DEMO_USERS:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    username, display_name, role, status, password_hash,
                    must_change_password, initial_admin
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    name,
                    role,
                    status,
                    generate_password_hash(password),
                    must_change,
                    initial,
                ),
            )
            user_ids[username] = cursor.lastrowid

        album_ids = {}
        for username, album_name, *_rest in DEMO_PHOTOS:
            key = (username, album_name)
            if key in album_ids:
                continue
            cursor = connection.execute(
                """
                INSERT INTO albums (user_id, name, status, published_at)
                VALUES (?, ?, 'published', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (user_ids[username], album_name),
            )
            album_ids[key] = cursor.lastrowid

        for username, profile in DEMO_PROFILES.items():
            connection.execute(
                """
                INSERT INTO about_blocks (
                    user_id, title, bio, signature, gear_json, contact_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_ids[username],
                    profile["title"],
                    profile["bio"],
                    profile["signature"],
                    json.dumps(profile["gear"], ensure_ascii=False),
                    json.dumps(profile["contact"], ensure_ascii=False),
                ),
            )

        for username, album_name, filename, title, story, processed in processed_photos:
            connection.execute(
                """
                INSERT INTO photos (
                    user_id, album_id, storage_name, original_name, title, story,
                    status, mime_type, width, height, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready', 'image/webp', ?, ?, ?)
                """,
                (
                    user_ids[username],
                    album_ids[(username, album_name)],
                    processed["storage_name"],
                    filename,
                    title,
                    story,
                    processed["width"],
                    processed["height"],
                    processed["size_bytes"],
                ),
            )

        save_site_copy({})
        connection.commit()
    except Exception:
        connection.rollback()
        for *_metadata, processed in processed_photos:
            try:
                delete_media(processed["storage_name"])
            except OSError:
                current_app.logger.exception(
                    "Failed to remove media after demo seed rollback"
                )
        raise
    click.echo("演示数据已创建。")
    click.echo("管理员：lin.qiu / fabula-demo-2026")
    click.echo("普通用户：zhou.wang / fabula-user-2026")


def init_app(app) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(bootstrap_admin_command)
    app.cli.add_command(reset_admin_password_command)
    app.cli.add_command(seed_demo_command)
