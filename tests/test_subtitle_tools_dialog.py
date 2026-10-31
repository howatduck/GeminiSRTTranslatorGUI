# -*- coding: utf-8 -*-
"""자막 정리 도구 다이얼로그: 실행 중 닫기 방지 테스트 (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWorker:
    def __init__(self, running):
        self._running = running

    def isRunning(self):
        return self._running


def _dialog():
    from app.subtitle_tools_dialog import SubtitleToolsDialog
    return SubtitleToolsDialog(None)


def test_set_running_disables_close_button(qapp):
    dlg = _dialog()
    assert dlg.btn_close.isEnabled()
    dlg._set_running(True)
    assert not dlg.btn_close.isEnabled()
    dlg._set_running(False)
    assert dlg.btn_close.isEnabled()
    dlg.close()


def test_close_blocked_while_worker_running(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    dlg = _dialog()
    fake = _FakeWorker(True)
    dlg._worker = fake
    dlg.show()
    assert dlg.isVisible()
    dlg.close()
    assert dlg.isVisible()
    dlg.reject()
    assert dlg.isVisible()
    fake._running = False
    dlg.close()
    assert not dlg.isVisible()


def test_close_blocked_while_ilass_download_running(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    dlg = _dialog()
    fake = _FakeWorker(True)
    dlg._dl_worker = fake
    dlg.show()
    dlg.close()
    assert dlg.isVisible()
    fake._running = False
    dlg.close()
    assert not dlg.isVisible()
