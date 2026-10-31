# -*- coding: utf-8 -*-
"""미리보기 편집기 닫기 가드 + 원자적 저장 테스트 (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox

SAMPLE_SRT = (
    "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n"
    "2\n00:00:03,000 --> 00:00:04,000\nSecond line\n"
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _dialog(tmp_path):
    from app.preview_editor import SubtitlePreviewDialog
    path = tmp_path / "trans.srt"
    path.write_text(SAMPLE_SRT, encoding="utf-8")
    dlg = SubtitlePreviewDialog(None, str(path))
    return dlg, path


def _patch_question(monkeypatch, answer):
    calls = []

    def _question(*args, **kwargs):
        calls.append(1)
        return answer

    monkeypatch.setattr(QMessageBox, "question", _question)
    return calls


def _close_dialog(monkeypatch, dlg):
    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)
    dlg.close()


def test_reject_blocked_when_dirty_and_user_says_no(qapp, tmp_path, monkeypatch):
    dlg, _ = _dialog(tmp_path)
    dlg._dirty = True
    _patch_question(monkeypatch, QMessageBox.StandardButton.No)
    dlg.show()
    assert dlg.isVisible()
    dlg.reject()
    assert dlg.isVisible()
    _close_dialog(monkeypatch, dlg)


def test_reject_closes_when_dirty_and_user_says_yes(qapp, tmp_path, monkeypatch):
    dlg, _ = _dialog(tmp_path)
    dlg._dirty = True
    _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)
    dlg.show()
    dlg.reject()
    assert not dlg.isVisible()


def test_close_event_blocked_when_dirty_and_user_says_no(
        qapp, tmp_path, monkeypatch):
    dlg, _ = _dialog(tmp_path)
    dlg._dirty = True
    _patch_question(monkeypatch, QMessageBox.StandardButton.No)
    dlg.show()
    assert dlg.isVisible()
    dlg.close()
    assert dlg.isVisible()
    _close_dialog(monkeypatch, dlg)


def test_close_event_asks_only_once_when_user_says_yes(
        qapp, tmp_path, monkeypatch):
    dlg, _ = _dialog(tmp_path)
    dlg._dirty = True
    calls = _patch_question(monkeypatch, QMessageBox.StandardButton.Yes)
    dlg.show()
    dlg.close()
    assert not dlg.isVisible()
    assert len(calls) == 1


def test_save_is_atomic_and_keeps_backup(qapp, tmp_path, monkeypatch):
    from app.preview_editor import format_srt
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg, path = _dialog(tmp_path)
    dlg.trans_entries[0]["text"] = "바뀐 번역"
    dlg._dirty = True
    dlg._save()
    assert not dlg._dirty
    assert path.read_text(encoding="utf-8") == format_srt(dlg.trans_entries)
    assert (tmp_path / "trans.srt.bak").read_text(encoding="utf-8") == SAMPLE_SRT
    assert not (tmp_path / "trans.srt.tmp").exists()


def test_save_failure_keeps_original_intact(qapp, tmp_path, monkeypatch):
    import app.preview_editor as pe
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    def _boom(entries):
        raise RuntimeError("format failure")

    monkeypatch.setattr(pe, "format_srt", _boom)
    dlg, path = _dialog(tmp_path)
    dlg.trans_entries[0]["text"] = "바뀐 번역"
    dlg._dirty = True
    dlg._save()
    assert dlg._dirty
    assert path.read_text(encoding="utf-8") == SAMPLE_SRT
    assert not (tmp_path / "trans.srt.tmp").exists()
