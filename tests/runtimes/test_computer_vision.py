"""Real small OpenCV fixtures, including independently asserted refusal paths."""
from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
from types import SimpleNamespace
import zlib

import pytest

from daedalus.runtimes import computer_vision as subject
from daedalus.runtimes.computer_vision import ImageCoordinateFrame, OpenCVVision, VisionError, VisionLimits


@pytest.fixture
def cv():
    return pytest.importorskip("cv2"), pytest.importorskip("numpy")


def encode(cv, pixels, extension=".png"):
    ok, encoded = cv[0].imencode(extension, pixels)
    assert ok
    return encoded.tobytes()


@pytest.fixture
def scene(cv):
    rng = cv[1].random.default_rng(731)
    patch = rng.integers(0, 256, (8, 10, 3), dtype=cv[1].uint8)
    pixels = rng.integers(0, 80, (60, 80, 3), dtype=cv[1].uint8)
    pixels[21:29, 32:42] = patch
    return pixels, patch


def test_import_does_not_load_optional_dependencies():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import daedalus.runtimes.computer_vision; "
         "assert 'cv2' not in sys.modules; assert 'numpy' not in sys.modules"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_optional_dependency_failure_is_explicit(monkeypatch):
    def unavailable(name):
        raise ImportError("fixture missing optional package")
    monkeypatch.setattr(subject.importlib, "import_module", unavailable)
    assert OpenCVVision().availability() == {"opencv": False, "ocr": False, "reason": "opencv_unavailable"}


def test_real_availability_is_versioned(cv):
    available = OpenCVVision().availability()
    assert available["opencv"] is True
    assert available["opencv_version"] == cv[0].__version__
    assert available["ocr"] is False


@pytest.mark.parametrize("extension,format_name", [(".png", "png"), (".jpg", "jpeg")])
def test_inspect_real_encoded_image(cv, scene, extension, format_name):
    data = encode(cv, scene[0], extension)
    result = OpenCVVision().inspect(data)
    assert result["status"] == "observed"
    assert result["image"] == {"sha256": hashlib.sha256(data).hexdigest(), "format": format_name,
                               "width": 80, "height": 60,
                               "coordinate_frame": subject.asdict(ImageCoordinateFrame())}


def test_unique_template_has_expected_coordinate_provenance(cv, scene):
    frame = ImageCoordinateFrame(coordinate_space="desktop", origin_x=-1920, origin_y=100,
                                 scale_x=1.5, scale_y=2, crop_x=40, crop_y=10,
                                 monitor_id="left-monitor", window_id="editor",
                                 captured_at="2026-09-05T08:00:00Z")
    result = OpenCVVision().match_template(encode(cv, scene[0]), encode(cv, scene[1]), frame=frame)
    assert result["status"] == "matched"
    assert result["selected"]["score"] == pytest.approx(1, abs=1e-5)
    assert result["selected"]["image_rect"] == {"x": 32, "y": 21, "width": 10, "height": 8}
    assert result["selected"]["mapped_rect"] == {"x": -1812, "y": 162, "width": 15, "height": 16}
    assert result["image"]["coordinate_frame"]["captured_at"] == "2026-09-05T08:00:00Z"


def test_duplicate_matches_are_ambiguous_even_when_return_limit_is_one(cv, scene):
    scene[0][40:48, 60:70] = scene[1]
    result = OpenCVVision().match_template(encode(cv, scene[0]), encode(cv, scene[1]), max_matches=1)
    assert result["status"] == "ambiguous"
    assert result["selected"] is None
    assert len(result["matches"]) == 1
    assert result["matches_truncated"] is True


def test_overlapping_repeated_templates_remain_ambiguous(cv):
    np = cv[1]
    patch = np.tile(np.array([0, 230], dtype=np.uint8), (4, 3))
    pixels = np.tile(np.array([0, 230], dtype=np.uint8), (4, 4))
    result = OpenCVVision().match_template(encode(cv, pixels), encode(cv, patch))
    assert result["status"] == "ambiguous"
    assert {item["image_rect"]["x"] for item in result["matches"]} == {0, 2}


def test_absent_template_does_not_invent_a_target(cv, scene):
    absent = cv[1].zeros_like(scene[0])
    result = OpenCVVision().match_template(encode(cv, absent), encode(cv, scene[1]))
    assert result["status"] == "no_match"
    assert result["matches"] == []
    assert result["selected"] is None


