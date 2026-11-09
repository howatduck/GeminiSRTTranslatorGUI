# -*- coding: utf-8 -*-
"""모델 폴백 체인·배치 래더·자막 서명 테스트.

- core.fallback: 배치 래더와 (모델, 배치) 시도 계획
- core.errors.failure_kind: 실패 종류 판정
- core.subtitle_io: 서명 렌더링·큐 삽입 + 저장 패치 통합
- app.workers: 과부하 시 모델 전환, 시간초과 시 배치 축소가 실제로
  다음 시도로 이어지는지 가짜 백엔드로 검증
"""

import os
import queue
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from core.errors import failure_kind, MODEL_SWITCH_KINDS
from core.fallback import batch_ladder, build_attempt_plan
import core.subtitle_io as sio


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# --- 배치 래더 / 시도 계획 ---

def test_batch_ladder_steps_down_to_floor():
    assert batch_ladder(1000, 200, 100) == [1000, 800, 600, 400, 200, 100]
    assert batch_ladder(100, 30, 10) == [100, 70, 40, 10]


def test_batch_ladder_disabled_cases():
    assert batch_ladder(1000, 0, 100) == [1000]
    assert batch_ladder(1000, 200, 0) == [1000]
    assert batch_ladder(1000, 200, 1000) == [1000]


def test_attempt_plan_is_level_major():
    plan = build_attempt_plan(["A", "B"], 1000, 500, 500)
    assert plan == [("A", 1000), ("B", 1000), ("A", 500), ("B", 500)]


def test_attempt_plan_dedups_and_defaults():
    assert build_attempt_plan(["A", "A", "B"], 100, 0, 0) == [("A", 100), ("B", 100)]
    assert build_attempt_plan([], 100, 0, 0) == [(None, 100)]


# --- 실패 종류 ---

def test_failure_kind_classification():
    assert failure_kind("작업 실패 - AI 모델 과부하(Overloaded 3회)") == "overload"
    assert failure_kind("작업 실패 - API 할당량 고갈 (429).") == "quota"
    assert failure_kind("작업 실패 - 서버 응답 시간 초과.") == "timeout"
    assert failure_kind("아무 관련 없는 오류") == "unknown"
    assert "overload" in MODEL_SWITCH_KINDS
    assert "timeout" not in MODEL_SWITCH_KINDS


# --- 서명 ---

@pytest.fixture()
def signature_on():
    sio.set_signature_config(True, "start", "번역: 홍길동 · {model} · {date}")
    sio.set_signature_model("gemini-3.5-flash")
    yield
    sio.set_signature_config(False, "start", "")
    sio.set_signature_model("")


def test_render_signature(signature_on):
    assert sio.render_signature(today="2026-11-10") == (
        "번역: 홍길동 · gemini-3.5-flash · 2026-11-10")


def test_render_signature_disabled():
    sio.set_signature_config(False, "start", "번역: {model}")
    assert sio.render_signature(today="2026-11-10") == ""


def test_default_signature_template_renders():
    sio.set_signature_config(True, "start", sio.DEFAULT_SIGNATURE_TEMPLATE)
    sio.set_signature_model("gemini-3.5-flash")
    try:
        assert sio.render_signature(today="2026-11-10") == (
            "번역 : GeminiSRTTranslator GUI · gemini-3.5-flash · 2026-11-10")
    finally:
        sio.set_signature_config(False, "start", "")
        sio.set_signature_model("")


def test_fill_default_signature(qapp):
    from PyQt6.QtWidgets import QLineEdit
    import app.main_window as mw

    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    win.txt_signature = QLineEdit()
    win._fill_default_signature()
    assert win.txt_signature.text() == sio.DEFAULT_SIGNATURE_TEMPLATE
    # 이미 내용이 있으면 건드리지 않는다
    win.txt_signature.setText("번역: 홍길동")
    win._fill_default_signature()
    assert win.txt_signature.text() == "번역: 홍길동"


_CUES = [
    "1\n00:00:05,000 --> 00:00:07,000\n안녕\n",
    "2\n00:00:08,000 --> 00:00:09,500\n세상\n",
]


def test_insert_signature_at_start():
    out = sio.insert_signature_cues(list(_CUES), "서명", "start")
    assert len(out) == 3
    assert out[0].startswith("1\n00:00:00,000 --> 00:00:03,000\n서명")
    assert out[1].startswith("2\n00:00:05,000")
    assert out[2].startswith("3\n00:00:08,000")


def test_insert_signature_at_end():
    out = sio.insert_signature_cues(list(_CUES), "서명", "end")
    assert len(out) == 3
    assert out[2].startswith("3\n00:00:09,500 --> 00:00:12,500\n서명")


def test_save_patch_writes_signature(tmp_path, signature_on):
    from core.gst_patches import _patched_save_subtitle_file

    class Sub:
        def __init__(self, start_ms, end_ms, content):
            self.start = timedelta(milliseconds=start_ms)
            self.end = timedelta(milliseconds=end_ms)
            self.content = content

    out = tmp_path / "movie.ko.srt"
    _patched_save_subtitle_file(
        "in.srt",
        [Sub(5000, 7000, "안녕"), Sub(8000, 9500, "세상")],
        str(out),
    )
    text = out.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    assert "번역: 홍길동 · gemini-3.5-flash" in blocks[0]
    assert blocks[0].split("\n")[1].startswith("00:00:00,000 --> 00:00:03,000")
    assert blocks[1].startswith("2\n00:00:05,000")


# --- 워커 폴백 실동작 ---

