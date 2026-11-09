# -*- coding: utf-8 -*-
"""줄 끝 마침표 제거 (core.subtitle_io.strip_final_periods) 테스트.

한국어 자막 관행에 맞춰 줄 끝 마침표만 제거하고, 어조 부호
(물음표·느낌표·말줄임표)와 숫자·약어의 마침표는 유지하는지 검증한다.
저장 패치(_patched_save_subtitle_file) 경유 적용도 함께 확인한다.
"""

from datetime import timedelta

import pytest

from core.subtitle_io import (
    set_strip_final_periods,
    strip_final_periods,
    strip_final_periods_enabled,
)


@pytest.fixture(autouse=True)
def _restore_flag():
    before = strip_final_periods_enabled()
    yield
    set_strip_final_periods(before)


@pytest.mark.parametrize("src,expected", [
    # 기본: 줄 끝 마침표 제거
    ("안녕하세요.", "안녕하세요"),
    ("그는 집에 갔다.", "그는 집에 갔다"),
    ("そうだ。", "そうだ"),
    # 어조 부호는 유지
    ("정말이야?", "정말이야?"),
    ("정말이야!", "정말이야!"),
    ("어… 그게…", "어… 그게…"),
    ("말을 잇지 못했다...", "말을 잇지 못했다..."),
    # 느낌표 뒤 마침표는 마침표만 제거
    ("정말이야!.", "정말이야!"),
    # 줄 내부 마침표는 유지, 마지막 것만 제거
    ("안녕. 잘 가.", "안녕. 잘 가"),
    # 숫자 뒤 마침표는 유지
    ("목차 3.", "목차 3."),
    ("버전 2.5.", "버전 2.5."),
    # 약어의 마침표는 유지
    ("He lives in the U.S.", "He lives in the U.S."),
    # 따옴표 안쪽 마침표
    ('"다녀왔어."', '"다녀왔어"'),
    # HTML 태그 안쪽 마침표
    ("<i>안녕.</i>", "<i>안녕</i>"),
    # 마침표가 없으면 무변경
    ("그냥 문장", "그냥 문장"),
    ("", ""),
    (".", "."),
])
def test_strip_line_cases(src, expected):
    assert strip_final_periods(src) == expected


def test_strip_multiline():
    src = "첫째 줄.\n둘째 줄?\n셋째 줄."
    assert strip_final_periods(src) == "첫째 줄\n둘째 줄?\n셋째 줄"


def test_flag_default_on_and_toggle():
    assert strip_final_periods_enabled() is True
    set_strip_final_periods(False)
    assert strip_final_periods_enabled() is False
    set_strip_final_periods(True)
    assert strip_final_periods_enabled() is True


class _Sub:
    def __init__(self, content, start_s=0):
        self.content = content
        self.start = timedelta(seconds=start_s)
        self.end = timedelta(seconds=start_s + 2)
        self.index = 1


def _save(tmp_path, subs, name="out.srt"):
    from core.gst_patches import _patched_save_subtitle_file

    out = tmp_path / name
    _patched_save_subtitle_file("in.srt", subs, str(out))
    return out.read_text(encoding="utf-8")


def test_save_patch_strips_when_enabled(tmp_path):
    set_strip_final_periods(True)
    text = _save(tmp_path, [_Sub("안녕하세요.", 0), _Sub("반갑습니다?", 3)])
    assert "안녕하세요\n" in text
    assert "반갑습니다?" in text


def test_save_patch_keeps_when_disabled(tmp_path):
    set_strip_final_periods(False)
    text = _save(tmp_path, [_Sub("안녕하세요.", 0)])
    assert "안녕하세요." in text
