# -*- coding: utf-8 -*-
"""gemini-srt-translator용 TranslationBackend 구현 (Phase b).

workers.py에 있던 라이브러리 직접 호출 로직을 이 어댑터로 격리한다.
Phase (b)에서는 인터페이스와 구현을 도입하고, Phase (c)에서 workers.py가
이 어댑터를 사용하도록 마이그레이션한다.

주의: 몽키패치는 core/gst_patches.py 레지스트리에 의해 임포트 시점에
전역 적용된다 (Phase a). 어댑터는 이미 패치된 클래스를 사용한다.
컨텍스트 매니저 범위의 패치 격리는 향후 과제.
"""

from typing import Dict, Optional

from core.backend.base import CancelToken, TranslationBackend, TranslationError
from core.gst_compat import (
    GeminiSRTTranslator,
    _get_gst_params,
    genai,
    gst,
    reset_library_logger,
)
from core.gst_patches import get_library_version, set_active_cancel_token


class GstAdapter(TranslationBackend):
    """gemini-srt-translator 라이브러리 어댑터."""

    def __init__(self):
        self._version = get_library_version()

    @property
    def backend_version(self) -> Optional[str]:
        return self._version

    @property
    def available(self) -> bool:
        """라이브러리를 사용할 수 있는지 (임포트 성공 여부)."""
        return gst is not None

    def _filter_params(self, params: Dict) -> Dict:
        """None 값 제거 + 실제 __init__ 시그니처에 있는 파라미터만 통과."""
        filtered = {k: v for k, v in params.items() if v is not None}
        if GeminiSRTTranslator is not None:
            allowed = _get_gst_params()
            filtered = {k: v for k, v in filtered.items() if k in allowed}
        return filtered

    def run(
        self,
        params: Dict,
        mode: str = "translate",
        cancel_token: Optional[CancelToken] = None,
    ) -> bool:
        if mode not in ("translate", "transcribe"):
            raise ValueError(f"mode는 'translate' 또는 'transcribe'여야 합니다: {mode}")
        if not self.available:
            raise TranslationError("gemini-srt-translator 라이브러리를 사용할 수 없습니다.")

        # 라이브러리 전역 진행 상태 초기화 (기존 workers.py에서 작업 직전 호출)
        reset_library_logger()

        filtered = self._filter_params(params)

        # 취소 토큰을 현재 스레드에 등록 — _process_batch 청크 가드에서 확인됨.
        # 반드시 해제해야 다음 작업에 잔류하지 않음.
        set_active_cancel_token(cancel_token)
        try:
            if GeminiSRTTranslator is not None:
                instance = GeminiSRTTranslator(**filtered)
                if mode == "transcribe":
                    instance.transcribe()
                else:
                    instance.translate()
            else:
                # 구버전 모듈 방식 fallback (기존 workers.py 로직과 동일)
                for key, value in filtered.items():
                    setattr(gst, key, value)
                if mode == "transcribe":
                    gst.transcribe()
                else:
                    gst.translate()
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"번역 백엔드 실행 실패 ({mode}): {e}") from e
        finally:
            set_active_cancel_token(None)
        return True
