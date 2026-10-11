# -*- coding: utf-8 -*-
"""재사용 UI 위젯: 다중 선택 콤보박스, Pyte VT100 터미널."""

import itertools
import queue
import re
import unicodedata

import pyte

from PyQt6.QtCore import Qt, QSettings, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QCheckBox, QTextEdit,
    QMessageBox, QGroupBox, QFormLayout, QListWidget, QListWidgetItem,
    QSizePolicy, QFrame, QDoubleSpinBox, QProgressBar,
    QToolButton, QScrollArea, QLayout, QDialog,
)




# =====================================================================
# [신규] 다중 선택 가능한 체크박스 콤보박스
# =====================================================================
class CheckableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._model.itemChanged.connect(self._on_item_changed)
        self.view().pressed.connect(self.handle_item_pressed)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("언어를 선택하세요...")
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def handle_item_pressed(self, index):
        item = self._model.itemFromIndex(index)
        if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(new_state)

    def _on_item_changed(self, item):
        self.update_text()

    def set_placeholder_text(self, text):
        self.lineEdit().setPlaceholderText(text)

    def update_text(self):
        texts = [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) and self._model.item(i).checkState() == Qt.CheckState.Checked
        ]
        display = ", ".join(texts)
        self.lineEdit().setText(display)
        if not display:
            self.lineEdit().clear()

    def addItem(self, text, user_data=None):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        if user_data is not None:
            item.setData(user_data, Qt.ItemDataRole.UserRole)
        self._model.appendRow(item)

    def checked_items(self):
        return [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) and self._model.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_checked_items(self, items):
        self._model.blockSignals(True)
        for i in range(self._model.rowCount()):
            item = self._model.item(i)
            if item:
                checked = item.text() in items
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._model.blockSignals(False)
        self.update_text()

    def clear(self):
        self._model.clear()
        self.update_text()



