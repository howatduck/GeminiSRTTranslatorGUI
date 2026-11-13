# -*- coding: utf-8 -*-
"""
Gemini SRT Translator GUI — Tkinter판 진입점.

PyQt판(main.py)과 공존하며, 실행하면 이쪽이 뜬다:
    python main_tk.py

설정은 app_tk.settings.JsonSettings(JSON 파일)에 저장되며, 첫 실행 시
기존 PyQt판(QSettings) 설정을 자동으로 읽어와 이전한다.
"""

import os
import sys

# 프로세스 안전 패치 및 FFmpeg 경로 등록: 가장 먼저 적용 (PyQt판과 동일)
import core.safety  # noqa: F401

# gemini-srt-translator 임포트 + GUI 안전 몽키패치 적용
import core.gst_compat  # noqa: F401


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


def main():
    _enable_dpi_awareness()
    import tkinter as tk

    from app_tk.main_window import TranslatorAppTk

    root = tk.Tk()
    root.geometry("1000x700")
    # 테마: 가능하면 clam (플랫폼 기본보다 일관된 모양)
    try:
        from tkinter import ttk
        ttk.Style(root).theme_use("clam")
    except Exception:
        pass
    app = TranslatorAppTk(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
