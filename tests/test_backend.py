# -*- coding: utf-8 -*-
"""core.backend 테스트 — TranslationBackend 인터페이스 + GstAdapter.

실제 gemini-srt-translator 없이 동작하도록 gst_compat 모듈을 목업으로 교체한다.
"""

import sys
import types

import pytest


def _install_mock_gst_compat(monkeypatch, translator_cls=None, gst_module=True):
    """core.gst_compat 목업을 sys.modules에 주입."""
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

    # gst_patches 목업 (get_library_version)
    patches = types.ModuleType("core.gst_patches")
    patches.get_library_version = lambda: "3.8.3"
    monkeypatch.setitem(sys.modules, "core.gst_patches", patches)

    # core.backend.* 모듈 캐시 제거 (목업으로 재임포트되도록)
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
    assert adapter.backend_version == "3.8.3"
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
