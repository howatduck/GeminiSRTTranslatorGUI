# -*- coding: utf-8 -*-
"""종료 요약 카운트 테스트 — 실패 작업이 '번역'으로 오집계되던 버그.

_handle_job_error도 completed_jobs를 올리는데 요약이 (완료-스킵)으로만
계산돼, 전부 실패해도 "번역 1개"로 표시됐다 (2026-11-10 실사용 로그).
실패 전용 카운터를 분리해 요약에 구분 표기하는지 검증한다.
"""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from app.i18n import I18N


def _real_tr(key, **kw):
    text = I18N["ko"].get(key, key)
    return text.format(**kw) if kw else text


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Bar:
    def setValue(self, v):
        pass

    def setFormat(self, f):
        pass


class _Btn:
    def isEnabled(self):
        return False


class _Check:
    def __init__(self, value):
        self._value = value

    def isChecked(self):
        return self._value


def _window(qapp, monkeypatch, total=1, skipped=0):
    import app.main_window as mw

    monkeypatch.setattr(mw, "read_report_cost", lambda path: None)
    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    win.job_completion_lock = threading.Lock()
    win.total_jobs = total
    win.completed_jobs = skipped
    win.failed_jobs = 0
    win.skipped_completed_jobs = skipped
    win.jobs = []
    win.recent_outputs = []
    win.last_job_errors = []
    win.progress_bar = _Bar()
    win.btn_start = _Btn()
    win.translation_worker = None
    win.job_queue = None
    win._stop_requested = False
    win.extracted_temp_files = []
    win.chk_keep_extracted = _Check(True)
    win.chk_reuse_extracted = _Check(True)
    win.app_lang = "ko"
    win.tr_str = _real_tr
    win.logs = []
    win.append_log = lambda msg: win.logs.append(msg)
    win.set_ui_enabled = lambda enabled: None
    return win


def _summary_line(win):
    for line in win.logs:
        if "요약:" in line:
            return line
    raise AssertionError(f"요약 줄이 없음: {win.logs}")


def test_all_failed_summary(qapp, monkeypatch):
    # 제보된 실제 케이스: 작업 1개, 실패 → 예전엔 "번역 1개"로 찍혔다
    win = _window(qapp, monkeypatch, total=1)
    win._handle_job_error("모델 과부하")
    win.translation_finished()
    assert _summary_line(win) == "  요약: 번역 0개 · 스킵 0개 · 실패 1개"


def test_mixed_summary(qapp, monkeypatch):
    win = _window(qapp, monkeypatch, total=3, skipped=1)
    win._handle_job_translated("/out/a.ko.srt", "Korean")
    win._handle_job_error("오류")
    win.translation_finished()
    assert _summary_line(win) == "  요약: 번역 1개 · 스킵 1개 · 실패 1개"


def test_all_success_summary_has_no_failure_segment(qapp, monkeypatch):
    win = _window(qapp, monkeypatch, total=2)
    win._handle_job_translated("/out/a.ko.srt", "Korean")
    win._handle_job_translated("/out/b.ko.srt", "Korean")
    win.translation_finished()
    assert _summary_line(win) == "  요약: 번역 2개 · 스킵 0개"
