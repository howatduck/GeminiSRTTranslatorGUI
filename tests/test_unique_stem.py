# -*- coding: utf-8 -*-
"""app.main_window._unique_stem 테스트 (동일 파일명 충돌 방지 WIP)."""

import re

import pytest

pytest.importorskip("PyQt6")

from app.main_window import _unique_stem


def test_unique_stem_deterministic():
    p = "/data/season1/video.mp4"
    assert _unique_stem(p) == _unique_stem(p)


def test_unique_stem_distinguishes_same_name_different_folder():
    a = _unique_stem("/data/season1/video.mp4")
    b = _unique_stem("/data/season2/video.mp4")
    assert a != b
    assert a.startswith("video_")
    assert b.startswith("video_")


def test_unique_stem_format():
    stem = _unique_stem("/x/y/movie.mkv")
    assert re.fullmatch(r"movie_[0-9a-f]{8}", stem)


def test_unique_stem_same_folder_same_name_same_stem():
    # '추출된 자막 재사용'이 성립하려면 같은 경로는 항상 같은 stem이어야 한다
    assert _unique_stem("/a/b/c.srt") == _unique_stem("/a/b/c.srt")