# =====================================================================
# [패치 2] Pyte 기반 완벽한 VT100 터미널 에뮬레이터 위젯
# =====================================================================
class PyteTerminalWidget(QTextEdit):
    """pyte 기반 VT100 터미널 에뮬레이터 위젯"""

    def __init__(self, cols=150, lines=50, history=2000):
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.setStyleSheet("""
            QTextEdit {
                background-color: #0c0c0c;
                color: #cccccc;
                font-family: Consolas, "Courier New", "Liberation Mono", monospace;
                font-size: 13px;
                border: none;
                padding: 4px;
            }
        """)

        self._cols = cols
        self._lines = lines
        self._history = history
        self.screen = pyte.HistoryScreen(cols, lines, history=history)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.Stream(self.screen)

        self.text_queue = queue.Queue()
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._render_terminal)
        self._update_timer.start(30)
        self._dirty = False

        self._flushed_history_len = 0
        self._last_flushed_signature = None
        self._live_start_pos = None

        self._div_style = (
            "white-space: pre; font-family: Consolas, \"Courier New\", monospace; "
            "font-size: 13px; line-height: 1.25;"
        )

        self._status_cycle_step = 0
        self._status_pending_erase = False

    _STATUS_LINE_1 = "Validating token size..."
    _STATUS_LINE_2 = "Token size validated. Translating..."
    _STATUS_LINE_3 = "✅ Translation completed successfully!"

    @staticmethod
    def _normalize_for_match(s):
        cleaned = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
        return cleaned.strip().lower()

    def feed(self, text):
        """텍스트를 터미널에 피드 (VT100 시퀀스 지원)"""
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
        self._last_flushed_signature = None
        self._live_start_pos = None
        self._status_cycle_step = 0
        self._status_pending_erase = False
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        self._dirty = False
        self.clear()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

    _COLOR_MAP = {
        'black': '#0c0c0c', 'red': '#e74856', 'green': '#16c60c',
        'brown': '#f9f1a5', 'blue': '#3b78ff', 'magenta': '#b4009e',
        'cyan': '#61d6d6', 'white': '#cccccc',
        'lightblack': '#767676', 'lightred': '#f96270', 'lightgreen': '#23d11b',
        'lightbrown': '#fdf6af', 'lightblue': '#548cff', 'lightmagenta': '#c810b1',
        'lightcyan': '#78e2e2', 'lightwhite': '#ffffff'
    }

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

    def _line_to_html(self, line_dict):
        chunks = []
        last_fg = None
        last_bg = None
        span_open = False

        last_col = self._line_last_col(line_dict)

        for col in range(last_col + 1):
            char_obj = line_dict[col]
            fg = self._color_to_hex(char_obj.fg)
            bg = self._color_to_hex(char_obj.bg)

            if fg != last_fg or bg != last_bg:
                if span_open:
                    chunks.append("</span>")
                style = ""
                if fg:
                    style += f"color: {fg};"
                if bg:
                    style += f"background-color: {bg};"
                if style:
                    chunks.append(f"<span style='{style}'>")
                    span_open = True
                else:
                    span_open = False
                last_fg = fg
                last_bg = bg

            ch = char_obj.data
            if ch == '<':
                chunks.append('&lt;')
            elif ch == '>':
                chunks.append('&gt;')
            elif ch == '&':
                chunks.append('&amp;')
            else:
                chunks.append(ch)

        if span_open:
            chunks.append("</span>")
        return "".join(chunks)

    def _line_signature(self, line_dict):
        last_col = self._line_last_col(line_dict)
        return "".join(line_dict[c].data for c in range(last_col + 1))

    def _lines_block_html(self, line_dicts):
        parts = [f"<div style='{self._div_style}'>"]
        for line_dict in line_dicts:
            parts.append(self._line_to_html(line_dict))
            parts.append("\n")
        parts.append("</div>")
        return "".join(parts)

    def _render_terminal(self):
        while not self.text_queue.empty():
            try:
                self.stream.feed(self.text_queue.get_nowait())
                self._dirty = True
            except queue.Empty:
                break

        if not self._dirty:
            return
        self._dirty = False

        scrollbar = self.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 5

        history_top = self.screen.history.top
        history_len = len(history_top)

        needs_full_rebuild = self._live_start_pos is None
        if not needs_full_rebuild and self._flushed_history_len > 0:
            check_idx = self._flushed_history_len - 1
            if check_idx >= history_len:
                needs_full_rebuild = True
            else:
                current_sig = self._line_signature(history_top[check_idx])
                if current_sig != self._last_flushed_signature:
                    needs_full_rebuild = True

        cursor = QTextCursor(self.document())

        def insert_block_html(html):
            if not self.document().isEmpty():
                cursor.insertBlock()
            cursor.insertHtml(html)

        if needs_full_rebuild:
            self.setHtml("")
            self._live_start_pos = None
        elif self._live_start_pos is not None:
            doc_len = self.document().characterCount()
            pos = min(self._live_start_pos, max(0, doc_len - 1))
            cursor.setPosition(pos)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

        if needs_full_rebuild:
            if history_len:
                cursor.movePosition(QTextCursor.MoveOperation.End)
                insert_block_html(self._lines_block_html(history_top))
            self._flushed_history_len = history_len
        elif history_len > self._flushed_history_len:
            new_lines = list(itertools.islice(history_top, self._flushed_history_len, history_len))
            cursor.movePosition(QTextCursor.MoveOperation.End)
            insert_block_html(self._lines_block_html(new_lines))
            self._flushed_history_len = history_len

        if history_len:
            self._last_flushed_signature = self._line_signature(history_top[self._flushed_history_len - 1])

        buffer_lines = [self.screen.buffer[i] for i in range(self.screen.lines)]
        while buffer_lines:
            last_line = buffer_lines[-1]
            if self._line_last_col(last_line) < 0:
                buffer_lines.pop()
            else:
                break

        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._live_start_pos = cursor.position()
        if buffer_lines:
            insert_block_html(self._lines_block_html(buffer_lines))

        if is_at_bottom:
            scrollbar.setValue(scrollbar.maximum())
