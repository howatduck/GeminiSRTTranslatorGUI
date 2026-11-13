# -*- coding: utf-8 -*-
"""Tkinter판 레트로 테마.

Qt판의 매끈한 현대 UI를 Tk로 흉내 내는 대신, Tk 고전 위젯의 질감을
살린 '레트로 데스크톱' 룩으로 통일한다: 실버 그레이 패널, 네이비
타이틀 스트립, 돌출(raised)/함몰(sunken) 베벨, 흰색 입력 필드.
"""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --- 팔레트 ---
FACE = "#c0c0c0"        # 패널/버튼 표면 (클래식 실버 그레이)
FACE_LIGHT = "#d4d0c8"  # 버튼 hover/active
FIELD = "#ffffff"       # 입력 필드 배경
INK = "#1a1a1a"         # 기본 글자색
NAVY = "#000080"        # 타이틀 스트립·선택·진행 바
NAVY_LIGHT = "#1084d0"  # 스트립 그라데이션 흉내 (우측 캡)
TEAL = "#008080"        # 보조 액센트
TERMINAL_BG = "#0c0c0c"

FONT_UI = "RetroUI"
FONT_UI_BOLD = "RetroUIBold"
FONT_MONO = "RetroMono"
FONT_MONO_BOLD = "RetroMonoBold"

# 이름 폰트는 파이썬 객체가 GC되면 Tcl 폰트까지 삭제되므로 참조를 유지한다.
_FONT_REFS = []


def _pick_family(candidates):
    try:
        available = set(tkfont.families())
    except Exception:
        return candidates[0]
    for name in candidates:
        if name in available:
            return name
    return candidates[0]


def apply_retro_theme(root):
    """루트 윈도우에 레트로 테마(폰트·ttk 스타일·기본 배경)를 적용한다."""
    if sys.platform.startswith("win"):
        ui_family = _pick_family(["Tahoma", "Malgun Gothic", "Segoe UI"])
        mono_family = _pick_family(["Consolas", "Courier New"])
        ui_size = 9
    else:
        ui_family = _pick_family(
            ["NanumGothic", "Noto Sans CJK KR", "DejaVu Sans"])
        mono_family = _pick_family(
            ["NanumGothicCoding", "D2Coding", "DejaVu Sans Mono"])
        ui_size = 10

    tkfont.nametofont("TkDefaultFont").configure(family=ui_family, size=ui_size)
    tkfont.nametofont("TkTextFont").configure(family=ui_family, size=ui_size)
    tkfont.nametofont("TkMenuFont").configure(family=ui_family, size=ui_size)
    tkfont.nametofont("TkHeadingFont").configure(
        family=ui_family, size=ui_size, weight="bold")
    tkfont.nametofont("TkFixedFont").configure(family=mono_family, size=ui_size)
    for name, weight in ((FONT_UI, "normal"), (FONT_UI_BOLD, "bold")):
        try:
            _FONT_REFS.append(tkfont.Font(
                name=name, family=ui_family, size=ui_size, weight=weight))
        except tk.TclError:
            pass
    try:
        _FONT_REFS.append(tkfont.Font(
            name=FONT_MONO, family=mono_family, size=ui_size))
    except tk.TclError:
        pass
    try:
        _FONT_REFS.append(tkfont.Font(
            name=FONT_MONO_BOLD, family=mono_family, size=ui_size,
            weight="bold"))
    except tk.TclError:
        pass

    root.configure(background=FACE)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=FACE, foreground=INK, font=FONT_UI)
    style.configure("TFrame", background=FACE)
    style.configure("TLabelframe", background=FACE, borderwidth=2,
                    relief="groove", padding=4)
    style.configure("TLabelframe.Label", background=FACE,
                    font=FONT_UI_BOLD, foreground=NAVY)
    style.configure("TLabel", background=FACE, foreground=INK)
    style.configure("TButton", background=FACE, foreground=INK,
                    borderwidth=2, relief="raised", padding=(8, 3),
                    focusthickness=1, focuscolor=NAVY)
    style.map("TButton",
              background=[("active", FACE_LIGHT), ("disabled", FACE)],
              relief=[("pressed", "sunken"), ("disabled", "raised")],
              foreground=[("disabled", "#7a7a7a")])
    style.configure("Small.TButton", padding=(4, 1))
    style.configure("Accent.TButton", background=NAVY, foreground="#ffffff",
                    borderwidth=2, relief="raised", padding=(10, 4),
                    font=FONT_UI_BOLD)
    style.map("Accent.TButton",
              background=[("active", "#1a1a9e"), ("disabled", FACE)],
              relief=[("pressed", "sunken")],
              foreground=[("disabled", "#7a7a7a")])
    style.configure("TEntry", fieldbackground=FIELD, borderwidth=2,
                    relief="sunken", padding=2)
    style.configure("TCombobox", fieldbackground=FIELD, borderwidth=2,
                    relief="sunken", padding=2, arrowcolor=INK)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD),
                                            ("disabled", FACE)])
    style.configure("TCheckbutton", background=FACE, foreground=INK)
    style.map("TCheckbutton", background=[("active", FACE)])
    style.configure("TRadiobutton", background=FACE, foreground=INK)
    style.map("TRadiobutton", background=[("active", FACE)])
    style.configure("TSpinbox", fieldbackground=FIELD, borderwidth=2,
                    relief="sunken", arrowcolor=INK)
    style.configure("Horizontal.TProgressbar", troughcolor=FIELD,
                    background=NAVY, borderwidth=1, relief="sunken",
                    thickness=14)
    style.configure("Treeview", fieldbackground=FIELD, background=FIELD,
                    foreground=INK, borderwidth=2, relief="sunken",
                    rowheight=22)
    style.configure("Treeview.Heading", background=FACE, foreground=INK,
                    font=FONT_UI_BOLD, borderwidth=1, relief="raised")
    style.map("Treeview", background=[("selected", NAVY)],
              foreground=[("selected", "#ffffff")])
    style.configure("TNotebook", background=FACE, borderwidth=2,
                    relief="raised")
    style.configure("TNotebook.Tab", background=FACE, padding=(10, 3))
    style.map("TNotebook.Tab", background=[("selected", FIELD)])
    return style


