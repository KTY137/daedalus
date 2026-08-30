# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import namedtuple

import pytest

from daedalus.storage import StorageUnavailable, check_storage, require_storage

_Usage = namedtuple("_Usage", ["total", "used", "free"])


def _usage(total: int, used: int, free: int):
    return _Usage(total, used, free)


def test_ok_state(monkeypatch):
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3),
    )
    status = check_storage("D:/grove")
    assert status.state == "ok"
    assert status.ok
    assert status.free_bytes == 50 * 1024**3
    assert status.min_free_bytes == int(2.0 * 1024**3)


def test_unavailable_when_below_watermark(monkeypatch):
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 99 * 1024**3, 1024**3),
    )
    status = check_storage("D:/grove")
    assert status.state == "storage_unavailable"
    assert not status.ok


def test_unavailable_when_volume_missing(monkeypatch):
    def boom(path):
        raise OSError("no such volume")

    monkeypatch.setattr("daedalus.storage.shutil.disk_usage", boom)
    status = check_storage("Z:/missing")
    assert status.state == "storage_unavailable"
    assert status.free_bytes == 0


def test_env_override(monkeypatch):
    monkeypatch.setenv("DAEDALUS_MIN_FREE_GIB", "10")
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 95 * 1024**3, 5 * 1024**3),
    )
    status = check_storage("D:/grove")
    assert status.min_free_bytes == 10 * 1024**3
    assert status.state == "storage_unavailable"
    # explicit argument wins over env
    assert check_storage("D:/grove", min_free_gib=1.0).state == "ok"


def test_env_override_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("DAEDALUS_MIN_FREE_GIB", "not-a-number")
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3),
    )
    assert check_storage("D:/grove").min_free_bytes == int(2.0 * 1024**3)


def test_require_storage_raises_with_path(monkeypatch):
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 100 * 1024**3, 0),
    )
    with pytest.raises(StorageUnavailable) as excinfo:
        require_storage("D:/grove")
    message = str(excinfo.value)
    assert "D:/grove" in message
    assert "0 bytes free" in message
    assert str(int(2.0 * 1024**3)) in message


def test_require_storage_returns_status_when_ok(monkeypatch):
    monkeypatch.setattr(
        "daedalus.storage.shutil.disk_usage",
        lambda path: _usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3),
    )
    status = require_storage("D:/grove")
    assert status.ok
