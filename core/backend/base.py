# -*- coding: utf-8 -*-
"""번역 백엔드 추상화 (Phase b).

GUI/워커가 gemini-srt-translator 내부 클래스에 직접 의존하지 않고
이 인터페이스를 통해서만 통신한다. Phase (c)에서 workers.py가 이
인터페이스를 사용하도록 마이그레이션된다.
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, Optional


class TranslationError(Exception):
    """백엔드 번역/전사 실패를 나타내는 GUI 표준 예외.

    라이브러리 내부 예외를 그대로 노출하지 않고 이 타입으로 정규화한다.
    원본 예외는 __cause__로 보존된다.
    """


# 취소 토큰: 호출 시 True를 반환하면 작업 중단 요청
CancelToken = Callable[[], bool]


class TranslationBackend(ABC):
    """GUI와 업스트림 번역 엔진 사이의 표준 계약."""

    @abstractmethod
    def run(
        self,
        params: Dict,
        mode: str = "translate",
        cancel_token: Optional[CancelToken] = None,
    ) -> bool:
        """번역/전사를 실행한다.

        Args:
            params: 번역기 생성 파라미터 dict (None 값 포함 가능).
            mode: "translate" 또는 "transcribe".
            cancel_token: 호출 시 True면 중단 요청. (Phase d에서 청크 루프에 주입 예정.
                Phase b에서는 인터페이스만 정의하고 아직 사용하지 않음.)

        Returns:
            True (성공 시).

        Raises:
            TranslationError: 백엔드 실행 실패 시.
            ValueError: mode가 translate/transcribe가 아닐 때.
        """
        ...

    @property
    @abstractmethod
    def backend_version(self) -> Optional[str]:
        """백엔드 라이브러리 버전 문자열 (감지 실패 시 None)."""
        ...
