# -*- coding: utf-8 -*-
"""core.gst_patches 테스트 — 버전별 패치셋 레지스트리.

실제 gemini-srt-translator 없이도 동작하도록 가짜 클래스로 검증한다.
"""

import pytest

from core.gst_patches import (
    PATCH_REGISTRY,
    SUPPORTED_VERSIONS,
    apply_patches,
    get_library_version,
    resolve_patch_set,
)


def _make_fake_translator():
    class _T:
        _save_subtitle_file = None
        _process_translated_lines = lambda self: None
        _parse_response = lambda self: None
        _process_batch = lambda self: "orig"
        _reduce_batch_size = lambda self: "orig-reduce"
        _reduce_transcribe_chunk_size = lambda self: "orig-reduce-t"
    return _T


def _make_fake_session():
    class _S:
        _process_batch = lambda self: "orig-session"
    return _S


def test_supported_versions():
    assert "3.8.3" in SUPPORTED_VERSIONS
    assert len(SUPPORTED_VERSIONS) >= 1


def test_resolve_patch_set_known():
    ps = resolve_patch_set("3.8.3")
    assert "patch_save_subtitle_file" in ps
    assert "patch_noop_reduce" in ps
    assert len(ps) == 7


def test_resolve_patch_set_unknown_falls_back(capsys):
    ps = resolve_patch_set("9.9.9")
    assert ps == PATCH_REGISTRY[SUPPORTED_VERSIONS[-1]]
    assert "검증되지 않은 버전" in capsys.readouterr().out


def test_apply_patches_registers_all():
    t = _make_fake_translator()
    s = _make_fake_session()
    ver = apply_patches(t, None, s, version="3.8.3")
    assert ver == "3.8.3"
    # _save_subtitle_file: 패치 함수로 교체됨
    assert t._save_subtitle_file is not None
    assert t._save_subtitle_file.__name__ == "_patched_save_subtitle_file"
    assert isinstance(s.__dict__["_save_subtitle_file"], staticmethod)
    # _process_batch: 가드로 래핑됨 (원본 호출 확인)
    assert t()._process_batch() == "orig"
    assert s()._process_batch() == "orig-session"
    # noop reduce
    assert t()._reduce_batch_size() is None
    assert t()._reduce_transcribe_chunk_size() is None


def test_chunk_guard_converts_error():
    class T(_make_fake_translator()):
        pass

    def _boom(self):
        raise AttributeError("'NoneType' object has no attribute 'content'")

    T._process_batch = _boom
    apply_patches(T, None, _make_fake_session(), version="3.8.3")
    with pytest.raises(RuntimeError, match="빈 응답 청크"):
        T()._process_batch()


def test_chunk_guard_reraises_unrelated():
    class T(_make_fake_translator()):
        pass

    def _boom(self):
        raise ValueError("something else")

    T._process_batch = _boom
    apply_patches(T, None, _make_fake_session(), version="3.8.3")
    with pytest.raises(ValueError, match="something else"):
        T()._process_batch()


def test_get_library_version_returns_str_or_none():
    v = get_library_version()
    assert v is None or isinstance(v, str)
