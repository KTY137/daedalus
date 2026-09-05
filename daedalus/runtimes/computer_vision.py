"""Bounded local OpenCV observations over supplied bytes, with no host effects.

This module grants no authority, opens no files, captures no screen and makes
no remote requests. Callers own capture admission, freshness, evidence storage
and task verification. A visual match is an observation, not task success.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import importlib
import math
import struct
from typing import Any, Iterable, Protocol
import zlib


class VisionError(ValueError):
    """A stable refusal code suitable for a canonical tool error observation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisionError("invalid_argument", f"{name} must be a finite number")
    if not low <= value <= high or not math.isfinite(value):
        raise VisionError("invalid_argument", f"{name} must be between {low} and {high}")
    return float(value)


def _integer(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise VisionError("invalid_argument", f"{name} must be an integer between {low} and {high}")
    return value


@dataclass(frozen=True)
class ImageCoordinateFrame:
    """Mapped pixels = origin + (crop offset + image pixels) * scale.

    Origin uses destination coordinates (possibly negative monitor positions).
    Crop offsets use pre-scale source pixels. Scale is destination units per
    source pixel, NOT an inferred Windows DPI percentage. No rounding occurs.
    """

    coordinate_space: str = "image"
    origin_x: float = 0.0
    origin_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    crop_x: float = 0.0
    crop_y: float = 0.0
    monitor_id: str | None = None
    window_id: str | None = None
    captured_at: str | None = None

    def __post_init__(self) -> None:
        if self.coordinate_space not in ("image", "desktop", "window"):
            raise VisionError("invalid_argument", "unknown coordinate space")
        for name in ("origin_x", "origin_y", "crop_x", "crop_y"):
            _number(getattr(self, name), name, -1_000_000, 1_000_000)
        for name in ("scale_x", "scale_y"):
            _number(getattr(self, name), name, 0.001, 1000)
        for name in ("monitor_id", "window_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 256):
                raise VisionError("invalid_argument", f"{name} must be a bounded identifier")
        if self.captured_at is not None:
            try:
                if not isinstance(self.captured_at, str) or len(self.captured_at) > 64:
                    raise ValueError()
                parsed = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError()
            except ValueError as exc:
                raise VisionError("invalid_argument", "captured_at requires an ISO timestamp with timezone") from exc

    def map_rect(self, x: int, y: int, width: int, height: int) -> dict[str, float]:
        for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
            _integer(value, name, 0, 1_000_000)
        return {
            "x": self.origin_x + (self.crop_x + x) * self.scale_x,
            "y": self.origin_y + (self.crop_y + y) * self.scale_y,
            "width": width * self.scale_x,
            "height": height * self.scale_y,
        }


@dataclass(frozen=True)
class VisionLimits:
    max_image_bytes: int = 8 * 1024 * 1024
    max_pixels: int = 16_777_216
    max_dimension: int = 8192

    def __post_init__(self) -> None:
        _integer(self.max_image_bytes, "max_image_bytes", 64, 64 * 1024 * 1024)
        _integer(self.max_pixels, "max_pixels", 1, 67_108_864)
        _integer(self.max_dimension, "max_dimension", 1, 16384)


class LocalOCRAdapter(Protocol):
    """Trusted, independently configured local OCR; never candidate supplied.

    Each row has text, confidence in [0, 1], x, y, width, height in image pixels.
    The adapter owns its own execution timeout and local-only implementation.
    """

    def recognize(self, bgr_image: Any) -> Iterable[dict[str, Any]]: ...


def _load_opencv() -> tuple[Any, Any]:
    try:
        return importlib.import_module("cv2"), importlib.import_module("numpy")
    except (ImportError, OSError) as exc:
        raise VisionError("opencv_unavailable", "Local OpenCV is unavailable; install the computer-vision extra") from exc


def _header_dimensions(data: bytes) -> tuple[str, int, int]:
    """Inspect supported headers BEFORE native decompression allocates pixels."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        pos, dimensions, has_data = 8, None, False
        while pos + 12 <= len(data):
            size = struct.unpack_from(">I", data, pos)[0]
            end = pos + size + 12
            if end > len(data):
                break
            kind = data[pos + 4:pos + 8]
            body = data[pos + 8:end - 4]
            if zlib.crc32(data[pos + 4:end - 4]) & 0xFFFFFFFF != struct.unpack_from(">I", data, end - 4)[0]:
                raise VisionError("malformed_image", "PNG chunk checksum mismatch")
            if pos == 8 and kind != b"IHDR":
                raise VisionError("malformed_image", "PNG must begin with IHDR")
            if kind == b"IHDR":
                if dimensions is not None or size != 13:
                    raise VisionError("malformed_image", "PNG has an invalid or duplicate header")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
                if depth != 8 or color not in (0, 2, 4, 6) or compression or filtering or interlace not in (0, 1):
                    raise VisionError("unsupported_image", "Only 8-bit grayscale/RGB PNG images are supported")
                dimensions = ("png", width, height)
            elif kind == b"acTL":
                raise VisionError("unsupported_image", "Animated PNG images are not supported")
            elif kind == b"IDAT":
                has_data = True
            elif kind == b"IEND":
                if size or end != len(data) or dimensions is None or not has_data:
                    break
                return dimensions
            pos = end
        raise VisionError("malformed_image", "PNG is truncated or has no complete image")
    if data.startswith(b"\xff\xd8"):
        pos, dimensions = 2, None
        while pos < len(data):
            if data[pos] != 0xFF:
                break
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in (0x00, 0xD8, 0xD9) or pos + 2 > len(data):
                break
            size = struct.unpack_from(">H", data, pos)[0]
            end = pos + size
            if size < 2 or end > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2):
                if dimensions is not None or size < 8:
                    break
                depth, height, width, components = struct.unpack_from(">BHHB", data, pos + 2)
                if depth != 8 or components not in (1, 3) or size != 8 + 3 * components:
                    raise VisionError("unsupported_image", "Only 8-bit grayscale/RGB JPEG images are supported")
                dimensions = ("jpeg", width, height)
            elif marker == 0xDA:
                if dimensions is not None and data.endswith(b"\xff\xd9"):
                    return dimensions
                break
            elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                raise VisionError("unsupported_image", "Unsupported JPEG frame coding")
            pos = end
        raise VisionError("malformed_image", "JPEG is truncated or has no supported image frame")
    raise VisionError("unsupported_image", "Only encoded PNG and JPEG bytes are supported")


class OpenCVVision:
    def __init__(self, *, limits: VisionLimits | None = None, ocr_adapter: LocalOCRAdapter | None = None) -> None:
        self.limits = limits if limits is not None else VisionLimits()
        if not isinstance(self.limits, VisionLimits):
            raise VisionError("invalid_argument", "limits must be VisionLimits")
        self.ocr_adapter = ocr_adapter

    def availability(self) -> dict[str, Any]:
        try:
            cv2, np = _load_opencv()
        except VisionError as exc:
            return {"opencv": False, "ocr": False, "reason": exc.code}
        return {"opencv": True, "opencv_version": cv2.__version__, "numpy_version": np.__version__,
                "ocr": self.ocr_adapter is not None, "formats": ["png", "jpeg"]}

    def _decode(self, data: bytes, frame: ImageCoordinateFrame | None) -> tuple[Any, dict[str, Any]]:
        if not isinstance(data, bytes):
            raise VisionError("invalid_argument", "image must be immutable encoded bytes")
        if not data or len(data) > self.limits.max_image_bytes:
            raise VisionError("image_size_limit", "Encoded image is empty or exceeds the byte limit")
        format_name, width, height = _header_dimensions(data)
        if (width <= 0 or height <= 0 or max(width, height) > self.limits.max_dimension
                or width * height > self.limits.max_pixels):
            raise VisionError("image_size_limit", "Image dimensions exceed the decode limits")
        if frame is not None and not isinstance(frame, ImageCoordinateFrame):
            raise VisionError("invalid_argument", "frame must be ImageCoordinateFrame")
        cv2, np = _load_opencv()
        try:
            pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        except cv2.error as exc:
            raise VisionError("malformed_image", "OpenCV could not decode the image") from exc
        if pixels is None or pixels.shape[:2] != (height, width) or pixels.dtype != np.uint8:
            raise VisionError("malformed_image", "Decoded image does not match its admitted header")
        if pixels.ndim == 2:
            pixels = cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR)
        elif pixels.ndim == 3 and pixels.shape[2] == 4:
            if not bool(np.all(pixels[:, :, 3] == 255)):
                raise VisionError("unsupported_image", "Transparent images require explicit compositing before vision analysis")
            pixels = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
        elif pixels.ndim != 3 or pixels.shape[2] != 3:
            raise VisionError("unsupported_image", "Unsupported decoded channel layout")
        return pixels, {"sha256": hashlib.sha256(data).hexdigest(), "format": format_name,
                        "width": width, "height": height,
                        "coordinate_frame": asdict(frame or ImageCoordinateFrame())}

    @staticmethod
    def _rect(frame: ImageCoordinateFrame, x: int, y: int, width: int, height: int) -> dict[str, Any]:
        return {"image_rect": {"x": x, "y": y, "width": width, "height": height},
                "mapped_rect": frame.map_rect(x, y, width, height)}

    def inspect(self, image: bytes, *, frame: ImageCoordinateFrame | None = None) -> dict[str, Any]:
        _, source = self._decode(image, frame)
        return {"status": "observed", "image": source}

    def match_template(self, image: bytes, template: bytes, *, threshold: float = 0.9,
                       ambiguity_margin: float = 0.03, max_matches: int = 16,
                       frame: ImageCoordinateFrame | None = None) -> dict[str, Any]:
        threshold = _number(threshold, "threshold", 0.01, 1.0)
        margin = _number(ambiguity_margin, "ambiguity_margin", 0.0, 1.0)
        _integer(max_matches, "max_matches", 1, 128)
        pixels, source = self._decode(image, frame)
        patch, template_source = self._decode(template, None)
        cv2, np = _load_opencv()
        th, tw = patch.shape[:2]
        if th > pixels.shape[0] or tw > pixels.shape[1]:
            raise VisionError("template_size", "Template must fit inside the source image")
        # CCOEFF subtracts each channel's mean, so uniform color is degenerate.
        if float(np.max(np.std(patch, axis=(0, 1)))) < 1e-6:
            raise VisionError("uninformative_template", "Template must contain spatial variation")
        scores = cv2.matchTemplate(pixels, patch, cv2.TM_CCOEFF_NORMED)
        if not bool(np.isfinite(scores).all()):
            raise VisionError("nonfinite_result", "OpenCV returned nonfinite template scores")
        best_score = float(np.max(scores))
        candidates: list[dict[str, Any]] = []
        score_floor = max(-1.0, threshold - margin)
        # Inspect at least two peaks even when the requested output limit is one.
        for _ in range(max(2, max_matches + 1)):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score < score_floor:
                break
            candidates.append({"score": float(score), **self._rect(frame or ImageCoordinateFrame(), x, y, tw, th)})
            # Keep overlapping alternate placements: suppressing a full template
            # footprint can hide a second true match in repeated visual patterns.
            # An uncertain one-pixel localization is conservatively ambiguous.
            scores[y, x] = -2
        accepted = [candidate for candidate in candidates if candidate["score"] >= threshold]
        ambiguous = (bool(accepted) and len(candidates) > 1
                     and candidates[0]["score"] - candidates[1]["score"] <= margin + 1e-7)
        status = "no_match" if not accepted else "ambiguous" if ambiguous else "matched"
        return {"status": status, "method": "TM_CCOEFF_NORMED", "image": source,
                "template": template_source, "best_score": best_score, "threshold": threshold,
                "ambiguity_margin": margin, "matches": accepted[:max_matches],
                "matches_truncated": len(accepted) > max_matches,
                "selected": accepted[0] if status == "matched" else None}

    def detect_changes(self, before: bytes, after: bytes, *, pixel_threshold: int = 20,
                       min_area: int = 4, max_regions: int = 64,
                       frame: ImageCoordinateFrame | None = None) -> dict[str, Any]:
        _integer(pixel_threshold, "pixel_threshold", 0, 255)
        _integer(min_area, "min_area", 1, self.limits.max_pixels)
        _integer(max_regions, "max_regions", 1, 1024)
        old, old_source = self._decode(before, frame)
        new, new_source = self._decode(after, frame)
        if old.shape != new.shape:
            raise VisionError("image_shape_mismatch", "Change detection requires images with identical dimensions")
        cv2, np = _load_opencv()
        mask = (np.max(cv2.absdiff(old, new), axis=2) > pixel_threshold).astype(np.uint8)
        changed_pixels = int(np.count_nonzero(mask))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        regions: list[dict[str, Any]] = []
        eligible = 0
        for index in range(1, count):
            x, y, width, height, area = (int(value) for value in stats[index])
            if area >= min_area:
                eligible += 1
                if len(regions) < max_regions:
                    regions.append({"changed_pixels": area,
                                    **self._rect(frame or ImageCoordinateFrame(), x, y, width, height)})
        return {"status": "changed" if changed_pixels else "unchanged", "before": old_source,
                "after": new_source, "changed_pixels": changed_pixels,
                "changed_fraction": changed_pixels / (old.shape[0] * old.shape[1]),
                "pixel_threshold": pixel_threshold, "min_area": min_area,
                "regions": regions, "regions_truncated": eligible > max_regions}

    def read_text(self, image: bytes, *, frame: ImageCoordinateFrame | None = None) -> dict[str, Any]:
        if self.ocr_adapter is None:
            return {"status": "unavailable", "reason": "local_ocr_not_configured", "words": []}
        pixels, source = self._decode(image, frame)
        words: list[dict[str, Any]] = []
        total_text = 0
        try:
            for row in self.ocr_adapter.recognize(pixels):
                if not isinstance(row, dict) or len(words) >= 4096:
                    raise VisionError("ocr_invalid_result", "OCR result must be a bounded collection of words")
                text = row.get("text")
                if not isinstance(text, str) or len(text) > 4096:
                    raise VisionError("ocr_invalid_result", "OCR text is invalid or too long")
                total_text += len(text)
                if total_text > 65536:
                    raise VisionError("ocr_invalid_result", "OCR text exceeds the output limit")
                x = _integer(row.get("x"), "OCR x", 0, source["width"] - 1)
                y = _integer(row.get("y"), "OCR y", 0, source["height"] - 1)
                width = _integer(row.get("width"), "OCR width", 1, source["width"] - x)
                height = _integer(row.get("height"), "OCR height", 1, source["height"] - y)
                # Some native OCR engines expose text/boxes but no calibrated
                # confidence. Keep that explicit instead of inventing a score.
                confidence = (None if row.get("confidence") is None else
                              _number(row.get("confidence"), "OCR confidence", 0, 1))
                words.append({"text": text, "confidence": confidence,
                              **self._rect(frame or ImageCoordinateFrame(), x, y, width, height)})
        except VisionError as exc:
            if exc.code not in {"invalid_argument", "ocr_invalid_result"}:
                raise
            raise VisionError("ocr_invalid_result", str(exc)) from exc
        except Exception as exc:
            raise VisionError("ocr_failed", "Configured local OCR adapter failed") from exc
        return {"status": "observed", "image": source, "words": words}
