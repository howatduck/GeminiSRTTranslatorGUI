# -*- coding: utf-8 -*-
"""Tkinter 포팅(app_tk) 회귀 테스트.

설정 저장소·워커·모델 체인은 디스플레이 없이도 검증하고, 창 구성
테스트는 DISPLAY가 있을 때만(xvfb-run) 실행한다.
"""

import json
import os
import queue
import threading
import time
import types

import pytest


# ----------------------------------------------------------------------
# JsonSettings
# ----------------------------------------------------------------------
def test_json_settings_roundtrip_and_casts(tmp_path):
    from app_tk.settings import JsonSettings

    path = str(tmp_path / "settings.json")
    s = JsonSettings("Org", "App", path=path)
    assert s.value("missing", "dflt") == "dflt"
    s.setValue("batch_size", 250)
    s.setValue("append_lang", True)
    s.setValue("temperature", 0.7)
    s.setValue("last_model", "gemini-x")

    s2 = JsonSettings("Org", "App", path=path)
    assert s2.value("batch_size", 0, type=int) == 250
    assert s2.value("append_lang", False, type=bool) is True
    assert s2.value("temperature", 0.0, type=float) == 0.7
    assert s2.value("last_model", "", type=str) == "gemini-x"
    # 문자열로 저장된 값의 캐스팅 (QSettings ini 이전 대비)
    s2.setValue("flag_str", "true")
    assert s2.value("flag_str", False, type=bool) is True
    s2.setValue("num_str", "42")
    assert s2.value("num_str", 0, type=int) == 42


