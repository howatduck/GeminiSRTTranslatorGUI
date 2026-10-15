# -*- coding: utf-8 -*-
"""core.errors 테스트: 워커 예외 분류."""

import pytest

from core.errors import classify_worker_error
from core.safety import WorkerLibraryExit


def _msg(exc, key="키 1/3", name="video.srt"):
    return classify_worker_error(exc, msg_key=key, base_name=name)


def test_context_included():
    msg = _msg(RuntimeError("boom"))
    assert "키 1/3" in msg
    assert "video.srt" in msg


def test_overload_exit():
    msg = _msg(WorkerLibraryExit(1))
    assert "과부하" in msg


def test_safety_blocked():
    msg = _msg(RuntimeError("response blocked by safety settings"))
    assert "안전 설정 차단" in msg


def test_stop_candidate():
    class StopCandidateIteration(Exception):
        pass

    msg = _msg(StopCandidateIteration("no candidates"))
    assert "응답 생성 중단" in msg


def test_stream_chunk_error():
    msg = _msg(AttributeError("'NoneType' object has no attribute 'content'"))
    assert "스트림 응답 오류" in msg
    assert "AttributeError" in msg


def test_library_internal_error():
    msg = _msg(KeyError("missing_key"))
    assert "라이브러리 내부 오류" in msg


def test_schema_error():
    msg = _msg(ValueError("invalid text content in response"))
    assert "Schema" in msg


def test_deadline_timeout():
    msg = _msg(TimeoutError("deadline exceeded"))
    assert "시간 초과" in msg


def test_quota_429():
    msg = _msg(RuntimeError("429 quota exceeded for model"))
    assert "할당량" in msg
    assert "429" in msg


def test_permission_403():
    msg = _msg(RuntimeError("403 permission denied"))
    assert "권한 없음" in msg


def test_fallback():
    msg = _msg(OSError("some weird os failure"))
    assert "라이브러리 예외" in msg
    assert "some weird os failure" in msg


def test_translation_error_unwrapped():
    """TranslationError로 감싸져도 원본 타입 기준으로 분류된다."""
    import sys
    sys.path.insert(0, '.')
    from core.backend.base import TranslationError
    orig = AttributeError("'NoneType' object has no attribute 'content'")
    wrapped = TranslationError("번역 백엔드 실행 실패 (translate): ...")
    wrapped.__cause__ = orig
    msg = _msg(wrapped)
    assert "스트림 응답 오류" in msg
    assert "AttributeError" in msg


def test_translation_error_without_cause():
    """cause가 없으면 TranslationError 자체로 분류 (fallback)."""
    import sys
    sys.path.insert(0, '.')
    from core.backend.base import TranslationError
    msg = _msg(TranslationError("something failed"))
    assert "라이브러리 예외" in msg
