# -*- coding: utf-8 -*-
"""에이전트 파일 교환 다이얼로그.

자막 배치를 JSON 파일로 내보내 어떤 AI 채팅(ChatGPT 웹 등)으로도
번역하게 하고, 번역된 파일을 다시 가져와 완성한다. 진행 상태와
검증은 라이브러리 SubtitleSession이 담당한다 (core/agent_bridge.py).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QLineEdit, QFileDialog, QTextEdit, QMessageBox, QGroupBox,
)

from core import agent_bridge
from core.style_presets import all_presets, preset_instruction


class AgentExchangeDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle(self._t("agent_dialog_title"))
        self.resize(600, 480)

        layout = QVBoxLayout()

        # --- 입력 ---
        in_box = QGroupBox(self._t("agent_grp_input"))
        in_layout = QVBoxLayout()
        file_row = QHBoxLayout()
        self.edit_file = QLineEdit()
        self.edit_file.setPlaceholderText(self._t("agent_file_ph"))
        self.btn_browse = QPushButton(self._t("agent_btn_browse"))
        self.btn_browse.clicked.connect(self._browse_file)
        file_row.addWidget(QLabel(self._t("agent_lbl_file")))
        file_row.addWidget(self.edit_file, 1)
        file_row.addWidget(self.btn_browse)
        in_layout.addLayout(file_row)

        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel(self._t("agent_lbl_language")))
        self.edit_lang = QLineEdit("Korean")
        opt_row.addWidget(self.edit_lang)
        opt_row.addWidget(QLabel(self._t("agent_lbl_batch")))
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(10, 300)
        self.spin_batch.setValue(agent_bridge.DEFAULT_BATCH_SIZE)
        opt_row.addWidget(self.spin_batch)
        opt_row.addStretch()
        in_layout.addLayout(opt_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel(self._t("agent_lbl_style")))
        self.cmb_style = QComboBox()
        lang = getattr(parent, "app_lang", "ko")
        custom = getattr(parent, "custom_presets", None)
        name_key = "name_ko" if lang == "ko" else "name_en"
        for p in all_presets(custom, lang):
            self.cmb_style.addItem(p.get(name_key) or p["id"], p["id"])
        style_row.addWidget(self.cmb_style, 1)
        in_layout.addLayout(style_row)
        in_box.setLayout(in_layout)
        layout.addWidget(in_box)
        self._prefill_from_parent()

        # --- 실행 버튼 ---
        act_row = QHBoxLayout()
        self.btn_export = QPushButton(self._t("agent_btn_export"))
        self.btn_export.clicked.connect(self._do_export)
        self.btn_import = QPushButton(self._t("agent_btn_import"))
        self.btn_import.clicked.connect(self._do_import)
        self.btn_status = QPushButton(self._t("agent_btn_status"))
        self.btn_status.clicked.connect(self._do_status)
        self.btn_reset = QPushButton(self._t("agent_btn_reset"))
        self.btn_reset.clicked.connect(self._do_reset)
        for b in (self.btn_export, self.btn_import, self.btn_status,
                  self.btn_reset):
            act_row.addWidget(b)
        act_row.addStretch()
        layout.addLayout(act_row)

        # --- 결과 ---
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText(self._t("agent_result_ph"))
        layout.addWidget(self.result_view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_close = QPushButton(self._t("btn_close"))
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.setLayout(layout)

        if agent_bridge.SubtitleSession is None:
            for b in (self.btn_export, self.btn_import, self.btn_status,
                      self.btn_reset):
                b.setEnabled(False)
            self.result_view.setPlainText(self._t("agent_no_library"))

    def _t(self, key, **kwargs):
        try:
            return self._parent.tr_str(key, **kwargs)
        except Exception:
            return key

    def _prefill_from_parent(self):
        """메인 윈도우의 현재 선택(파일·언어·스타일)을 기본값으로 가져온다."""
        parent = self._parent
        try:
            files = getattr(parent, "input_files", None) or []
            for f in files:
                if f.lower().endswith((".srt", ".ass")):
                    self.edit_file.setText(f)
                    break
        except Exception:
            pass
        try:
            checked = parent.cmb_langs.checked_items()
            if checked:
                self.edit_lang.setText(checked[0])
        except Exception:
            pass
        try:
            pid = parent.cmb_style.currentData()
            idx = self.cmb_style.findData(pid)
            if idx >= 0:
                self.cmb_style.setCurrentIndex(idx)
        except Exception:
            pass

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("agent_pick_input"), self.edit_file.text(),
            "Subtitle (*.srt *.ass);;All files (*)")
        if path:
            self.edit_file.setText(path)

    def _input_file(self):
        path = self.edit_file.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, self._t("agent_dialog_title"),
                                self._t("agent_invalid_input"))
            return None
        return path

    def _style_instruction(self):
        pid = self.cmb_style.currentData()
        custom = getattr(self._parent, "custom_presets", None)
        try:
            return preset_instruction(pid, custom) or ""
        except Exception:
            return ""

    def _progress_text(self, status):
        done = status.get("completed_lines", 0)
        total = status.get("total_lines", 0)
        pct = status.get("progress_percent", 0)
        return f"{done}/{total} ({pct}%)"

    def _show_ready(self, key, result):
        status = result.get("status") or {}
        lines = [self._t(key, path=result.get("batch_file", ""))]
        inst = result.get("instructions_file")
        if inst:
            lines.append(inst)
        lines.append(self._progress_text(status))
        self.result_view.setPlainText("\n".join(lines))

    def _show_completed(self, result):
        self.result_view.setPlainText(
            self._t("agent_completed",
                    path=result.get("output_file", "")))

    def _do_export(self):
        path = self._input_file()
        if not path:
            return
        lang = self.edit_lang.text().strip() or "Korean"
        try:
            result = agent_bridge.start_exchange(
                path, lang, batch_size=self.spin_batch.value(),
                style_instruction=self._style_instruction())
        except Exception as e:
            self.result_view.setPlainText(self._t("agent_failed", err=str(e)))
            return
        if result["state"] == "completed":
            self._show_completed(result)
        else:
            self._show_ready("agent_export_done", result)

    def _do_import(self):
        path = self._input_file()
        if not path:
            return
        start_dir = agent_bridge.exchange_dir_for(path)
        translated, _ = QFileDialog.getOpenFileName(
            self, self._t("agent_pick_translated"),
            start_dir if os.path.isdir(start_dir) else "",
            "JSON (*.json);;All files (*)")
        if not translated:
            return
        try:
            result = agent_bridge.commit_exchange(
                path, translated, batch_size=self.spin_batch.value())
        except Exception as e:
            self.result_view.setPlainText(self._t("agent_failed", err=str(e)))
            return
        if result["state"] == "completed":
            self._show_completed(result)
        else:
            self._show_ready("agent_import_done", result)

    def _do_status(self):
        path = self._input_file()
        if not path:
            return
        try:
            result = agent_bridge.exchange_status(
                path, batch_size=self.spin_batch.value())
        except Exception as e:
            self.result_view.setPlainText(self._t("agent_failed", err=str(e)))
            return
        if result["state"] == "completed":
            self._show_completed(result)
        else:
            status = result.get("status") or {}
            self.result_view.setPlainText(self._t(
                "agent_status", progress=self._progress_text(status),
                path=result.get("batch_file", "")))

    def _do_reset(self):
        path = self._input_file()
        if not path:
            return
        if QMessageBox.question(self, self._t("agent_dialog_title"),
                                self._t("agent_reset_confirm")) \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            agent_bridge.reset_exchange(path)
        except Exception as e:
            self.result_view.setPlainText(self._t("agent_failed", err=str(e)))
            return
        self.result_view.setPlainText(self._t("agent_reset_done"))
