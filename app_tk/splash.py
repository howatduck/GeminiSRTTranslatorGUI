# -*- coding: utf-8 -*-
"""Tkinter판 레트로 로딩(스플래시) 화면.

무거운 라이브러리 임포트와 메인 창 구성이 끝나기 전에 먼저 띄워
대기 시간을 보여준다. 실버 프레임 + 네이비 스트립 + 구간형
(segmented) 진행 바의 고전 데스크톱 룩.
"""

import os
import sys
import tkinter as tk

from app_tk.theme import FACE, FONT_MONO, FONT_UI, FONT_UI_BOLD, NAVY

SEGMENTS = 24
WIDTH, HEIGHT = 456, 252


def _assets_dir():
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets")


class SplashScreen:
    """모달 없는 스플래시. set_progress(0..1, 상태문구)로 갱신한다."""

    def __init__(self, root):
        self.root = root
        win = tk.Toplevel(root)
        self.win = win
        win.overrideredirect(True)
        win.configure(background=FACE)
        win.attributes("-topmost", True)

        frame = tk.Frame(win, background=FACE, relief="raised", borderwidth=3,
                         width=WIDTH, height=HEIGHT)
        frame.pack(fill="both", expand=True)
        frame.pack_propagate(False)

        strip = tk.Frame(frame, background=NAVY, height=34)
        strip.pack(fill="x")
        strip.pack_propagate(False)
        tk.Label(strip, text="◆ GEMINI SRT TRANSLATOR", background=NAVY,
                 foreground="#ffffff", font=FONT_UI_BOLD).pack(
                     side="left", padx=10, pady=6)
        tk.Label(strip, text="Tk Retro", background=NAVY,
                 foreground="#c8d8f0", font=FONT_UI).pack(
                     side="right", padx=10, pady=6)

        body = tk.Frame(frame, background=FACE)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        self._icon_image = None
        icon_path = os.path.join(_assets_dir(), "app_tk.png")
        if os.path.exists(icon_path):
            try:
                img = tk.PhotoImage(file=icon_path)
                self._icon_image = img.subsample(4, 4)  # 256 → 64
                tk.Label(body, image=self._icon_image,
                         background=FACE).pack(side="left", padx=(0, 14))
            except Exception:
                self._icon_image = None

        texts = tk.Frame(body, background=FACE)
        texts.pack(side="left", fill="both", expand=True)
        tk.Label(texts, text="Gemini SRT Translator",
                 background=FACE, foreground="#1a1a1a",
                 font=(FONT_UI_BOLD,)).pack(anchor="w")
        tk.Label(texts, text="Tkinter · Retro Edition",
                 background=FACE, foreground=NAVY,
                 font=FONT_UI).pack(anchor="w", pady=(2, 0))
        tk.Label(texts, text="자막 번역 워크스테이션",
                 background=FACE, foreground="#444444",
                 font=FONT_UI).pack(anchor="w", pady=(8, 0))

        self.status_var = tk.StringVar(value="준비 중...")
        tk.Label(frame, textvariable=self.status_var, background=FACE,
                 foreground="#1a1a1a", font=FONT_MONO).pack(
                     anchor="w", padx=16)

        self.canvas = tk.Canvas(frame, width=WIDTH - 36, height=18,
                                background="#ffffff", relief="sunken",
                                borderwidth=2, highlightthickness=0)
        self.canvas.pack(padx=16, pady=(4, 6))

        tk.Label(frame, text="© GeminiSRTTranslator GUI — Tk port",
                 background=FACE, foreground="#666666",
                 font=FONT_UI).pack(anchor="e", padx=16, pady=(0, 10))

        self._fraction = 0.0
        self._draw_bar()
        # 화면 중앙 배치 — 첫 매핑에서 위치가 초기화되는 환경(Xvfb 등)이
        # 있어, 매핑 후 같은 지오메트리를 한 번 더 지정해 확정한다.
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - WIDTH) // 2)
        y = max(0, (sh - HEIGHT) // 2)
        geo = f"{WIDTH}x{HEIGHT}+{x}+{y}"
        win.geometry(geo)
        win.lift()
        win.update()
        win.geometry(geo)
        win.update()

    def _draw_bar(self):
        c = self.canvas
        c.delete("all")
        w = WIDTH - 36
        gap = 2
        seg_w = (w - gap * (SEGMENTS - 1)) / SEGMENTS
        filled = int(round(self._fraction * SEGMENTS))
        for i in range(filled):
            x0 = i * (seg_w + gap)
            c.create_rectangle(x0, 2, x0 + seg_w, 14,
                               fill=NAVY, outline=NAVY)

    def set_progress(self, fraction, status=None):
        self._fraction = max(0.0, min(1.0, float(fraction)))
        if status:
            self.status_var.set(status)
        self._draw_bar()
        try:
            self.win.update_idletasks()
        except Exception:
            pass

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass
