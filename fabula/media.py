from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError


STORAGE_PATTERN = re.compile(r"^[a-f0-9]{32}\.webp$")
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
Image.MAX_IMAGE_PIXELS = 80_000_000


class InvalidImage(ValueError):
    pass


def _paths(storage_name: str) -> tuple[Path, Path]:
    media_root = Path(current_app.config["MEDIA_ROOT"])
    return (
        media_root / "original" / storage_name,
        media_root / "thumbs" / storage_name,
    )


def _save_webp(image: Image.Image, destination: Path, max_size: tuple[int, int], quality: int) -> None:
    output = image.copy()
    output.thumbnail(max_size, Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix="fabula-",
        suffix=".webp",
        dir=current_app.config["TEMP_ROOT"],
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        output.save(
            temporary_path,
            "WEBP",
            quality=quality,
            method=6,
            optimize=True,
        )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def process_image(stream) -> dict:
    storage_name = f"{uuid.uuid4().hex}.webp"
    original_path, thumb_path = _paths(storage_name)
    try:
        with Image.open(stream) as opened:
            if opened.format not in ALLOWED_FORMATS:
                raise InvalidImage("仅支持 JPEG、PNG 和 WebP 图片")
            if opened.width * opened.height > Image.MAX_IMAGE_PIXELS:
                raise InvalidImage("图片像素数量超过安全处理限制")
            image = ImageOps.exif_transpose(opened)
            image.load()
            if image.width < 32 or image.height < 32:
                raise InvalidImage("图片尺寸过小")
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            if image.mode == "RGBA":
                background = Image.new("RGB", image.size, "#e9e8e2")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            width, height = image.size
            _save_webp(image, original_path, (2400, 2400), 84)
            _save_webp(image, thumb_path, (1000, 1000), 78)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        original_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        raise InvalidImage("图片文件无效或无法安全处理") from error
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


def delete_media(storage_name: str) -> None:
    if not STORAGE_PATTERN.fullmatch(storage_name):
        return
    original_path, thumb_path = _paths(storage_name)
    original_path.unlink(missing_ok=True)
    thumb_path.unlink(missing_ok=True)
