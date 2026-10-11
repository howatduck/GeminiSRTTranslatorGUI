# -*- coding: utf-8 -*-
"""번역 결과 미리보기/편집 다이얼로그."""

import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog,
    QTextEdit, QDialogButtonBox,
)

from core.subtitle_io import entry_cps, format_srt, parse_srt

CPS_WARN_THRESHOLD = 20.0  # 초당 글자수 경고 기준 (참고용)

COL_NUM, COL_START, COL_END, COL_CPS, COL_TRANS, COL_ORIG = range(6)


class SubtitlePreviewDialog(QDialog):
    """번역된 SRT를 원문과 대조하며 보고, 번역문을 수정·저장한다."""

    def __init__(self, parent, translated_path, original_path=None):
        super().__init__(parent)
        self._parent = parent
        self.translated_path = translated_path
        self.original_path = original_path
        self.trans_entries = []
        self.orig_entries = []
        self._dirty = False

        self.setWindowTitle(self._t("preview_title"))
        self.resize(1100, 700)

        layout = QVBoxLayout()

        # --- 파일 정보 바 ---
        file_bar = QHBoxLayout()
        self.lbl_trans_file = QLabel()
        self.lbl_orig_file = QLabel()
        self.btn_open_trans = QPushButton(self._t("preview_open_translated"))
        self.btn_open_trans.clicked.connect(self._pick_translated)
        self.btn_open_orig = QPushButton(self._t("preview_open_original"))
        self.btn_open_orig.clicked.connect(self._pick_original)
        file_bar.addWidget(self.lbl_trans_file, 1)
        file_bar.addWidget(self.btn_open_trans)
        file_bar.addWidget(self.lbl_orig_file, 1)
        file_bar.addWidget(self.btn_open_orig)
        layout.addLayout(file_bar)

        # --- 검색 바 ---
        search_bar = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(self._t("preview_search_ph"))
        self.search_box.textChanged.connect(self._apply_search)
        self.lbl_rows = QLabel()
        search_bar.addWidget(self.search_box, 1)
        search_bar.addWidget(self.lbl_rows)
        layout.addLayout(search_bar)

        # --- 테이블 ---
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            self._t("preview_col_num"), self._t("preview_col_start"),
            self._t("preview_col_end"), self._t("preview_col_cps"),
            self._t("preview_col_trans"), self._t("preview_col_orig"),
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NUM, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_START, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_END, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_CPS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_TRANS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ORIG, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_NUM, 50)
        self.table.setColumnWidth(COL_START, 110)
        self.table.setColumnWidth(COL_END, 110)
        self.table.setColumnWidth(COL_CPS, 60)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._edit_cell)
        layout.addWidget(self.table, 1)

        # --- 하단 버튼 ---
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        self.btn_save = QPushButton(self._t("btn_save"))
        self.btn_save.clicked.connect(self._save)
        self.btn_save.setEnabled(False)
        self.btn_close = QPushButton(self._t("btn_close"))
        self.btn_close.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_save)
        btn_bar.addWidget(self.btn_close)
        layout.addLayout(btn_bar)

        self.setLayout(layout)
        self._reload()

    # -- helpers ---------------------------------------------------------
    def _t(self, key, **kwargs):
        try:
            return self._parent.tr_str(key, **kwargs)
        except Exception:
            return key

    def _read_entries(self, path):
        if not path or not os.path.isfile(path):
            return []
        if path.lower().endswith(".ass"):
            QMessageBox.warning(
                self, self._t("preview_title"),
                self._t("preview_ass_unsupported",
                        file=os.path.basename(path)))
            return []
        try:
            with open(path, encoding="utf-8-sig") as f:
                return parse_srt(f.read())
        except Exception as e:
            QMessageBox.warning(self, self._t("preview_title"), str(e))
            return []

    def _reload(self):
        self.trans_entries = self._read_entries(self.translated_path)
        self.orig_entries = self._read_entries(self.original_path)
        self._dirty = False
        self.btn_save.setEnabled(False)
        self.lbl_trans_file.setText(
            self._t("preview_translated_file",
                    file=os.path.basename(self.translated_path or "")))
        self.lbl_orig_file.setText(
            self._t("preview_original_file",
                    file=os.path.basename(self.original_path or "")
                    if self.original_path else "—"))
        self._populate()
        self._apply_search()

    def _populate(self):
        t = self.table
        t.setRowCount(len(self.trans_entries))
        for r, e in enumerate(self.trans_entries):
            num = QTableWidgetItem(str(e["index"]))
            num.setFlags(num.flags() & ~Qt.ItemFlag.ItemIsEditable)
            start = QTableWidgetItem(e["start"])
            start.setFlags(start.flags() & ~Qt.ItemFlag.ItemIsEditable)
            end = QTableWidgetItem(e["end"])
            end.setFlags(end.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cps = entry_cps(e)
            cps_item = QTableWidgetItem(f"{cps:.1f}" if cps is not None else "—")
            cps_item.setFlags(cps_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if cps is not None and cps > CPS_WARN_THRESHOLD:
                cps_item.setBackground(Qt.GlobalColor.red)
                cps_item.setForeground(Qt.GlobalColor.white)
            trans = QTableWidgetItem(e["text"])
            trans.setFlags(trans.flags() & ~Qt.ItemFlag.ItemIsEditable)
            trans.setToolTip(self._t("preview_dblclick_edit"))
            orig_text = ""
            if r < len(self.orig_entries):
                orig_text = self.orig_entries[r]["text"]
            orig = QTableWidgetItem(orig_text)
            orig.setFlags(orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
            for c, item in enumerate([num, start, end, cps_item, trans, orig]):
                t.setItem(r, c, item)
        self._update_row_label()

    def _update_row_label(self):
        visible = sum(1 for r in range(self.table.rowCount())
                      if not self.table.isRowHidden(r))
        self.lbl_rows.setText(
            self._t("preview_rows", visible=visible,
                    total=self.table.rowCount()))

    def _apply_search(self):
        q = self.search_box.text().strip().lower()
        for r in range(self.table.rowCount()):
            if not q:
                self.table.setRowHidden(r, False)
                continue
            hay = " ".join(
                (self.table.item(r, c).text() if self.table.item(r, c) else "")
                for c in (COL_TRANS, COL_ORIG))
            self.table.setRowHidden(r, q not in hay.lower())
        self._update_row_label()

    # -- editing ---------------------------------------------------------
    def _edit_cell(self, row, col):
        if col != COL_TRANS:
            return
        item = self.table.item(row, col)
        dlg = QDialog(self)
        dlg.setWindowTitle(self._t("preview_edit_title", num=row + 1))
        dlg.resize(600, 300)
        v = QVBoxLayout()
        edit = QTextEdit()
        edit.setPlainText(item.text())
        v.addWidget(edit, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        dlg.setLayout(v)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_text = edit.toPlainText().strip()
            if new_text != item.text():
                item.setText(new_text)
                self.trans_entries[row]["text"] = new_text
                cps = entry_cps(self.trans_entries[row])
                cps_item = self.table.item(row, COL_CPS)
                cps_item.setText(f"{cps:.1f}" if cps is not None else "—")
                self._dirty = True
                self.btn_save.setEnabled(True)

    def _pick_translated(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("preview_open_translated"), "",
            "Subtitles (*.srt)")
        if path:
            self.translated_path = path
            self._reload()

    def _pick_original(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("preview_open_original"), "",
            "Subtitles (*.srt)")
        if path:
            self.original_path = path
            self._reload()

    def _save(self):
        if not self._dirty or not self.translated_path:
            return
        bak = self.translated_path + ".bak"
        try:
            if os.path.isfile(self.translated_path):
                shutil.copy2(self.translated_path, bak)
            with open(self.translated_path, "w", encoding="utf-8") as f:
                f.write(format_srt(self.trans_entries))
        except Exception as e:
            QMessageBox.critical(self, self._t("preview_title"), str(e))
            return
        self._dirty = False
        self.btn_save.setEnabled(False)
        QMessageBox.information(
            self, self._t("preview_title"),
            self._t("preview_saved", bak=os.path.basename(bak)))
