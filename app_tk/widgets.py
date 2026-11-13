# -*- coding: utf-8 -*-
"""Tkinter판 공용 위젯 — 터미널 로그(pyte) + 체크 가능 언어 드롭다운.

터미널은 PyQt판 PyteTerminalWidget과 같은 구조(pyte HistoryScreen +
상태 사이클 접기 + 증분 렌더)를 Tk Text 태그로 구현했다.
"""

import queue
import tkinter as tk
import unicodedata
from tkinter import ttk

import pyte

from app_tk.theme import (
    FONT_MONO, FONT_MONO_BOLD, LISTBOX_STYLE, TERMINAL_BG,
)


def set_enabled(widget, enabled):
    """ttk/tk 위젯 공통 활성/비활성 전환."""
    try:
        widget.state(["!disabled" if enabled else "disabled"])
        return
    except Exception:
        pass
    try:
        widget.configure(state="normal" if enabled else "disabled")
    except Exception:
        pass


class TerminalLog(tk.Frame):
    """pyte 기반 VT100 터미널 로그 (읽기 전용)."""

    _COLOR_MAP = {
        'black': '#0c0c0c', 'red': '#e74856', 'green': '#16c60c',
        'brown': '#f9f1a5', 'blue': '#3b78ff', 'magenta': '#b4009e',
        'cyan': '#61d6d6', 'white': '#cccccc',
        'lightblack': '#767676', 'lightred': '#f96270', 'lightgreen': '#23d11b',
        'lightbrown': '#fdf6af', 'lightblue': '#548cff', 'lightmagenta': '#c810b1',
        'lightcyan': '#78e2e2', 'lightwhite': '#ffffff'
    }

    def __init__(self, parent, cols=150, lines=50, history=2000):
        super().__init__(parent, relief="sunken", borderwidth=2,
                         background=TERMINAL_BG)
        self.text = tk.Text(
            self, wrap="none", bg=TERMINAL_BG, fg="#cccccc", height=20,
            insertbackground="#cccccc", relief="flat", borderwidth=0,
            font=FONT_MONO, padx=4, pady=4, undo=False,
        )
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.text.bind("<Key>", self._guard_keys)
        self.text.bind("<<Paste>>", lambda e: "break")

        self._cols = cols
        self._lines = lines
        self.screen = pyte.HistoryScreen(cols, lines, history=history)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.Stream(self.screen)
        self.text_queue = queue.Queue()
        self._dirty = False
        self._flushed_history_len = 0
        self._live_start_line = 1  # Text 라인 번호(1-base)
        self._tags_made = set()
        self._status_cycle_step = 0
        self._status_pending_erase = False
        self.after(30, self._render_terminal)

    # -- 입력 가드 (복사·이동 키만 허용) ------------------------------------
    def _guard_keys(self, event):
        if event.state & 0x4:  # Control: 복사 등 허용
            return None
        if event.keysym in (
                "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                "KP_Home", "KP_End", "Shift_L", "Shift_R", "F1", "F2", "F3",
                "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"):
            return None
        return "break"

    # -- PyQt판과 같은 상태 사이클 접기 --------------------------------------
    @staticmethod
    def _normalize_for_match(s):
        cleaned = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
        return cleaned.strip().lower()

    def feed(self, text):
        if not text:
            return
        pieces = text.split("\n")
        out_pieces = []
        for line in pieces:
            norm = self._normalize_for_match(line)
            erase_prefix = ""
            if norm == "":
                pass
            elif "validating token size" in norm:
                if self._status_pending_erase:
                    erase_prefix = "\x1b[3A\r\x1b[0J"
                    self._status_pending_erase = False
                self._status_cycle_step = 1
            elif "token size validated" in norm and self._status_cycle_step == 1:
                self._status_cycle_step = 2
            elif "translation completed successfully" in norm and self._status_cycle_step == 2:
                self._status_cycle_step = 0
                self._status_pending_erase = True
            else:
                self._status_cycle_step = 0
                self._status_pending_erase = False
            out_pieces.append(erase_prefix + line)
        text = "\n".join(out_pieces)
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        self.text_queue.put(text)

    def feed_line(self, text):
        self.feed(text + "\n")

    def clear_screen(self):
        self.screen.reset()
        if hasattr(pyte, 'modes') and hasattr(pyte.modes, 'LNM'):
            self.screen.set_mode(pyte.modes.LNM)
        if hasattr(self.screen, 'history'):
            self.screen.history.top.clear()
            self.screen.history.bottom.clear()
        self._flushed_history_len = 0
        self._live_start_line = 1
        self._status_cycle_step = 0
        self._status_pending_erase = False
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        self._dirty = False
        self.text.delete("1.0", "end")

    # -- 렌더링 ---------------------------------------------------------------
    def _color_to_hex(self, color_name):
        if not color_name or color_name == 'default':
            return None
        if isinstance(color_name, str):
            if color_name.startswith('#'):
                return color_name
            mapped = self._COLOR_MAP.get(color_name)
            if mapped:
                return mapped
            if len(color_name) == 6:
                return f"#{color_name}"
            if len(color_name) == 3:
                return f"#{color_name[0]*2}{color_name[1]*2}{color_name[2]*2}"
        return None

    def _line_last_col(self, line_dict):
        last_col = self.screen.columns - 1
        while last_col >= 0:
            char_obj = line_dict[last_col]
            if char_obj.data != ' ':
                break
            if char_obj.bg != 'default' and char_obj.bg is not None:
                break
            last_col -= 1
        return last_col

    def _tag_for(self, fg, bg, bold):
        name = f"t_{fg or 'd'}_{bg or 'd'}_{'b' if bold else 'n'}".replace('#', '')
        if name not in self._tags_made:
            self._tags_made.add(name)
            kwargs = {}
            if fg:
                kwargs["foreground"] = fg
            if bg:
                kwargs["background"] = bg
            if bold:
                kwargs["font"] = FONT_MONO_BOLD
            self.text.tag_configure(name, **kwargs)
        return name

    def _insert_line(self, line_dict):
        """한 줄을 (텍스트, 태그) 런 단위로 삽입한다."""
        last_col = self._line_last_col(line_dict)
        run_text = ""
        run_tag = None
        for col in range(last_col + 1):
            char_obj = line_dict[col]
            fg = self._color_to_hex(char_obj.fg)
            bg = self._color_to_hex(char_obj.bg)
            tag = self._tag_for(fg, bg, bool(getattr(char_obj, "bold", False)))
            if tag != run_tag:
                if run_text:
                    self.text.insert("end", run_text, run_tag)
                run_text = char_obj.data
                run_tag = tag
            else:
                run_text += char_obj.data
        if run_text:
            self.text.insert("end", run_text, run_tag)
        self.text.insert("end", "\n")

    def _render_terminal(self):
        try:
            while not self.text_queue.empty():
                try:
                    self.stream.feed(self.text_queue.get_nowait())
                    self._dirty = True
                except queue.Empty:
                    break
            if self._dirty:
                self._dirty = False
                self._render_now()
        finally:
            self.after(30, self._render_terminal)

    def _render_now(self):
        at_bottom = self.text.yview()[1] >= 0.999
        history_top = self.screen.history.top
        history_len = len(history_top)

        # 히스토리로 확정된 줄이 늘면 전체를 다시 그린다 (단순·확실한 방식)
        if history_len > self._flushed_history_len:
            self._rebuild_all(history_top)
            self._flushed_history_len = history_len
            if at_bottom:
                self.text.see("end")
            return

        # 라이브(현재 화면) 영역만 교체
        start = f"{self._live_start_line}.0"
        self.text.delete(start, "end-1c")
        buffer_lines = [self.screen.buffer[i] for i in range(self.screen.lines)]
        while buffer_lines and self._line_last_col(buffer_lines[-1]) < 0:
            buffer_lines.pop()
        for line_dict in buffer_lines:
            self._insert_line(line_dict)
        if at_bottom:
            self.text.see("end")

    def _rebuild_all(self, history_top):
        self.text.delete("1.0", "end")
        for line_dict in history_top:
            self._insert_line(line_dict)
        # 히스토리 줄 수 + 1 = 라이브(현재 화면) 영역의 시작 라인
        self._live_start_line = len(history_top) + 1
        buffer_lines = [self.screen.buffer[i] for i in range(self.screen.lines)]
        while buffer_lines and self._line_last_col(buffer_lines[-1]) < 0:
            buffer_lines.pop()
        for line_dict in buffer_lines:
            self._insert_line(line_dict)


