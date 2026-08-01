from __future__ import annotations

import json

from .db import get_db
from .media import SITE_IMAGE_SLOTS, SITE_STORAGE_PATTERN


DEFAULT_SITE_PALETTE = "cinnabar"
SITE_PALETTES = frozenset({"cinnabar", "celadon", "indigo", "lotus"})

SITE_COPY_DEFAULTS = {
    "site_title": "Fabula",
    "hero_before": "光停下来，",
    "hero_accent": "故事",
    "hero_after": "继续。",
    "hero_note": "三位摄影师，共同整理正在发生的生活、远方与记忆。每一张照片都属于它的作者，也向所有人敞开。",
    "hero_cta": "浏览作品",
    "archive_title": "共有人间",
    "archive_intro": "从摄影师和摄影集进入，也可以不做选择。标题留在画面之外，故事留在点击之后。",
    "about_title": "关于我们，以及看见。",
    "about_intro": "Fabula 不是一个人的展墙。每位摄影师负责自己的段落，所有段落一起组成这里。",
    "login_title": "回到你的暗房。",
    "login_intro": "进入只属于你的工作台。管理员会看到额外的站点治理工具，摄影内容仍按所有者隔离。",
}

SITE_COPY_LIMITS = {
    "site_title": 40,
    "hero_before": 80,
    "hero_accent": 40,
    "hero_after": 80,
    "hero_note": 600,
    "hero_cta": 40,
    "archive_title": 80,
    "archive_intro": 600,
    "about_title": 100,
    "about_intro": 600,
    "login_title": 100,
    "login_intro": 600,
}


def normalize_site_palette(value: object) -> str:
    palette = str(value or "").strip()
    return palette if palette in SITE_PALETTES else DEFAULT_SITE_PALETTE


def default_site_copy() -> dict:
    return {
        **SITE_COPY_DEFAULTS,
        "color_scheme": DEFAULT_SITE_PALETTE,
    }


def get_site_copy() -> dict:
    row = get_db().execute(
        "SELECT value FROM site_settings WHERE key = 'site_copy'"
    ).fetchone()
    if row is None:
        return default_site_copy()
    try:
        stored = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return default_site_copy()
    if not isinstance(stored, dict):
        return default_site_copy()
    site_copy = {
        key: str(stored.get(key, default))
        for key, default in SITE_COPY_DEFAULTS.items()
    }
    site_copy["color_scheme"] = normalize_site_palette(stored.get("color_scheme"))
    return site_copy


def save_site_copy(values: dict) -> dict:
    cleaned = {
        key: str(values.get(key, default)).strip()[: SITE_COPY_LIMITS[key]] or default
        for key, default in SITE_COPY_DEFAULTS.items()
    }
    cleaned["color_scheme"] = normalize_site_palette(values.get("color_scheme"))
    get_db().execute(
        """
        INSERT INTO site_settings (key, value)
        VALUES ('site_copy', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (json.dumps(cleaned, ensure_ascii=False),),
    )
    return cleaned


def get_site_images() -> dict[str, str | None]:
    images = {slot: None for slot in SITE_IMAGE_SLOTS}
    row = get_db().execute(
        "SELECT value FROM site_settings WHERE key = 'site_images'"
    ).fetchone()
    if row is None:
        return images
    try:
        stored = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return images
    if not isinstance(stored, dict):
        return images
    for slot in SITE_IMAGE_SLOTS:
        storage_name = stored.get(slot)
        if isinstance(storage_name, str) and SITE_STORAGE_PATTERN.fullmatch(storage_name):
            images[slot] = storage_name
    return images


def save_site_image(slot: str, storage_name: str | None) -> dict[str, str | None]:
    if slot not in SITE_IMAGE_SLOTS:
        raise ValueError("invalid site image slot")
    if storage_name is not None and not SITE_STORAGE_PATTERN.fullmatch(storage_name):
        raise ValueError("invalid site image storage name")
    images = get_site_images()
    images[slot] = storage_name
    get_db().execute(
        """
        INSERT INTO site_settings (key, value)
        VALUES ('site_images', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (json.dumps(images, ensure_ascii=False),),
    )
    return images
