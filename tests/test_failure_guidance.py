# -*- coding: utf-8 -*-
"""실패 후 안내 테스트 — 원인 추정(failure_advice)과 선택지 다이얼로그.

실패로 끝나면 로그만 남고 끝나던 것을, 원인별 해결 안내와
[다시 시도/모델 변경/배치 절반] 선택지로 잇는 기능의 검증.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox

from core.errors import failure_advice

OVERLOAD_MSG = (
    "작업 실패 (키 1/1): 'Lanterns.S01E02.srt' - "
    "AI 모델 과부하(Overloaded 3회) 또는 라이브러리 종료 요청으로 중단됨."
)
QUOTA_MSG = "작업 실패 (키 1/1): 'a.srt' - API 할당량 고갈 (429)."
AUTH_MSG = "작업 실패 (키 1/1): 'a.srt' - 권한 없음 (API 인증 오류)."


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# --- failure_advice (순수 함수) ---

def test_advice_overload():
    label, advice = failure_advice([OVERLOAD_MSG])
    assert label == "모델 서버 과부하"
    assert any("모델을 바꾸면" in line for line in advice)
    assert any("배치 크기" in line for line in advice)


def test_advice_quota_and_auth():
    label, advice = failure_advice([QUOTA_MSG])
    assert label == "API 할당량 고갈"
    assert any("API 키를 추가" in line for line in advice)
    label, _ = failure_advice([AUTH_MSG])
    assert label == "API 키 인증 오류"


def test_advice_picks_most_frequent_kind():
    label, _ = failure_advice([OVERLOAD_MSG, QUOTA_MSG, QUOTA_MSG])
    assert label == "API 할당량 고갈"


def test_advice_empty_is_unknown():
    label, advice = failure_advice([])
    assert label == "일시적 오류"
    assert advice


# --- 선택지 다이얼로그 ---

class _FakeBox:
    Icon = QMessageBox.Icon
    ButtonRole = QMessageBox.ButtonRole
    next_click = "닫기"
    instances = []

    def __init__(self, parent):
        self.buttons = []
        self._tokens = {}
        _FakeBox.instances.append(self)

    def setIcon(self, icon):
        pass

    def setWindowTitle(self, t):
        pass

    def setText(self, t):
        self.text = t

    def setInformativeText(self, t):
        self.info = t

    def addButton(self, text, role):
        self.buttons.append(text)
        token = object()
        self._tokens[text] = token
        return token

    def exec(self):
        pass

    def clickedButton(self):
        return self._tokens.get(_FakeBox.next_click)


class _Combo:
    def __init__(self, items, current=0):
        self._items = items
        self._current = current

    def count(self):
        return len(self._items)

    def itemText(self, i):
        return self._items[i]

    def currentText(self):
        return self._items[self._current]

    def setCurrentIndex(self, i):
        self._current = i


class _Spin:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, v):
        self._value = v


def _dialog_window(qapp, monkeypatch):
    import app.main_window as mw

    monkeypatch.setattr(mw, "QMessageBox", _FakeBox)
    _FakeBox.instances = []
    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    win.last_job_errors = [OVERLOAD_MSG]
    win.logs = []
    win.append_log = lambda msg: win.logs.append(msg)
    win.cmb_model = _Combo(["gemini-3.5-flash-lite", "gemini-3.5-flash"])
    win.spin_batch = _Spin(714)
    win.started = 0

    def _start():
        win.started += 1

    win.start_translation = _start
    return win


def test_dialog_retry_restarts(qapp, monkeypatch):
    win = _dialog_window(qapp, monkeypatch)
    _FakeBox.next_click = "다시 시도"
    win._show_failure_dialog(1)
    assert win.started == 1
    box = _FakeBox.instances[-1]
    assert "모델 서버 과부하" in box.text
    assert "다시 시도" in box.buttons
    assert "모델 변경 후 재시도" in box.buttons
    assert "배치 크기 절반으로 재시도" in box.buttons


def test_dialog_model_change_restarts_with_new_model(qapp, monkeypatch):
    win = _dialog_window(qapp, monkeypatch)
    _FakeBox.next_click = "모델 변경 후 재시도"
    win._show_failure_dialog(1)
    assert win.started == 1
    assert win.cmb_model.currentText() == "gemini-3.5-flash"


def test_dialog_batch_halving_restarts_smaller(qapp, monkeypatch):
    win = _dialog_window(qapp, monkeypatch)
    _FakeBox.next_click = "배치 크기 절반으로 재시도"
    win._show_failure_dialog(1)
    assert win.started == 1
    assert win.spin_batch.value() == 357


def test_dialog_close_does_nothing(qapp, monkeypatch):
    win = _dialog_window(qapp, monkeypatch)
    _FakeBox.next_click = "닫기"
    win._show_failure_dialog(1)
    assert win.started == 0