class CheckableDropdown(ttk.Frame):
    """체크 가능한 드롭다운 (언어 다중 선택) — CheckableComboBox 대체."""

    def __init__(self, parent):
        super().__init__(parent)
        self._items = []
        self._checked = set()
        self._placeholder = ""
        self._popup = None
        self._label_var = tk.StringVar(value="")
        self._button = ttk.Button(
            self, textvariable=self._label_var, command=self._toggle_popup)
        self._button.pack(fill="x", expand=True)
        self._update_text()

    # -- Qt 호환 API -----------------------------------------------------------
    def addItem(self, text):
        if text not in self._items:
            self._items.append(text)

    def all_items(self):
        return list(self._items)

    def checked_items(self):
        return [t for t in self._items if t in self._checked]

    def set_checked_items(self, items):
        self._checked = {t for t in items if t in self._items}
        self._update_text()

    def set_placeholder_text(self, text):
        self._placeholder = text
        self._update_text()

    def clear(self):
        self._items.clear()
        self._checked.clear()
        self._update_text()

    # -- 내부 -------------------------------------------------------------------
    def _update_text(self):
        checked = self.checked_items()
        if checked:
            label = ", ".join(checked)
            if len(label) > 60:
                label = label[:57] + "..."
        else:
            label = self._placeholder or "선택"
        self._label_var.set(label + "  ▾")

    def _toggle_popup(self):
        if self._popup is not None:
            self._close_popup()
            return
        popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        popup.attributes("-topmost", True)
        self._popup = popup
        x = self._button.winfo_rootx()
        y = self._button.winfo_rooty() + self._button.winfo_height()
        popup.geometry(f"+{x}+{y}")

        frame = ttk.Frame(popup, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(
            frame, height=min(18, max(5, len(self._items))),
            width=42, selectmode="browse", **LISTBOX_STYLE)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        for text in self._items:
            mark = "☑ " if text in self._checked else "☐ "
            listbox.insert("end", mark + text)
        self._listbox = listbox

        def on_click(event):
            idx = listbox.nearest(event.y)
            if idx < 0 or idx >= len(self._items):
                return "break"
            text = self._items[idx]
            if text in self._checked:
                self._checked.discard(text)
                listbox.delete(idx)
                listbox.insert(idx, "☐ " + text)
            else:
                self._checked.add(text)
                listbox.delete(idx)
                listbox.insert(idx, "☑ " + text)
            listbox.selection_set(idx)
            self._update_text()
            return "break"

        listbox.bind("<ButtonRelease-1>", on_click)
        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(btn_row, text="닫기", command=self._close_popup).pack(
            side="right", padx=4, pady=4)
        popup.bind("<Escape>", lambda e: self._close_popup())
        popup.focus_set()

    def _close_popup(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None


def enable_file_drop(widget, callback):
    """OS 파일 드래그&드롭 등록 (tkinterdnd2 필요, 없으면 조용히 비활성).

    루트가 TkinterDnD.Tk일 때만 실제 동작한다. callback에는 경로
    리스트가 넘어간다. 등록 성공 시 True.
    """
    try:
        from tkinterdnd2 import DND_FILES
    except Exception:
        return False
    try:
        widget.drop_target_register(DND_FILES)

        def _on_drop(event):
            try:
                paths = list(widget.tk.splitlist(event.data))
            except Exception:
                paths = [event.data]
            if paths:
                callback(paths)
            return "break"

        widget.dnd_bind("<<Drop>>", _on_drop)
        return True
    except Exception:
        return False
