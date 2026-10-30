# -*- coding: utf-8 -*-
"""set_ui_enabled가 커스텀 언어 위젯도 함께 토글하는지 테스트 (offscreen Qt).

작업 실행 중 txt_custom_lang/btn_add_lang이 활성화 상태로 남으면
언어 모델이 바뀌어 UI 상태 불일치가 생겼던 문제의 회귀 테스트.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QComboBox, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


_WIDGET_ATTRS = [
    "btn_save_api", "btn_manage_api_keys", "btn_advanced",
    "cmb_task_mode", "btn_out", "lbl_out", "btn_preview",
    "btn_skill_install", "btn_update_check",
    "btn_agent_exchange",
    "btn_clear_files",
    "btn_video_file", "lst_video_files", "btn_clear_video_file",
    "btn_audio_file", "lbl_audio_file", "btn_clear_audio_file",
    "cmb_langs", "btn_all_lang", "btn_none_lang",
    "txt_custom_lang", "btn_add_lang",
    "cmb_model", "spin_start", "spin_batch", "txt_desc",
    "lbl_style", "cmb_style",
    "chk_extract_audio", "chk_free",
    "spin_temp", "spin_top_p", "spin_top_k",
    "chk_streaming", "chk_thinking", "spin_thinking_budget",
    "cmb_thinking_level", "spin_audio_chunk", "chk_isolate_voice",
    "chk_append_lang", "chk_reuse_extracted",
    "chk_keep_extracted",
    "chk_resume", "chk_thoughts_log",
    "chk_token_stats",
    "chk_token_report", "spin_resume_context",
    "spin_batch_error_step", "spin_audio_chunk_error_step",
    "cmb_service_tier", "chk_use_enterprise",
    "cloud_project_input", "cloud_api_key_input",
    "cloud_location_input", "cmb_request_type",
    "btn_files", "lst_files",
    "btn_fetch", "btn_start", "btn_stop",
]


def _window(qapp):
    import app.main_window as mw

    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    for name in _WIDGET_ATTRS:
        if name == "cmb_task_mode":
            combo = QComboBox()
            combo.addItem("files")
            setattr(win, name, combo)
        else:
            setattr(win, name, QWidget())
    win.api_key_inputs = []
    win.api_key_labels = []
    return win


def test_custom_lang_widgets_toggle_with_ui(qapp, monkeypatch):
    import app.main_window as mw

    monkeypatch.setattr(mw, "genai", object())
    monkeypatch.setattr(mw, "gst", object())
    win = _window(qapp)
    win.set_ui_enabled(False)
    assert not win.txt_custom_lang.isEnabled()
    assert not win.btn_add_lang.isEnabled()
    assert not win.cmb_langs.isEnabled()
    win.set_ui_enabled(True)
    assert win.txt_custom_lang.isEnabled()
    assert win.btn_add_lang.isEnabled()
    assert win.cmb_langs.isEnabled()