class _FakeBackend:
    def __init__(self, behavior):
        self.behavior = behavior
        self.seen = []

    def run(self, args, mode=None, cancel_token=None):
        self.seen.append((args["model_name"], args["batch_size"]))
        self.behavior(args)


def _run_worker(qapp, monkeypatch, behavior, base_config):
    import app.workers as workers

    backend = _FakeBackend(behavior)
    monkeypatch.setattr(workers, "GstAdapter", lambda: backend)
    jobs = queue.Queue()
    jobs.put(("in.srt", "Korean", "out.ko.srt", False, None, None))
    worker = workers.TranslationWorker(["key1"], jobs, base_config)
    results = {"ok": [], "err": []}
    worker.job_translated.connect(lambda p, lang: results["ok"].append(p))
    worker.job_error.connect(lambda m: results["err"].append(m))
    worker.run()
    return backend, results


def test_worker_switches_model_on_overload(qapp, monkeypatch):
    def behavior(args):
        if args["model_name"] == "m-lite":
            raise RuntimeError("503 UNAVAILABLE: high demand")

    backend, results = _run_worker(qapp, monkeypatch, behavior, {
        "model_chain": ["m-lite", "m-flash"], "batch_size": 100})
    assert results["ok"] == ["out.ko.srt"]
    assert results["err"] == []
    assert backend.seen == [("m-lite", 100), ("m-flash", 100)]


def test_worker_shrinks_batch_on_timeout(qapp, monkeypatch):
    def behavior(args):
        if args["batch_size"] >= 1000:
            raise RuntimeError("504 deadline exceeded")

    backend, results = _run_worker(qapp, monkeypatch, behavior, {
        "model_chain": ["m1"], "batch_size": 1000,
        "batch_step_down": 500, "batch_floor": 100})
    assert results["ok"] == ["out.ko.srt"]
    assert backend.seen == [("m1", 1000), ("m1", 500)]


def test_worker_gives_up_after_plan_exhausted(qapp, monkeypatch):
    def behavior(args):
        raise RuntimeError("503 UNAVAILABLE")

    backend, results = _run_worker(qapp, monkeypatch, behavior, {
        "model_chain": ["m1", "m2"], "batch_size": 100})
    assert results["ok"] == []
    assert len(results["err"]) == 1
    assert backend.seen == [("m1", 100), ("m2", 100)]


# --- 폴백 체인 구성 (on/off + 모델별 제외) ---

class _CheckBox:
    def __init__(self, value):
        self._value = value

    def isChecked(self):
        return self._value


def _chain_window(qapp, enabled=True, order=(), disabled=()):
    import app.main_window as mw

    win = mw.TranslatorApp.__new__(mw.TranslatorApp)
    win.chk_model_fallback = _CheckBox(enabled)
    win.model_fallback_order = list(order)
    win.model_fallback_disabled = list(disabled)
    return win


def test_model_chain_includes_order(qapp):
    win = _chain_window(qapp, order=["m2", "m3", "m2"])
    assert win._model_chain("m1") == ["m1", "m2", "m3"]


def test_model_chain_off_uses_primary_only(qapp):
    win = _chain_window(qapp, enabled=False, order=["m2", "m3"])
    assert win._model_chain("m1") == ["m1"]


def test_model_chain_skips_disabled_but_keeps_primary(qapp):
    win = _chain_window(qapp, order=["m2", "m3"], disabled=["m2", "m1"])
    assert win._model_chain("m1") == ["m1", "m3"]


# --- 텍스트 모델 판정 + 가져오기 필터 ---

def test_is_text_model():
    from core.config import is_text_model

    assert is_text_model("gemini-3.5-flash-lite")
    assert is_text_model("gemini-2.5-flash")
    assert is_text_model("gemma-3-27b-it")
    assert is_text_model("models/gemini-2.5-pro")
    for junk in (
        "gemini-embedding-001", "embedding-001", "imagen-4.0-generate-001",
        "veo-3.0-generate-001", "gemini-2.5-flash-preview-tts",
        "gemini-2.5-flash-image", "gemini-2.5-flash-native-audio-preview",
        "gemini-live-2.5-flash-preview", "gemini-robotics-er-1.5-preview",
        "gemini-2.5-computer-use-preview-10-2025",
        "deep-research-pro-preview-12-2025", "aqa", "",
    ):
        assert not is_text_model(junk), junk


def test_model_chain_filters_non_text_models(qapp):
    win = _chain_window(
        qapp, order=["gemini-embedding-001", "gemini-2.5-flash"])
    assert win._model_chain("gemini-3.5-flash-lite") == [
        "gemini-3.5-flash-lite", "gemini-2.5-flash"]


def test_model_fetcher_excludes_non_text_models(qapp, monkeypatch):
    import types as _types
    import app.workers as workers

    class _M:
        def __init__(self, name, methods):
            self.name = name
            self.supported_generation_methods = methods

    class _Models:
        def list(self):
            return [
                _M("models/gemini-2.5-flash", ["generateContent"]),
                _M("models/gemini-embedding-001", ["embedContent"]),
                _M("models/gemini-2.5-flash-image", ["generateContent"]),
                _M("models/gemini-2.5-flash-preview-tts", ["generateContent"]),
                _M("models/gemini-2.0-flash", []),
            ]

    fake_client = _types.SimpleNamespace(models=_Models())
    fake_genai = _types.SimpleNamespace(Client=lambda api_key: fake_client)
    monkeypatch.setattr(workers, "genai", fake_genai)
    thread = workers.ModelFetcherThread("key")
    got = []
    thread.models_fetched.connect(got.append)
    thread.run()
    assert got == [["gemini-2.0-flash", "gemini-2.5-flash"]]
