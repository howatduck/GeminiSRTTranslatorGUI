# -*- coding: utf-8 -*-
"""_skipped_videos_notice 테스트: 자막 없는 영상 제외 알림 문구.

추출된 자막이 있어 번역으로 진행하는 분기에서는 자막 없는 영상이
전사 질의 없이 조용히 제외됐었다. 제외 사실을 로그로 남기는 문구를
순수 함수로 검증한다.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from app.main_window import _skipped_videos_notice


def test_empty_returns_none():
    assert _skipped_videos_notice([]) is None


def test_single_video_names_file():
    msg = _skipped_videos_notice(["/tmp/a/movie.mp4"])
    assert msg is not None
    assert "1개" in msg
    assert "movie.mp4" in msg
    assert "전사" in msg


def test_multiple_videos_counts_and_names():
    msg = _skipped_videos_notice(["/tmp/a/one.mp4", "/tmp/b/two.mkv"])
    assert msg is not None
    assert "2개" in msg
    assert "one.mp4" in msg
    assert "two.mkv" in msg
