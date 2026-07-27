from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
from typing import BinaryIO

from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


LISTING_IMAGE_MAX_SIZE = (1600, 1200)
PROFILE_IMAGE_MAX_SIZE = (512, 512)


def optimize_listing_image(upload: UploadedFile) -> UploadedFile:
    return optimize_uploaded_image(upload, max_size=LISTING_IMAGE_MAX_SIZE, quality=82)


def optimize_profile_image(upload: UploadedFile) -> UploadedFile:
    return optimize_uploaded_image(upload, max_size=PROFILE_IMAGE_MAX_SIZE, quality=80)


def optimize_uploaded_image(upload: UploadedFile, *, max_size: tuple[int, int], quality: int) -> UploadedFile:
    try:
        if hasattr(upload, "seek"):
            upload.seek(0)
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        image = _normalize_image_mode(image)

        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        optimized_size = output.tell()
        if optimized_size <= 0 or optimized_size >= getattr(upload, "size", optimized_size + 1):
            _rewind(upload)
            return upload

        output.seek(0)
        filename = _webp_filename(getattr(upload, "name", "image"))
        return SimpleUploadedFile(filename, output.read(), content_type="image/webp")
    except (OSError, ValueError, UnidentifiedImageError):
        _rewind(upload)
        return upload


def _normalize_image_mode(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA"}:
        return image
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def _webp_filename(filename: str) -> str:
    path = PurePath(str(filename or "image"))
    stem = path.stem or "image"
    return f"{stem}.webp"


def _rewind(file: BinaryIO) -> None:
    try:
        file.seek(0)
    except (AttributeError, OSError):
        return
