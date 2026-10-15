# -*- coding: utf-8 -*-
"""워커 오류 분류: 작업 예외를 사용자용 메시지로 변환하는 순수 함수."""

from core.safety import WorkerLibraryExit


def _unwrap(exc: BaseException) -> BaseException:
    """TranslationError로 감싸진 경우 원본 예외를 반환 (분류 정확도 보존).

    core.backend.GstAdapter는 모든 백엔드 예외를 TranslationError로 정규화한다.
    타입 기반 분류가 동작하도록 __cause__ 체인을 따라 원본을 찾는다.
    순환 참조 방지를 위해 방문 집합을 사용한다.
    """
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ == "TranslationError" and cur.__cause__ is not None:
            cur = cur.__cause__
        else:
            break
    return cur


def classify_worker_error(exc: BaseException, *, msg_key: str, base_name: str) -> str:
    """번역/전사 작업 중 발생한 예외를 사용자용 한국어 메시지로 분류한다.

    순수 함수이므로 I/O나 스레드 상태에 의존하지 않아 단위 테스트가 가능하다.
    분류 규칙은 기존 TranslationWorker의 인라인 체인과 동일하다.
    """
    exc = _unwrap(exc)
    err_str = str(exc).lower()
    err_type = type(exc).__name__.lower()
    err_base = f"작업 실패 ({msg_key}): '{base_name}'"

    if isinstance(exc, WorkerLibraryExit):
        return f"{err_base} - AI 모델 과부하(Overloaded 3회) 또는 라이브러리 종료 요청으로 중단됨."
    if "blocked" in err_type or "blocked" in err_str:
        return f"{err_base} - AI 안전 설정 차단."
    if "stop" in err_type and "candidate" in err_type:
        return f"{err_base} - AI 응답 생성 중단."
    if err_type in ("attributeerror", "typeerror", "indexerror") and (
        "content" in err_str or "candidates" in err_str or "parts" in err_str
    ):
        # 라이브러리 내부 스트림 청크 None 접근 오류 (google-genai SDK 호환성 문제)
        return f"{err_base} - API 스트림 응답 오류 ({type(exc).__name__}: {exc})"
    if err_type in ("attributeerror", "typeerror", "indexerror", "keyerror"):
        # 기타 Python 런타임 오류 - 실제 내용을 표시
        return f"{err_base} - 라이브러리 내부 오류 ({type(exc).__name__}: {exc})"
    if "content" in err_str or "text" in err_str:
        # ValueError 등 라이브러리의 Schema/응답 검증 실패
        return f"{err_base} - API 응답 데이터(Schema) 오류 ({exc})"
    if "deadline" in err_str or "504" in err_str:
        return f"{err_base} - 서버 응답 시간 초과."
    if "quota" in err_str or "429" in err_str:
        return f"{err_base} - API 할당량 고갈 (429)."
    if "permission" in err_str or "403" in err_str:
        return f"{err_base} - 권한 없음 (API 인증 오류)."
    return f"{err_base} - 라이브러리 예외: {exc}"
