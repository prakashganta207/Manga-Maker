"""Atomic project saves survive a briefly locked target file (Windows antivirus / indexer)."""

import os

import pytest

from app.agents import state


def test_replace_retries_on_permission_error(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new")
    real, calls = os.replace, {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("Access is denied")
        real(a, b)

    monkeypatch.setattr(state.os, "replace", flaky)
    state.replace_with_retry(src, dst, delay=0)
    assert dst.read_text() == "new" and calls["n"] == 3


def test_replace_gives_up_after_attempts(tmp_path, monkeypatch):
    def always(a, b):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(state.os, "replace", always)
    with pytest.raises(PermissionError):
        state.replace_with_retry(tmp_path / "a", tmp_path / "b", attempts=3, delay=0)
