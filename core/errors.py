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


# --- 실패 후 안내: 원인 추정 + 해결 가능성 있는 다음 행동 제시 ---

_FAILURE_KINDS = (
    # (종류, 원인 라벨, 판정 키워드들)
    ("overload", "모델 서버 과부하",
     ("과부하", "overloaded", "503", "unavailable")),
    ("quota", "API 할당량 고갈",
     ("할당량", "429", "quota")),
    ("auth", "API 키 인증 오류",
     ("권한 없음", "인증 오류", "403")),
    ("timeout", "서버 응답 시간 초과",
     ("시간 초과", "deadline", "504")),
    ("safety", "AI 안전 설정 차단",
     ("안전 설정 차단", "blocked")),
    ("response", "API 응답 처리 오류",
     ("schema", "스트림 응답 오류", "내부 오류")),
)

_FAILURE_ADVICE = {
    "overload": [
        "잠시 후 다시 시도해 보세요. 서버 과부하는 보통 일시적입니다.",
        "모델을 바꾸면 도움이 됩니다 (예: flash-lite → flash).",
        "배치 크기를 줄이면 실패해도 그 구간만 다시 시도합니다.",
    ],
    "quota": [
        "API 키를 추가하면 자동으로 번갈아 사용합니다.",
        "할당량이 복구되는 시간(보통 자정 전후) 뒤에 다시 시도해 보세요.",
    ],
    "auth": [
        "API 키가 올바른지, 해당 모델을 쓸 권한이 있는지 확인해 보세요.",
        "키를 다시 저장한 뒤 다시 시도해 보세요.",
    ],
    "timeout": [
        "잠시 후 다시 시도해 보세요.",
        "배치 크기를 줄이면 한 번에 처리하는 양이 줄어 시간 초과가 덜 생깁니다.",
    ],
    "safety": [
        "해당 구간의 내용이 안전 필터에 걸린 것으로 보입니다.",
        "다른 모델로 시도하면 통과하는 경우가 있습니다.",
    ],
    "response": [
        "다시 시도해 보세요. 반복되면 모델 변경이 도움이 됩니다.",
        "같은 파일에서 반복되면 배치 크기를 줄여 보세요.",
    ],
    "unknown": [
        "다시 시도해 보세요. 완료된 작업은 자동으로 건너뜁니다.",
        "반복되면 모델을 바꾸거나 배치 크기를 줄여 보세요.",
    ],
}


def failure_kind(message):
    """실패 메시지 1건 → 종류 키 (overload/quota/auth/timeout/safety/response/unknown)."""
    text = str(message or "").lower()
    for name, _label, keywords in _FAILURE_KINDS:
        if any(k in text for k in keywords):
            return name
    return "unknown"


def failure_kind_label(kind):
    for name, label, _keywords in _FAILURE_KINDS:
        if name == kind:
            return label
    return "일시적 오류"


# 이 종류의 실패는 배치 축소가 아니라 모델 전환이 답이다 —
# 워커 폴백이 같은 모델의 남은 프로필을 건너뛸 때 쓴다.
MODEL_SWITCH_KINDS = frozenset({"overload", "quota", "safety"})


def failure_advice(messages):
    """실패 메시지 목록 → (원인 라벨, 안내 문구 목록).

    classify_worker_error가 만든 사용자용 문구를 키워드로 되짚어 대표
    원인을 추정한다. 가장 잦은 종류를 고르고, 동률이면 마지막 실패를
    우선한다. 순수 함수.
    """
    counts = {}
    last_seen = {}
    for idx, msg in enumerate(messages or []):
        kind = failure_kind(msg)
        counts[kind] = counts.get(kind, 0) + 1
        last_seen[kind] = idx
    if not counts:
        kind = "unknown"
    else:
        kind = max(counts, key=lambda k: (counts[k], last_seen[k]))
    return failure_kind_label(kind), list(_FAILURE_ADVICE[kind])
