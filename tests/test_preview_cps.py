# -*- coding: utf-8 -*-
"""app.preview_editor._set_cps_item 테스트 (CPS 경고 배경 갱신 WIP)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidgetItem


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _dialog():
    from app.preview_editor import SubtitlePreviewDialog
    return SubtitlePreviewDialog.__new__(SubtitlePreviewDialog)


def test_set_cps_item_warns_over_threshold(qapp):
    item = QTableWidgetItem()
    entry = {"start_ms": 0, "end_ms": 1000, "text": "가" * 30}  # CPS 30 > 20
    _dialog()._set_cps_item(item, entry)
    assert item.text() == "30.0"
    assert item.background().color().name() == "#ff0000"
    assert item.foreground().color().name() == "#ffffff"


def test_set_cps_item_resets_background_when_back_under_threshold(qapp):
    dlg = _dialog()
    item = QTableWidgetItem()
    dlg._set_cps_item(item, {"start_ms": 0, "end_ms": 1000,
                             "text": "가" * 30})
    assert item.background().color().name() == "#ff0000"
    # 편집으로 CPS가 내려가면 경고 배경/전경이 함께 리셋돼야 한다 (버그 수정)
    dlg._set_cps_item(item, {"start_ms": 0, "end_ms": 2000, "text": "짧음"})
    assert item.text() == "1.0"
    assert item.background().style() == Qt.BrushStyle.NoBrush
    assert item.foreground().style() == Qt.BrushStyle.NoBrush


def test_set_cps_item_no_duration(qapp):
    item = QTableWidgetItem()
    _dialog()._set_cps_item(item, {"start_ms": None, "end_ms": None,
                                   "text": "x"})
    assert item.text() == "—"
    assert item.background().style() == Qt.BrushStyle.NoBrush
