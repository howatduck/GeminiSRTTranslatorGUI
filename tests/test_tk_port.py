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
