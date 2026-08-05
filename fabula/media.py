from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .db import get_db
from .i18n import translate


STORAGE_PATTERN = re.compile(r"^[a-f0-9]{32}\.webp$")
SITE_STORAGE_PATTERN = re.compile(r"^(home|login)-[a-f0-9]{32}\.webp$")
SITE_IMAGE_SLOTS = frozenset({"home", "login"})
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
HARD_MAX_IMAGE_PIXELS = 50_000_000
ORIGINAL_MAX_SIZE = (2400, 2400)
Image.MAX_IMAGE_PIXELS = HARD_MAX_IMAGE_PIXELS
IMAGE_PROCESSING_LOCK = threading.Lock()

register_heif_opener(
    thumbnails=False,
    depth_images=False,
    aux_images=False,
    decode_threads=1,
)


class InvalidImage(ValueError):
    pass


def _paths(storage_name: str) -> tuple[Path, Path]:
    media_root = Path(current_app.config["MEDIA_ROOT"])
    return (
        media_root / "original" / storage_name,
        media_root / "thumbs" / storage_name,
    )


def _save_webp(image: Image.Image, destination: Path, quality: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix="fabula-",
        suffix=".webp",
        dir=current_app.config["TEMP_ROOT"],
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        image.save(
            temporary_path,
            "WEBP",
            quality=quality,
            method=6,
            optimize=True,
        )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _validate_image_dimensions(image: Image.Image) -> None:
    if (
        image.width > current_app.config["MAX_IMAGE_DIMENSION"]
        or image.height > current_app.config["MAX_IMAGE_DIMENSION"]
        or image.width * image.height > current_app.config["MAX_IMAGE_PIXELS"]
    ):
        raise InvalidImage(translate("图片像素数量超过安全处理限制"))


def _validate_image_header(opened: Image.Image) -> None:
    if opened.format not in ALLOWED_FORMATS:
        raise InvalidImage(translate("仅支持 JPEG、PNG、WebP 和 HEIF 图片"))
    _validate_image_dimensions(opened)


def _normalized_image(opened: Image.Image) -> Image.Image:
    if opened.format == "JPEG":
        opened.draft("RGB", ORIGINAL_MAX_SIZE)
    ImageOps.exif_transpose(opened, in_place=True)
    image = opened
    _validate_image_dimensions(image)
    if image.width < 32 or image.height < 32:
        raise InvalidImage(translate("图片尺寸过小"))
    image.thumbnail(ORIGINAL_MAX_SIZE, Image.Resampling.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, "#e9e8e2")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    return image


def _log_decode_failure(error: Exception, source_description: str) -> None:
    detail = " ".join(str(error).split())[:240]
    current_app.logger.warning(
        "Image processing rejected (%s; %s): %s",
        source_description,
        type(error).__name__,
        detail,
    )


def process_image(stream) -> dict:
    storage_name = f"{uuid.uuid4().hex}.webp"
    original_path, thumb_path = _paths(storage_name)
    source_description = "format=unknown dimensions=unknown"
    try:
        with IMAGE_PROCESSING_LOCK:
            with Image.open(stream) as opened:
                source_description = (
                    f"format={opened.format or 'unknown'} "
                    f"dimensions={opened.width}x{opened.height}"
                )
                _validate_image_header(opened)
                image = _normalized_image(opened)
                width, height = image.size
                _save_webp(image, original_path, 84)
                image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                _save_webp(image, thumb_path, 78)
    except InvalidImage:
        original_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        raise
    except Image.DecompressionBombError as error:
        original_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        _log_decode_failure(error, source_description)
        raise InvalidImage(translate("图片像素数量超过安全处理限制")) from error
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        RuntimeError,
        EOFError,
        ValueError,
    ) as error:
        original_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        _log_decode_failure(error, source_description)
        raise InvalidImage(translate("图片文件无效或无法安全处理")) from error
    except Exception:
        original_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        raise

    return {
        "storage_name": storage_name,
        "width": width,
        "height": height,
        "size_bytes": original_path.stat().st_size,
    }


def process_site_image(stream, slot: str) -> dict:
    if slot not in SITE_IMAGE_SLOTS:
        raise InvalidImage(translate("站点图片位置无效"))
    storage_name = f"{slot}-{uuid.uuid4().hex}.webp"
    destination = Path(current_app.config["SITE_MEDIA_ROOT"]) / storage_name
    source_description = "format=unknown dimensions=unknown"
    try:
        with IMAGE_PROCESSING_LOCK:
            with Image.open(stream) as opened:
                source_description = (
                    f"format={opened.format or 'unknown'} "
                    f"dimensions={opened.width}x{opened.height}"
                )
                _validate_image_header(opened)
                image = _normalized_image(opened)
                width, height = image.size
                _save_webp(image, destination, 84)
    except InvalidImage:
        destination.unlink(missing_ok=True)
        raise
    except Image.DecompressionBombError as error:
        destination.unlink(missing_ok=True)
        _log_decode_failure(error, source_description)
        raise InvalidImage(translate("图片像素数量超过安全处理限制")) from error
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        RuntimeError,
        EOFError,
        ValueError,
    ) as error:
        destination.unlink(missing_ok=True)
        _log_decode_failure(error, source_description)
        raise InvalidImage(translate("图片文件无效或无法安全处理")) from error
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return {
        "storage_name": storage_name,
        "width": width,
        "height": height,
        "size_bytes": destination.stat().st_size,
    }


def delete_media(storage_name: str) -> None:
    if not STORAGE_PATTERN.fullmatch(storage_name):
        return
    original_path, thumb_path = _paths(storage_name)
    original_path.unlink(missing_ok=True)
    thumb_path.unlink(missing_ok=True)


def delete_site_media(storage_name: str | None) -> None:
    if not storage_name or not SITE_STORAGE_PATTERN.fullmatch(storage_name):
        return
    (Path(current_app.config["SITE_MEDIA_ROOT"]) / storage_name).unlink(missing_ok=True)


def queue_media_deletion(connection, storage_name: str | None, media_kind: str) -> None:
    valid = (
        media_kind == "photo"
        and storage_name is not None
        and STORAGE_PATTERN.fullmatch(storage_name)
    ) or (
        media_kind == "site"
        and storage_name is not None
        and SITE_STORAGE_PATTERN.fullmatch(storage_name)
    )
    if not valid:
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO media_cleanup_queue (storage_name, media_kind)
        VALUES (?, ?)
        """,
        (storage_name, media_kind),
    )


def drain_media_deletions(limit: int = 100) -> int:
    connection = get_db()
    rows = connection.execute(
        """
        SELECT storage_name, media_kind
        FROM media_cleanup_queue
        ORDER BY created_at, storage_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    completed = 0
    for row in rows:
        try:
            if row["media_kind"] == "photo":
                delete_media(row["storage_name"])
            else:
                delete_site_media(row["storage_name"])
        except OSError as error:
            connection.execute(
                """
                UPDATE media_cleanup_queue
                SET attempts = attempts + 1, last_error = ?
                WHERE storage_name = ? AND media_kind = ?
                """,
                (str(error)[:500], row["storage_name"], row["media_kind"]),
            )
            connection.commit()
            current_app.logger.warning(
                "Deferred media cleanup for %s",
                row["storage_name"],
            )
            continue
        connection.execute(
            """
            DELETE FROM media_cleanup_queue
            WHERE storage_name = ? AND media_kind = ?
            """,
            (row["storage_name"], row["media_kind"]),
        )
        connection.commit()
        completed += 1
    return completed
