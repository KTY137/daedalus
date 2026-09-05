"""Independent local OCR evidence: real OS recognition and controlled faults."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from daedalus.runtimes import computer_ocr as subject
from daedalus.runtimes.computer_vision import ImageCoordinateFrame, OpenCVVision, VisionError


@pytest.fixture
def pixels():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    return np.zeros((20, 50, 3), dtype=np.uint8)


@pytest.fixture
def fake_winrt(monkeypatch):
    state = SimpleNamespace(cancelled=0, bitmap_closed=0, writer_closed=0, pending=False,
                            engine_available=True, languages=[SimpleNamespace(language_tag="en-US")])
    class Operation:
        def cancel(self):
            state.cancelled += 1
        def __await__(self):
            async def result():
                if state.pending:
                    await asyncio.Future()
                rect = SimpleNamespace(x=2.2, y=3.4, width=12.6, height=7.2)
                word = SimpleNamespace(text="Save", bounding_rect=rect)
                return SimpleNamespace(lines=[SimpleNamespace(words=[word])])
            return result().__await__()
    class Engine:
        max_image_dimension = 4096
        available_recognizer_languages = state.languages
        @staticmethod
        def try_create_from_user_profile_languages():
            return Engine() if state.engine_available else None
        def recognize_async(self, bitmap):
            return Operation()
    class Bitmap:
        @staticmethod
        def create_copy_from_buffer(*args):
            return Bitmap()
        def close(self):
            state.bitmap_closed += 1
    class Writer:
        def write_bytes(self, data):
            assert isinstance(data, bytes)
        def detach_buffer(self):
            return b"pixels"
        def close(self):
            state.writer_closed += 1
    monkeypatch.setitem(sys.modules, "winrt.windows.media.ocr", SimpleNamespace(OcrEngine=Engine))
    monkeypatch.setitem(sys.modules, "winrt.windows.graphics.imaging", SimpleNamespace(
        SoftwareBitmap=Bitmap, BitmapPixelFormat=SimpleNamespace(BGRA8=1), BitmapAlphaMode=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "winrt.windows.storage.streams", SimpleNamespace(DataWriter=Writer))
    return state


@pytest.mark.parametrize("timeout", [0, -1, 61, True, float("inf"), float("nan"), 10 ** 1000])
def test_ocr_refuses_invalid_timeout(timeout):
    with pytest.raises(VisionError) as error:
        subject.WindowsOCR(timeout_s=timeout)
    assert error.value.code == "invalid_argument"


def test_native_boxes_round_outward_and_do_not_invent_confidence(pixels, fake_winrt):
    words = subject.WindowsOCR().recognize(pixels)
    assert words == [{"text": "Save", "confidence": None, "x": 2, "y": 3, "width": 13, "height": 8}]
    assert fake_winrt.bitmap_closed == 1
    assert fake_winrt.writer_closed == 1
    assert fake_winrt.cancelled == 0


def test_timeout_cancels_native_operation_and_closes_resources(pixels, fake_winrt):
    fake_winrt.pending = True
    with pytest.raises(VisionError) as error:
        subject.WindowsOCR(timeout_s=.01).recognize(pixels)
    assert error.value.code == "ocr_timeout"
    assert fake_winrt.cancelled == 1
    assert fake_winrt.bitmap_closed == 1
    assert fake_winrt.writer_closed == 1


def test_checkpoint_cancellation_cancels_native_operation(pixels, fake_winrt):
    fake_winrt.pending = True
    calls = []
    def checkpoint():
        calls.append(True)
        if len(calls) == 2:
            raise VisionError("cancelled", "fixture operator cancellation")
    with pytest.raises(VisionError) as error:
        subject.WindowsOCR(checkpoint=checkpoint).recognize(pixels)
    assert error.value.code == "cancelled"
    assert fake_winrt.cancelled == 1
    assert fake_winrt.bitmap_closed == 1
    assert fake_winrt.writer_closed == 1


def test_missing_language_refuses_before_native_recognition(pixels, fake_winrt):
    fake_winrt.engine_available = False
    with pytest.raises(VisionError) as error:
        subject.WindowsOCR().recognize(pixels)
    assert error.value.code == "ocr_unavailable"
    assert fake_winrt.bitmap_closed == fake_winrt.writer_closed == 0


def test_missing_provider_is_reported_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "winrt.windows.media.ocr", None)
    assert subject.WindowsOCR.availability()["available"] is False


def test_empty_language_inventory_reports_unavailable(fake_winrt):
    fake_winrt.languages.clear()
    assert subject.WindowsOCR.availability()["available"] is False


def test_running_event_loop_requires_worker_thread(pixels):
    async def inside_loop():
        with pytest.raises(VisionError) as error:
            subject.WindowsOCR().recognize(pixels)
        assert error.value.code == "ocr_context"
    asyncio.run(inside_loop())


def test_ocr_operational_refusal_code_survives_vision_wrapper(pixels, fake_winrt):
    import cv2
    ok, data = cv2.imencode(".png", pixels)
    assert ok
    fake_winrt.engine_available = False
    with pytest.raises(VisionError) as error:
        OpenCVVision(ocr_adapter=subject.WindowsOCR()).read_text(data.tobytes())
    assert error.value.code == "ocr_unavailable"


@pytest.mark.skipif(os.name != "nt", reason="real Windows OCR host acceptance")
def test_real_os_ocr_reads_generated_fixture_with_grounded_boxes():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    pytest.importorskip("winrt.windows.media.ocr")
    available = subject.WindowsOCR.availability()
    if not available["available"]:
        pytest.skip(available["reason"])
    pixels = np.full((140, 800, 3), 255, dtype=np.uint8)
    cv2.putText(pixels, "Ikarus Computer 123", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.7, (0, 0, 0), 3, cv2.LINE_AA)
    ok, data = cv2.imencode(".png", pixels)
    assert ok
    result = OpenCVVision(ocr_adapter=subject.WindowsOCR()).read_text(
        data.tobytes(), frame=ImageCoordinateFrame(origin_x=-100, scale_x=1.5))
    text = " ".join(word["text"] for word in result["words"])
    assert "ikarus" in text.casefold(), text
    assert "computer" in text.casefold(), text
    assert "123" in text, text
    for word in result["words"]:
        box = word["image_rect"]
        assert 20 <= box["x"] < 780
        assert 20 <= box["y"] < 100
        assert 0 < box["width"] < 700 and 0 < box["height"] < 100
        assert word["confidence"] is None
        assert word["mapped_rect"]["x"] == -100 + box["x"] * 1.5
