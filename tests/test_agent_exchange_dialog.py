# -*- coding: utf-8 -*-
"""app.agent_exchange_dialog 테스트 (offscreen Qt)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget


class _StubParent(QWidget):
    """tr_str/app_lang/custom_presets만 흉내 내는 부모."""

    app_lang = "ko"
    custom_presets = None

    def tr_str(self, key, **kwargs):
        text = {
            "agent_dialog_title": "title",
            "agent_grp_input": "input",
            "agent_lbl_file": "file",
            "agent_file_ph": "ph",
            "agent_btn_browse": "browse",
            "agent_lbl_language": "lang",
            "agent_lbl_batch": "batch",
            "agent_lbl_style": "style",
            "agent_btn_export": "export",
            "agent_btn_import": "import",
            "agent_btn_status": "status",
            "agent_btn_reset": "reset",
            "agent_result_ph": "result",
            "agent_no_library": "no library",
            "btn_close": "close",
        }.get(key, key)
        return text.format(**kwargs) if kwargs else text


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_constructs(qapp):
    from app.agent_exchange_dialog import AgentExchangeDialog
    parent = _StubParent()
    dlg = AgentExchangeDialog(parent)
    # 스타일 콤보에는 최소 내장 프리셋들이 채워진다
    assert dlg.cmb_style.count() >= 7
    assert dlg.cmb_style.currentData() == "default"
    # 버튼 4종이 존재한다
    for btn in (dlg.btn_export, dlg.btn_import, dlg.btn_status,
                dlg.btn_reset):
        assert btn is not None
    dlg.close()


class _FakeCombo:
    def __init__(self, checked=None, data=None):
        self._checked = checked or []
        self._data = data

    def checked_items(self):
        return self._checked

    def currentData(self):
        return self._data


def test_dialog_prefill_from_parent(qapp):
    from app.agent_exchange_dialog import AgentExchangeDialog
    parent = _StubParent()
    parent.input_files = ["/movies/clip.mp4", "/movies/ep1.srt"]
    parent.cmb_langs = _FakeCombo(checked=["Japanese"])
    parent.cmb_style = _FakeCombo(data="drama_cinema")
    dlg = AgentExchangeDialog(parent)
    # 영상은 건너뛰고 첫 자막 파일, 첫 체크 언어, 스타일이 주입된다
    assert dlg.edit_file.text() == "/movies/ep1.srt"
    assert dlg.edit_lang.text() == "Japanese"
    assert dlg.cmb_style.currentData() == "drama_cinema"
    dlg.close()