def test_json_settings_migrates_qsettings_ini(tmp_path, monkeypatch):
    from app_tk.settings import JsonSettings

    home = tmp_path / "home"
    conf_dir = home / ".config" / "GeminiSrtTranslatorGUI"
    conf_dir.mkdir(parents=True)
    (conf_dir / "GeminiSrtTranslatorGUI.conf").write_text(
        "[General]\n"
        "gemini_api_key_1=migrated-key\n"
        "batch_size=777\n"
        "append_lang=true\n",
        encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("app_tk.settings._read_qsettings_via_pyqt",
                        lambda org, app: None)

    path = str(tmp_path / "tk.json")
    s = JsonSettings("GeminiSrtTranslatorGUI", "GeminiSrtTranslatorGUI", path=path)
    assert s.value("gemini_api_key_1", "") == "migrated-key"
    assert s.value("batch_size", 0, type=int) == 777
    assert s.value("append_lang", False, type=bool) is True
    # 이전 결과가 JSON 파일로 고정됐는지
    assert json.loads(open(path, encoding="utf-8").read())["batch_size"] in (777, "777")


# ----------------------------------------------------------------------
# Signal / 워커
# ----------------------------------------------------------------------
def test_signal_dispatch_and_disconnect():
    from app_tk.workers import Signal

    sig = Signal()
    got = []
    sig.connect(got.append)
    sig.emit("a")
    sig.disconnect(got.append)
    sig.emit("b")
    assert got == ["a"]

    dispatched = []
    sig2 = Signal()
    sig2.dispatch = dispatched.append
    seen = []
    sig2.connect(seen.append)
    sig2.emit("x")
    assert seen == [] and len(dispatched) == 1
    dispatched[0]()
    assert seen == ["x"]


def test_model_fetcher_tk_filter_parity(monkeypatch):
    import app_tk.workers as workers

    class _M:
        def __init__(self, name, methods):
            self.name = name
            self.supported_generation_methods = methods

    class _Models:
        def list(self):
            return [
                _M("models/gemini-2.5-flash", ["generateContent"]),
                _M("models/gemini-embedding-001", ["embedContent"]),
                _M("models/gemini-omni-1.2-flash", []),
            ]

    fake_client = types.SimpleNamespace(models=_Models())
    monkeypatch.setattr(workers, "genai",
                        types.SimpleNamespace(Client=lambda api_key: fake_client))

    for include_all, expected in (
        (False, ["gemini-2.5-flash"]),
        (True, ["gemini-2.5-flash", "gemini-embedding-001", "gemini-omni-1.2-flash"]),
    ):
        thread = workers.ModelFetcherThread("key", include_all=include_all)
        got = []
        thread.models_fetched.connect(got.append)
        thread.run()
        assert got == [expected]


def test_translation_worker_tk_cancel(monkeypatch):
    import app_tk.workers as workers
    from core.backend import BackendCancelRequested

    class FakeAdapter:
        def run(self, args, mode=None, cancel_token=None):
            for _ in range(200):
                if cancel_token and cancel_token():
                    raise BackendCancelRequested("cancelled")
                time.sleep(0.05)
            raise AssertionError("취소가 걸리지 않음")

    monkeypatch.setattr(workers, "GstAdapter", FakeAdapter)
    job_queue = queue.Queue()
    job_queue.put(("in.srt", "Korean", "out.srt", False, None, None))
    worker = workers.TranslationWorker(["key"], job_queue, {"task_mode": "translate"})
    finished = threading.Event()
    translated = []
    worker.finished_signal.connect(finished.set)
    worker.job_translated.connect(lambda *a: translated.append(a))
    worker.start()
    time.sleep(0.3)
    worker.requestInterruption()
    assert finished.wait(timeout=5)
    worker.join(timeout=5)
    assert translated == []


# ----------------------------------------------------------------------
# 모델 체인 (Tk 변수 없이 스텁으로 검증)
# ----------------------------------------------------------------------
def _chain_window(order, disabled=(), fallback_on=True, show_all=False):
    from app_tk.main_window import TranslatorAppTk

    win = object.__new__(TranslatorAppTk)
    win.vars = {"model_fallback": types.SimpleNamespace(get=lambda: fallback_on)}
    win.model_fallback_order = list(order)
    win.model_fallback_disabled = list(disabled)
    win.show_all_models = show_all
    return win


def test_tk_model_chain_parity():
    win = _chain_window(["m2", "m3"])
    assert win._model_chain("m1") == ["m1", "m2", "m3"]
    win = _chain_window(["m2", "m3"], fallback_on=False)
    assert win._model_chain("m1") == ["m1"]
    win = _chain_window(["m2", "m3"], disabled=["m2"])
    assert win._model_chain("m1") == ["m1", "m3"]
    # 번역 불가 모델은 기본 제외, '모든 모델 표시'면 포함 (PyQt판과 동일)
    win = _chain_window(["gemini-embedding-001", "m2"])
    assert win._model_chain("m1") == ["m1", "m2"]
    win = _chain_window(["gemini-embedding-001", "m2"], show_all=True)
    assert win._model_chain("m1") == ["m1", "gemini-embedding-001", "m2"]


# ----------------------------------------------------------------------
# 창 구성 (디스플레이 필요)
# ----------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_tk_window_builds_and_settings_roundtrip(tmp_path):
    tk = pytest.importorskip("tkinter")
    import app_tk.main_window as mw
    if mw.gst is None:
        pytest.skip("gemini-srt-translator 미설치 환경 (시작 경고 모달 방지)")
    from app_tk.main_window import TranslatorAppTk

    root = tk.Tk()
    root.withdraw()
    try:
        path = str(tmp_path / "tk-settings.json")
        app = TranslatorAppTk(root, settings_path=path)
        # 핵심 위젯·변수가 구성됐는지
        assert app.vars["model"].get()
        assert app.log_output is not None
        app.api_key_vars[0].set("test-key-1")
        app.vars["batch"].set(321)
        app.save_settings()
        data = json.loads(open(path, encoding="utf-8").read())
        assert data["gemini_api_key_1"] == "test-key-1"
        assert data["batch_size"] == 321

        # 재시작(새 인스턴스) 시 복원되는지
        app2 = TranslatorAppTk(root, settings_path=path)
        assert app2.api_key_vars[0].get() == "test-key-1"
        assert app2.vars["batch"].get() == 321
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# 2단계: 레트로 테마 + 다이얼로그 4종 (디스플레이 필요)
# ----------------------------------------------------------------------
class _StubApp:
    """다이얼로그 테스트용 최소 앱 스텁 (tr_str만 실제 i18n 사용)."""

    app_lang = "ko"
    custom_presets = {}
    input_files = []

    def tr_str(self, key, **kwargs):
        from app.i18n import I18N
        template = I18N["ko"].get(key, key)
        if kwargs:
            try:
                return template.format(**kwargs)
            except Exception:
                return template
        return template


def _no_modal(monkeypatch):
    class FakeMB:
        @staticmethod
        def showinfo(*a, **k):
            return "ok"

        @staticmethod
        def showwarning(*a, **k):
            return "ok"

        @staticmethod
        def showerror(*a, **k):
            return "ok"

        @staticmethod
        def askyesno(*a, **k):
            return True

    monkeypatch.setattr("app_tk.dialogs2.messagebox", FakeMB)


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_retro_theme_applies_and_strip_builds(tmp_path):
    tk = pytest.importorskip("tkinter")
    from app_tk.theme import apply_retro_theme, make_title_strip, FACE, NAVY

    root = tk.Tk()
    root.withdraw()
    try:
        apply_retro_theme(root)
        assert root.cget("background") == FACE
        strip = make_title_strip(root, "TEST", "sub")
        assert str(strip.cget("background")) == NAVY
        # 이름 폰트가 GC로 사라지지 않고 유지되는지 (버튼 폭 폭증 회귀 방지)
        from tkinter import font as tkfont
        from tkinter import ttk as _ttk
        assert "RetroUI" in tkfont.names()
        btn = _ttk.Button(root, text="전체 해제")
        btn.pack()
        root.update_idletasks()
        assert btn.winfo_reqwidth() < 120
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_preview_dialog_loads_edits_and_saves(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    _no_modal(monkeypatch)
    from app_tk.dialogs2 import SubtitlePreviewDialogTk

    srt = ("1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\nSecond line\n")
    trans = tmp_path / "movie.ko.srt"
    orig = tmp_path / "movie.srt"
    trans.write_text(srt, encoding="utf-8")
    orig.write_text(srt, encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    try:
        dlg = SubtitlePreviewDialogTk(root, _StubApp(), str(trans), str(orig))
        root.update_idletasks()
        assert len(dlg.trans_entries) == 2
        assert len(dlg.tree.get_children()) == 2
        # 검색 필터
        dlg.search_var.set("Second")
        assert len(dlg.tree.get_children()) == 1
        dlg.search_var.set("")
        # 편집 반영 + 저장 (백업 생성 포함)
        dlg.trans_entries[0]["text"] = "안녕 세상"
        dlg._dirty = True
        dlg._save()
        saved = trans.read_text(encoding="utf-8")
        assert "안녕 세상" in saved
        assert (tmp_path / "movie.ko.srt.bak").exists()
        dlg._close()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_skill_and_agent_dialogs(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    _no_modal(monkeypatch)
    from app_tk.dialogs2 import AgentExchangeDialogTk, SkillInstallDialogTk

    root = tk.Tk()
    root.withdraw()
    try:
        # 스킬 설치: 프로젝트 범위로 agy 대상 설치 → 결과 텍스트가 채워짐
        skill = SkillInstallDialogTk(root, _StubApp())
        skill.scope_var.set(1)
        skill._on_scope_changed()
        skill.folder_var.set(str(tmp_path))
        skill.cmb_platform.current(skill._target_ids.index("agy"))
        skill._do_install()
        assert skill.result.get("1.0", "end").strip()
        skill._close()

        # 에이전트 교환: 내보내기 → 상태 확인까지
        srt = tmp_path / "ep.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n",
                       encoding="utf-8")
        agent = AgentExchangeDialogTk(root, _StubApp())
        agent.file_var.set(str(srt))
        agent._do_export()
        out = agent.result.get("1.0", "end")
        assert out.strip()
        agent._do_status()
        assert agent.result.get("1.0", "end").strip()
        agent._close()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_subtitle_tools_dialog_empty_folder(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    _no_modal(monkeypatch)
    from app_tk.dialogs2 import SubtitleToolsDialogTk

    root = tk.Tk()
    root.withdraw()
    try:
        dlg = SubtitleToolsDialogTk(root, _StubApp())
        dlg.folder_var.set(str(tmp_path))
        dlg._refresh_preview()  # 빈 폴더: 예외 없이 종료
        dlg._close()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_enable_file_drop_degrades_gracefully():
    tk = pytest.importorskip("tkinter")
    from app_tk.widgets import enable_file_drop

    root = tk.Tk()
    root.withdraw()
    try:
        lb = tk.Listbox(root)
        result = enable_file_drop(lb, lambda paths: None)
        assert result in (True, False)  # tkinterdnd2 유무에 따라 다름, 크래시만 없으면 됨
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# 레트로 아이콘 + 스플래시
# ----------------------------------------------------------------------
def test_tk_icon_assets_valid():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    png = os.path.join(root_dir, "assets", "app_tk.png")
    ico = os.path.join(root_dir, "assets", "app_tk.ico")
    assert os.path.isfile(png) and os.path.getsize(png) > 500
    assert os.path.isfile(ico) and os.path.getsize(ico) > 1000
    with open(png, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"
    with open(ico, "rb") as f:
        assert f.read(4) == b"\x00\x00\x01\x00"  # ICO 매직


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_splash_constructs_and_progresses(tmp_path):
    tk = pytest.importorskip("tkinter")
    from app_tk.splash import SplashScreen
    from app_tk.theme import apply_retro_theme

    root = tk.Tk()
    root.withdraw()
    try:
        apply_retro_theme(root)
        splash = SplashScreen(root)
        splash.set_progress(0.5, "절반 로딩 중...")
        assert splash._fraction == 0.5
        assert splash.status_var.get() == "절반 로딩 중..."
        splash.set_progress(1.0, "완료")
        splash.close()
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_failure_help_toggle_gates_dialog(tmp_path):
    tk = pytest.importorskip("tkinter")
    import app_tk.main_window as mw
    if mw.gst is None:
        pytest.skip("gemini-srt-translator 미설치 환경 (시작 경고 모달 방지)")
    from app_tk.main_window import TranslatorAppTk

    root = tk.Tk()
    root.withdraw()
    try:
        path = str(tmp_path / "tk-fh.json")
        app = TranslatorAppTk(root, settings_path=path)
        # 기본값은 켜짐 (기존 동작 유지)
        assert app.vars["show_failure_help"].get() is True
        assert app._failure_help_enabled() is True

        shown = []
        app._show_failure_dialog = shown.append
        app._failure_help_pending = 3
        app._maybe_show_failure_dialog()
        assert shown == [3]
        assert app._failure_help_pending == 0

        # 끄면 설정에 즉시 저장되고, 안내창은 건너뛴다
        app.vars["show_failure_help"].set(False)
        app._sync_failure_help()
        data = json.loads(open(path, encoding="utf-8").read())
        assert data["show_failure_help"] is False
        app._failure_help_pending = 2
        app._maybe_show_failure_dialog()
        assert shown == [3]  # 추가 호출 없음
        assert app._failure_help_pending == 0

        # 재시작 시 꺼진 상태가 복원된다
        app2 = TranslatorAppTk(root, settings_path=path)
        assert app2.vars["show_failure_help"].get() is False
        assert app2._failure_help_enabled() is False
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_custom_lang_placeholder_shows_guidance(tmp_path):
    tk = pytest.importorskip("tkinter")
    import app_tk.main_window as mw
    if mw.gst is None:
        pytest.skip("gemini-srt-translator 미설치 환경 (시작 경고 모달 방지)")
    from app_tk.main_window import TranslatorAppTk

    root = tk.Tk()
    root.withdraw()
    try:
        app = TranslatorAppTk(root, settings_path=str(tmp_path / "tk-ph.json"))
        label = app._custom_lang_ph
        # Qt판과 같은 안내문구, 값은 오염시키지 않는다
        assert label.cget("text") == app.tr_str("custom_lang_ph")
        assert app.vars["custom_lang"].get() == ""
        root.update_idletasks()
        assert label.place_info()  # 빈 칸이라 안내가 보인다
        # 입력하면 사라지고, 지우면 돌아온다
        app.vars["custom_lang"].set("Vietnamese")
        assert not label.place_info()
        app.vars["custom_lang"].set("")
        root.update_idletasks()
        assert label.place_info()
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# UI 언어 전환 (영어 선택 시 전체 영문화 — Qt판 update_ui_language 패리티)
# ----------------------------------------------------------------------
def _registered(app, key):
    return next(w for w, k, _kw in app._i18n_texts if k == key)


def _make_tk_app(tmp_path, name="tk-lang.json"):
    """언어 전환 테스트용 앱 생성 (기존 창 테스트와 같은 가드 패턴)."""
    tk = pytest.importorskip("tkinter")
    import app_tk.main_window as mw
    if mw.gst is None:
        pytest.skip("gemini-srt-translator 미설치 환경 (시작 경고 모달 방지)")
    from app_tk.main_window import TranslatorAppTk
    root = tk.Tk()
    root.withdraw()
    app = TranslatorAppTk(root, settings_path=str(tmp_path / name))
    return root, app


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_tk_language_switch_retexts_main_window(tmp_path):
    from app.i18n import I18N
    root, app = _make_tk_app(tmp_path)
    try:
        assert app.btn_start.cget("text") == "🚀 작업 시작"
        assert app.api_group.cget("text") == "API 키 설정"
        assert app.advanced_dialog.title() == "고급 설정 및 튜닝 (v3.8.3 기능)"
        assert app.api_keys_dialog.title() == "API 키 관리 (최대 10개)"
        assert _registered(app, "chk_streaming").cget("text") == "스트리밍"
        assert app.api_key_labels[0].cget("text") == "API 키 1:"

        app.vars["app_lang"].set("English")
        app._on_app_lang_changed()
        assert app.btn_start.cget("text") == "🚀 Start Task"
        assert app.btn_stop.cget("text") == "🛑 Stop Task"
        assert app.api_group.cget("text") == "API Key Settings"
        assert app.file_lang_group.cget("text") == \
            I18N["en"]["file_lang_group_title"]
        assert app.advanced_dialog.title() == I18N["en"]["advanced_dialog_title"]
        assert app.api_keys_dialog.title() == I18N["en"]["dialog_api_title"]
        assert _registered(app, "chk_streaming").cget("text") == \
            I18N["en"]["chk_streaming"]
        assert _registered(app, "chk_show_failure_help").cget("text") == \
            I18N["en"]["chk_show_failure_help"]
        assert _registered(app, "btn_fetch").cget("text") == "Fetch Models"
        assert app.btn_advanced.cget("text") == I18N["en"]["btn_advanced"]
        assert app.api_key_labels[0].cget("text") == "API Key 1:"
        assert app.api_key_labels[9].cget("text") == "API Key 10:"
        assert app.vars["audio_label"].get() == I18N["en"]["lbl_audio_file_ph"]

        app.vars["app_lang"].set("한국어")
        app._on_app_lang_changed()
        assert app.btn_start.cget("text") == "🚀 작업 시작"
        assert app.api_group.cget("text") == "API 키 설정"
        assert _registered(app, "chk_streaming").cget("text") == "스트리밍"
    finally:
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="DISPLAY 없음 (xvfb-run 필요)")
def test_tk_dialogs_follow_app_language(tmp_path):
    from app.i18n import I18N
    from app_tk.dialogs2 import SkillInstallDialogTk, SubtitlePreviewDialogTk
    root, app = _make_tk_app(tmp_path, "tk-lang2.json")
    try:
        # 한글 모드 제목부터 (제목 키가 그대로 노출되는 버그 회귀 방지)
        skill_ko = SkillInstallDialogTk(app.root, app)
        try:
            assert skill_ko.dlg.title() == I18N["ko"]["skill_dialog_title"]
        finally:
            skill_ko._close()

        app.vars["app_lang"].set("English")
        app._on_app_lang_changed()

        skill = SkillInstallDialogTk(app.root, app)
        try:
            assert skill.dlg.title() == I18N["en"]["skill_dialog_title"]
            assert "All" in list(skill.cmb_platform.cget("values"))
        finally:
            skill._close()

        srt = tmp_path / "en.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n",
                       encoding="utf-8")
        preview = SubtitlePreviewDialogTk(app.root, app, str(srt))
        try:
            assert preview.dlg.title() == I18N["en"]["preview_title"]
            assert preview.tree.heading("trans", "text") == \
                I18N["en"]["preview_col_trans"]
        finally:
            preview._request_close()
    finally:
        root.destroy()
