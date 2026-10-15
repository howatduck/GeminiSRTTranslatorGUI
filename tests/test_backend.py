# -*- coding: utf-8 -*-
"""core.backend 테스트 — TranslationBackend 인터페이스 + GstAdapter.

실제 gemini-srt-translator 없이 동작하도록 gst_compat 모듈을 목업으로 교체한다.
"""

import sys
import types

import pytest


def _install_mock_gst_compat(monkeypatch, translator_cls=None, gst_module=True):
    """core.gst_compat 목업을 sys.modules에 주입.

    core.gst_patches와 core.backend는 실제 모듈을 사용한다 (라이브러리 없이도
    임포트 가능). gst_compat만 목업한다.
    """
    mod = types.ModuleType("core.gst_compat")
    mod.GST_IMPORT_ERROR = None
    mod.GENAI_IMPORT_ERROR = None
    mod.GeminiSRTTranslator = translator_cls
    mod.Subtitle = None
    mod.SubtitleSession = None
    mod.genai = None
    mod.gst = types.ModuleType("gst") if gst_module else None
    if translator_cls is not None:
        import inspect as _inspect
        params = set(_inspect.signature(translator_cls.__init__).parameters.keys())
        params.discard("self")
        mod._get_gst_params = lambda: params
    else:
        mod._get_gst_params = lambda: set()
    mod.reset_library_logger = lambda: None
    monkeypatch.setitem(sys.modules, "core.gst_compat", mod)

    # core.backend.* 모듈 캐시 제거 (목업 gst_compat으로 재임포트되도록)
    # 주의: core.gst_patches는 삭제하지 말 것 — _cancel_state thread-local이
    # 모듈 인스턴스별로 분리되면 토큰 레지스트리가 깨진다.
    for name in [n for n in sys.modules if n.startswith("core.backend")]:
        del sys.modules[name]


class _FakeTranslator:
    def __init__(self, input_file=None, output_file=None):
        self.kwargs = {"input_file": input_file, "output_file": output_file}
        self.ran = None

    def translate(self):
        self.ran = "translate"

    def transcribe(self):
        self.ran = "transcribe"


def test_adapter_run_translate(monkeypatch):
    _install_mock_gst_compat(monkeypatch, _FakeTranslator)
    from core.backend import GstAdapter, TranslationBackend
    adapter = GstAdapter()
    assert isinstance(adapter, TranslationBackend)
    assert adapter.available is True
    # 실제 gst_patches 사용: 라이브러리 미설치 시 None
    assert adapter.backend_version is None or isinstance(adapter.backend_version, str)
    assert adapter.run({"input_file": "a.srt", "empty": None}, mode="translate") is True


def test_adapter_run_transcribe(monkeypatch):
    _install_mock_gst_compat(monkeypatch, _FakeTranslator)
    from core.backend import GstAdapter
    adapter = GstAdapter()
    assert adapter.run({"input_file": "a.mp4"}, mode="transcribe") is True


def test_adapter_filters_unknown_params(monkeypatch):
    _install_mock_gst_compat(monkeypatch, _FakeTranslator)
    from core.backend import GstAdapter
    adapter = GstAdapter()
    filtered = adapter._filter_params({"input_file": "a.srt", "bogus_param": 1, "none_val": None})
    assert "bogus_param" not in filtered
    assert "none_val" not in filtered
    assert filtered["input_file"] == "a.srt"


def test_adapter_invalid_mode(monkeypatch):
    _install_mock_gst_compat(monkeypatch, _FakeTranslator)
    from core.backend import GstAdapter
    with pytest.raises(ValueError, match="translate"):
        GstAdapter().run({}, mode="bogus")


def test_adapter_unavailable(monkeypatch):
    _install_mock_gst_compat(monkeypatch, None, gst_module=False)
    from core.backend import GstAdapter, TranslationError
    adapter = GstAdapter()
    assert adapter.available is False
    with pytest.raises(TranslationError):
        adapter.run({}, mode="translate")


def test_adapter_wraps_exception(monkeypatch):
    class _Boom:
        def __init__(self, **kwargs):
            pass

        def translate(self):
            raise RuntimeError("api exploded")

    _install_mock_gst_compat(monkeypatch, _Boom)
    from core.backend import GstAdapter, TranslationError
    with pytest.raises(TranslationError, match="api exploded") as exc_info:
        GstAdapter().run({}, mode="translate")
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_backend_is_abstract():
    from core.backend import TranslationBackend
    with pytest.raises(TypeError):
        TranslationBackend()


def test_adapter_registers_and_clears_token(monkeypatch):
    """run() 동안 토큰 등록, 종료 후 해제."""
    from core.gst_patches import _get_active_cancel_token

    seen = []

    class _CheckingTranslator(_FakeTranslator):
        def translate(self):
            seen.append(_get_active_cancel_token())
            self.ran = "translate"

    _install_mock_gst_compat(monkeypatch, _CheckingTranslator)
    from core.backend import GstAdapter

    token = lambda: False
    GstAdapter().run({"input_file": "a.srt"}, mode="translate", cancel_token=token)
    assert seen == [token]  # 실행 중에는 토큰 등록됨
    assert _get_active_cancel_token() is None  # 종료 후 해제됨


def test_adapter_propagates_cancel(monkeypatch):
    """취소 시 BackendCancelRequested가 그대로 전파 (TranslationError로 감싸지 않음)."""
    from core.gst_patches import _make_chunk_guard
    from core.backend.base import BackendCancelRequested

    def _orig(self):
        raise BackendCancelRequested()

    guarded = _make_chunk_guard(_orig)

    class _CancelTranslator:
        def __init__(self, input_file=None):
            pass

        def translate(self):
            guarded(self)

    _install_mock_gst_compat(monkeypatch, _CancelTranslator)
    from core.backend import GstAdapter

    with pytest.raises(BackendCancelRequested):
        GstAdapter().run({"input_file": "a.srt"}, mode="translate",
                         cancel_token=lambda: False)