def test_constant_color_template_is_rejected(cv, scene):
    patch = cv[1].zeros((4, 4, 3), dtype=cv[1].uint8)
    patch[:, :, 0] = 255
    with pytest.raises(VisionError, match="spatial variation"):
        OpenCVVision().match_template(encode(cv, scene[0]), encode(cv, patch))


def test_larger_template_is_rejected(cv, scene):
    with pytest.raises(VisionError) as error:
        OpenCVVision().match_template(encode(cv, scene[1]), encode(cv, scene[0]))
    assert error.value.code == "template_size"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, True, "0.9", 10 ** 1000])
def test_invalid_threshold_rejected_before_decode(value, monkeypatch):
    monkeypatch.setattr(subject, "_load_opencv", lambda: pytest.fail("invalid threshold reached OpenCV"))
    with pytest.raises(VisionError):
        OpenCVVision().match_template(b"not an image", b"not a template", threshold=value)


def test_nonfinite_native_scores_are_rejected(cv, scene, monkeypatch):
    monkeypatch.setattr(cv[0], "matchTemplate", lambda *args: cv[1].array([[float("nan")]]))
    with pytest.raises(VisionError) as error:
        OpenCVVision().match_template(encode(cv, scene[0]), encode(cv, scene[1]))
    assert error.value.code == "nonfinite_result"


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff\xc0\x00", b"\x89PNG\r\n\x1a\n"])
def test_malformed_images_refused_without_native_decode(data, monkeypatch):
    monkeypatch.setattr(subject, "_load_opencv", lambda: pytest.fail("malformed header reached native decode"))
    with pytest.raises(VisionError):
        OpenCVVision().inspect(data)


def test_truncated_and_checksum_corrupt_png_refused(cv, scene):
    data = encode(cv, scene[0])
    for invalid in (data[:-5], data[:40] + bytes([data[40] ^ 1]) + data[41:]):
        with pytest.raises(VisionError) as error:
            OpenCVVision().inspect(invalid)
        assert error.value.code == "malformed_image"


def test_forged_huge_png_dimensions_refused_before_decode(cv, scene, monkeypatch):
    data = bytearray(encode(cv, scene[0]))
    struct.pack_into(">II", data, 16, 50000, 50000)
    struct.pack_into(">I", data, 29, zlib.crc32(data[12:29]) & 0xFFFFFFFF)
    monkeypatch.setattr(subject, "_load_opencv", lambda: pytest.fail("oversized header reached native decode"))
    with pytest.raises(VisionError) as error:
        OpenCVVision().inspect(bytes(data))
    assert error.value.code == "image_size_limit"


def test_forged_huge_jpeg_dimensions_refused_before_decode(cv, scene, monkeypatch):
    data = bytearray(encode(cv, scene[0], ".jpg"))
    marker = data.index(b"\xff\xc0")
    struct.pack_into(">HH", data, marker + 5, 60000, 60000)
    monkeypatch.setattr(subject, "_load_opencv", lambda: pytest.fail("oversized JPEG reached native decode"))
    with pytest.raises(VisionError) as error:
        OpenCVVision().inspect(bytes(data))
    assert error.value.code == "image_size_limit"


def test_native_decode_failure_is_a_typed_refusal(cv, scene, monkeypatch):
    data = encode(cv, scene[0])
    monkeypatch.setattr(cv[0], "imdecode", lambda *args: None)
    with pytest.raises(VisionError) as error:
        OpenCVVision().inspect(data)
    assert error.value.code == "malformed_image"


def test_byte_and_pixel_limits_apply(cv, scene):
    data = encode(cv, scene[0])
    for limits in (VisionLimits(max_image_bytes=64), VisionLimits(max_pixels=100)):
        with pytest.raises(VisionError) as error:
            OpenCVVision(limits=limits).inspect(data)
        assert error.value.code == "image_size_limit"


@pytest.mark.parametrize("kwargs", [{"scale_x": float("nan")}, {"scale_y": 0},
                                    {"origin_x": float("inf")}, {"crop_x": True},
                                    {"captured_at": "2026-09-05T08:00:00"},
                                    {"monitor_id": 123}, {"coordinate_space": "unknown"}])
