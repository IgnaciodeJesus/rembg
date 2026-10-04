"""Bound image/model work shared by the optional HTTP API and Gradio UI.

The caller supplies the real model factory/remover. A single non-blocking slot
prevents concurrent API and UI calls from duplicating model memory; only one
session is retained. This is backpressure, not a killable inference deadline.
"""

import logging
import struct
import threading
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from .server_security import MAX_IMAGE_BYTES, server_options

MAX_IMAGE_PIXELS = 20_000_000
MAX_OUTPUT_BYTES = 40 * 1024 * 1024


def validate_image(content):
    """Reject oversized, malformed or multi-frame images before loading a model."""
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds server size limit")
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(413, "Image exceeds server pixel limit")
            if getattr(image, "n_frames", 1) != 1:
                raise HTTPException(400, "Use a single-frame image")
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except Image.DecompressionBombError:
        raise HTTPException(413, "Image exceeds server pixel limit") from None
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        EOFError,
        struct.error,
        OverflowError,
    ):
        raise HTTPException(400, "Invalid image") from None


def background_color(value):
    """Parse an RGBA query value without exposing a ValueError as HTTP 500."""
    if value is None:
        return None
    try:
        if len(value) > 32:
            raise ValueError()
        parts = tuple(int(part) for part in value.split(","))
        if len(parts) != 4 or any(not 0 <= part <= 255 for part in parts):
            raise ValueError()
        return parts
    except (TypeError, ValueError):
        raise HTTPException(400, "Background color must be four RGBA bytes") from None


class ImageProcessor:
    """One active inference and one cached session for both API and UI."""

    def __init__(self, session_factory, remover, models):
        self._session_factory = session_factory
        self._remover = remover
        self._models = frozenset(models)
        self._slot = threading.Lock()
        self._session = None
        self._key = None

    def process(self, content, model, extras=None, **kwargs):
        if model not in self._models:
            raise HTTPException(400, "Unsupported server model")
        options = server_options(extras)
        if not self._slot.acquire(blocking=False):
            raise HTTPException(
                503,
                "Image processor is busy; retry later",
                headers={"Retry-After": "1"},
            )
        try:
            validate_image(content)
            # sam_quant changes the model session; processing-only extras do not.
            key = (model, options.get("sam_quant", False))
            if self._key != key:
                # Release the previous session before constructing a different one.
                self._session = None
                self._key = None
                self._session = self._session_factory(model, **options)
                self._key = key
            result = self._remover(content, session=self._session, **kwargs, **options)
            if not isinstance(result, bytes) or len(result) > MAX_OUTPUT_BYTES:
                raise HTTPException(500, "Image output exceeds server limit")
            return result
        except HTTPException:
            raise
        except Exception:
            # Never send model exceptions (paths, sources or library state) to a
            # client. Discard a potentially broken session before a later retry.
            self._session = None
            self._key = None
            logging.getLogger(__name__).warning("Model processing unavailable")
            raise HTTPException(
                503,
                "Image processor is unavailable; retry later",
                headers={"Retry-After": "60"},
            ) from None
        finally:
            self._slot.release()
