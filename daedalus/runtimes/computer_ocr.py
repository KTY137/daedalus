"""Local Windows OCR over supplied pixels, using installed OS language packs.

No network, files, model downloads or arbitrary executables. Windows OCR does
not publish confidence scores; observations explicitly retain that absence.
"""
from __future__ import annotations

import asyncio
import math
import os
from typing import Any, Callable

from .computer_vision import VisionError


class WindowsOCR:
    def __init__(self, checkpoint: Callable[[], None] | None = None, timeout_s: float = 15):
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= 60 or not math.isfinite(timeout_s):
            raise VisionError("invalid_argument", "OCR timeout must be positive and at most 60 seconds")
        self.checkpoint = checkpoint or (lambda: None)
        self.timeout_s = timeout_s

    @staticmethod
    def availability() -> dict:
        if os.name != "nt":
            return {"available": False, "reason": "Windows OCR requires Windows"}
        try:
            from winrt.windows.media.ocr import OcrEngine
            languages = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
            return {"available": bool(languages), "languages": languages,
                    "reason": "" if languages else "No Windows OCR language installed"}
        except (ImportError, OSError, RuntimeError):
            return {"available": False, "reason": "Install daedalus[computer] for Windows OCR"}

    def recognize(self, bgr_image: Any) -> list[dict]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise VisionError("ocr_context", "Synchronous OCR must run in the computer worker thread")
        self.checkpoint()
        return asyncio.run(self._recognize(bgr_image))

    async def _recognize(self, image: Any) -> list[dict]:
        import cv2
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter

        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise VisionError("ocr_unavailable", "No Windows OCR language is installed")
        height, width = image.shape[:2]
        if max(width, height) > OcrEngine.max_image_dimension:
            raise VisionError("ocr_image_size", "Image exceeds the Windows OCR dimension limit")
        pixels = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA).tobytes()
        writer = DataWriter()
        bitmap = None
        try:
            writer.write_bytes(pixels)
            buffer = writer.detach_buffer()
            bitmap = SoftwareBitmap.create_copy_from_buffer(
                buffer, BitmapPixelFormat.BGRA8, width, height)
            operation = engine.recognize_async(bitmap)

            async def await_result():
                return await operation

            pending = asyncio.create_task(await_result())
            deadline = asyncio.get_running_loop().time() + self.timeout_s
            try:
                while not pending.done():
                    self.checkpoint()
                    if asyncio.get_running_loop().time() >= deadline:
                        raise VisionError("ocr_timeout", "Local OCR exceeded its deadline")
                    await asyncio.wait((pending,), timeout=.1)
                result = await pending
                self.checkpoint()
            finally:
                if not pending.done():
                    operation.cancel()
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        pass
            rows = []
            for line in result.lines:
                for word in line.words:
                    rect = word.bounding_rect
                    x, y = max(0, int(rect.x)), max(0, int(rect.y))
                    right, bottom = min(width, math.ceil(rect.x + rect.width)), min(height, math.ceil(rect.y + rect.height))
                    if right > x and bottom > y:
                        rows.append({"text": word.text, "confidence": None,
                                     "x": x, "y": y, "width": right - x, "height": bottom - y})
            return rows
        finally:
            if bitmap is not None:
                bitmap.close()
            writer.close()
