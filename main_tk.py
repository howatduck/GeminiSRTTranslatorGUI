# -*- coding: utf-8 -*-
"""Tkinter 진입점 — 레트로 스플래시를 띄운 뒤 단계적으로 로딩한다.

드래그&드롭 루트(tkinterdnd2) 우선, 없으면 일반 Tk로 폴백한다.
"""

import sys

# 프로세스 안전 패치 및 FFmpeg 경로 등록: 가장 먼저 적용 (PyQt판과 동일)
import core.safety  # noqa: F401


def _enable_dpi_awareness():
    """윈도우에서 Tkinter가 흐려 보이지 않도록 DPI 인식을 켠다."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _make_root():
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk()
    except Exception:
        import tkinter as tk
        return tk.Tk()


def main():
    _enable_dpi_awareness()
    from app_tk.theme import apply_retro_theme

    root = _make_root()
    apply_retro_theme(root)
    root.withdraw()

    # 스플래시를 먼저 띄우고, 무거운 임포트를 단계별로 진행한다
    from app_tk.splash import SplashScreen
    splash = SplashScreen(root)
    splash.set_progress(0.10, "핵심 모듈을 불러오는 중...")
    root.update()

    # gemini-srt-translator 임포트 + GUI 안전 몽키패치 적용
    import core.gst_compat  # noqa: F401
    splash.set_progress(0.45, "번역 라이브러리를 불러오는 중...")
    root.update()

    from app_tk.main_window import TranslatorAppTk
    splash.set_progress(0.65, "메인 창을 구성하는 중...")
    root.update()

    app = TranslatorAppTk(root)
    splash.set_progress(0.90, "설정을 불러오는 중...")
    root.update()

    splash.set_progress(1.0, "완료")
    root.update()
    splash.close()
    root.deiconify()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