def make_title_strip(parent, title, subtitle=""):
    """네이비 타이틀 스트립 (창 상단 배너). 반환: 스트립 프레임."""
    strip = tk.Frame(parent, background=NAVY, height=38)
    strip.pack(fill="x", side="top")
    strip.pack_propagate(False)
    lbl = tk.Label(strip, text=f"◆ {title}", background=NAVY,
                   foreground="#ffffff", font=FONT_UI_BOLD, anchor="w")
    lbl.pack(side="left", padx=10, pady=6)
    if subtitle:
        sub = tk.Label(strip, text=subtitle, background=NAVY,
                       foreground="#c8d8f0", font=FONT_UI, anchor="e")
        sub.pack(side="right", padx=10, pady=6)
    cap = tk.Frame(parent, background=NAVY_LIGHT, height=3)
    cap.pack(fill="x", side="top")
    return strip


def sunken_frame(parent, **kwargs):
    """함몰 베벨 프레임 (터미널·표 같은 콘텐츠 영역용)."""
    kwargs.setdefault("relief", "sunken")
    kwargs.setdefault("borderwidth", 2)
    kwargs.setdefault("background", FIELD)
    return tk.Frame(parent, **kwargs)


# 고전 tk 위젯(Listbox/Text)에 쓸 공통 옵션
LISTBOX_STYLE = dict(
    background=FIELD, foreground=INK, selectbackground=NAVY,
    selectforeground="#ffffff", relief="sunken", borderwidth=2,
    highlightthickness=0, activestyle="none",
)
TEXT_STYLE = dict(
    background=FIELD, foreground=INK, insertbackground=INK,
    selectbackground=NAVY, selectforeground="#ffffff",
    relief="sunken", borderwidth=2, highlightthickness=0,
)