def test_invalid_coordinate_provenance_is_rejected(kwargs):
    with pytest.raises(VisionError):
        ImageCoordinateFrame(**kwargs)


def test_transparent_image_requires_explicit_compositing(cv):
    data = encode(cv, cv[1].zeros((8, 8, 4), dtype=cv[1].uint8))
    with pytest.raises(VisionError) as error:
        OpenCVVision().inspect(data)
    assert error.value.code == "unsupported_image"


def test_exact_diff_regions_and_unchanged_status(cv):
    before = cv[1].zeros((30, 40, 3), dtype=cv[1].uint8)
    after = before.copy()
    after[3:8, 4:11, 2] = 255
    after[18:21, 25:29, 0] = 128
    frame = ImageCoordinateFrame(origin_x=100, scale_x=2)
    result = OpenCVVision().detect_changes(encode(cv, before), encode(cv, after), frame=frame)
    assert result["status"] == "changed"
    assert result["changed_pixels"] == 47
    assert result["changed_fraction"] == pytest.approx(47 / 1200)
    assert [region["image_rect"] for region in result["regions"]] == [
        {"x": 4, "y": 3, "width": 7, "height": 5}, {"x": 25, "y": 18, "width": 4, "height": 3}]
    assert result["regions"][0]["mapped_rect"]["x"] == 108
    same = OpenCVVision().detect_changes(encode(cv, before), encode(cv, before))
    assert same["status"] == "unchanged"
    assert same["changed_pixels"] == 0
    assert same["regions"] == []


def test_diff_region_limit_reports_truncation_and_tiny_changes(cv):
    before = cv[1].zeros((20, 20, 3), dtype=cv[1].uint8)
    after = before.copy()
    after[1, 1] = after[10, 10] = 255
    result = OpenCVVision().detect_changes(encode(cv, before), encode(cv, after), min_area=1, max_regions=1)
    assert result["regions_truncated"] is True
    assert result["changed_pixels"] == 2
    assert len(result["regions"]) == 1
    filtered = OpenCVVision().detect_changes(encode(cv, before), encode(cv, after))
    assert filtered["status"] == "changed"
    assert filtered["regions"] == []


def test_diff_requires_same_shape(cv, scene):
    with pytest.raises(VisionError) as error:
        OpenCVVision().detect_changes(encode(cv, scene[0]), encode(cv, scene[1]))
    assert error.value.code == "image_shape_mismatch"


def test_ocr_is_honestly_unavailable_without_adapter():
    assert OpenCVVision().read_text(b"no image is needed for availability") == {
        "status": "unavailable", "reason": "local_ocr_not_configured", "words": []}


def test_local_ocr_adapter_retains_text_and_coordinates(cv, scene):
    calls = []
    def recognize(pixels):
        calls.append(pixels.shape)
        return [{"text": "Save", "confidence": 0.98, "x": 3, "y": 4, "width": 20, "height": 12}]
    vision = OpenCVVision(ocr_adapter=SimpleNamespace(recognize=recognize))
    result = vision.read_text(encode(cv, scene[0]), frame=ImageCoordinateFrame(origin_x=100))
    assert calls == [(60, 80, 3)]
    assert result["words"][0]["text"] == "Save"
    assert result["words"][0]["mapped_rect"]["x"] == 103


@pytest.mark.parametrize("mutation", [{"confidence": float("nan")}, {"x": -1},
                                     {"width": 10000}, {"text": "a" * 4097}])
def test_invalid_ocr_result_fails_visibly(cv, scene, mutation):
    row = {"text": "Save", "confidence": 0.98, "x": 3, "y": 4, "width": 20, "height": 12}
    row.update(mutation)
    vision = OpenCVVision(ocr_adapter=SimpleNamespace(recognize=lambda pixels: [row]))
    with pytest.raises(VisionError) as error:
        vision.read_text(encode(cv, scene[0]))
    assert error.value.code == "ocr_invalid_result"


def test_ocr_failure_does_not_invent_text(cv, scene):
    def recognize(pixels):
        raise RuntimeError("local OCR fixture failed")
    with pytest.raises(VisionError) as error:
        OpenCVVision(ocr_adapter=SimpleNamespace(recognize=recognize)).read_text(encode(cv, scene[0]))
    assert error.value.code == "ocr_failed"
