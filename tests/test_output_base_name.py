# -*- coding: utf-8 -*-
"""app.main_window._output_base_name 및 작업 빌더 출력명 테스트.

추출 temp 파일의 _unique_stem 해시가 최종 출력 파일명으로 새던
문제의 회귀 테스트. 해시는 temp 고유성 전용이며, 최종 출력명은
원본 stem이어야 한다 (동명 충돌 시에만 해시가 붙는다).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from app.i18n import I18N
from app.main_window import _output_base_name


def _real_tr(key, **kw):
    text = I18N["ko"].get(key, key)
    return text.format(**kw) if kw else text


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------- _output_base_name 단위 ----------

def test_plain_subtitle_unchanged():
    assert _output_base_name("/in/Movie.srt") == "Movie"
    assert _output_base_name("/in/Movie.Korean.srt") == "Movie.Korean"


def test_extracted_temp_hash_stripped():
    p = "/out/Stuart.Fails.S01E09-cakes_ab23c91b_extracted.srt"
    assert _output_base_name(p) == "Stuart.Fails.S01E09-cakes"


def test_extracted_temp_without_hash():
    assert _output_base_name("/out/Movie_extracted.srt") == "Movie"


def test_non_hex_suffix_not_stripped():
    # 8자여도 hex가 아니면 해시로 보지 않는다
    assert _output_base_name("/out/Movie_xyz12345_extracted.srt") \
        == "Movie_xyz12345"


def test_user_file_ending_in_hex_not_stripped():
    # _extracted가 아닌 일반 파일은 stem 끝이 hex여도 그대로 둔다
    assert _output_base_name("/in/Movie_deadbeef.srt") == "Movie_deadbeef"


# ---------- 작업 빌더 통합 ----------

class _Check:
    def __init__(self, value):
        self._value = value

    def isChecked(self):
        return self._value


def _window(qapp, tmp_path):
    import app.main_window as mw

    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    win.app_lang = "ko"
    win.tr_str = _real_tr
    win.output_dir = str(tmp_path)
    win.chk_append_lang = _Check(True)
    win.chk_force_retranslate = _Check(False)
    win.append_log = lambda *a, **k: None
    return win


def test_jobs_single_extracted_output_has_no_hash(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    video = tmp_path / "Stuart-cakes.mkv"
    video.write_bytes(b"")
    temp = tmp_path / "Stuart-cakes_ab23c91b_extracted.srt"
    jobs = win._create_translation_jobs(
        ["Korean"], [str(temp)], False, False, None, [str(video)])
    assert len(jobs) == 1
    out = jobs[0][2]
    assert os.path.basename(out) == "Stuart-cakes.ko.srt"
    # 비디오 컨텍스트도 이름으로 매칭돼야 한다
    assert jobs[0][5] == str(video)


def test_jobs_two_same_name_videos_get_distinct_outputs(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    t1 = tmp_path / "Movie_1111aaaa_extracted.srt"
    t2 = tmp_path / "Movie_2222bbbb_extracted.srt"
    jobs = win._create_translation_jobs(
        ["Korean"], [str(t1), str(t2)], False, False, None, [])
    assert len(jobs) == 2
    names = sorted(os.path.basename(j[2]) for j in jobs)
    assert names[0] != names[1]
    for n in names:
        assert n.startswith("Movie_") and n.endswith(".ko.srt")


def test_jobs_plain_subtitle_output_unchanged(qapp, tmp_path):
    win = _window(qapp, tmp_path)
    jobs = win._create_translation_jobs(
        ["Korean"], ["/in/Movie.srt"], False, False, None, [])
    assert len(jobs) == 1
    assert os.path.basename(jobs[0][2]) == "Movie.ko.srt"
