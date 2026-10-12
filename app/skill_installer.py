# -*- coding: utf-8 -*-
"""AI Agent Skill 설치 다이얼로그.

라이브러리(gemini-srt-translator)의 `install_skill()`을 이용해
SKILL.md를 AI 코딩 에이전트(Claude Code, Cursor, Antigravity 등)에 설치한다.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QRadioButton, QLineEdit, QFileDialog, QTextEdit, QMessageBox, QGroupBox,
)

from core.gst_compat import install_skill

# (target_id, 라벨_ko, 라벨_en)
SKILL_TARGETS = [
    ("claude", "Claude Code", "Claude Code"),
    ("agents", "Cursor / Codex / Cline (범용)", "Cursor / Codex / Cline (generic)"),
    ("antigravity", "Antigravity / Gemini", "Antigravity / Gemini"),
    ("all", "전체", "All"),
]


def target_ids():
    return [t[0] for t in SKILL_TARGETS]


class SkillInstallDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle(self._t("skill_dialog_title"))
        self.resize(560, 420)

        layout = QVBoxLayout()

        # --- 플랫폼 선택 ---
        plat_box = QGroupBox(self._t("skill_lbl_platform"))
        plat_layout = QVBoxLayout()
        self.cmb_platform = QComboBox()
        name_key = 1 if getattr(parent, 'app_lang', 'ko') == 'ko' else 2
        for tid, ko, en in SKILL_TARGETS:
            self.cmb_platform.addItem(ko if name_key == 1 else en, tid)
        plat_layout.addWidget(self.cmb_platform)
        plat_box.setLayout(plat_layout)
        layout.addWidget(plat_box)

        # --- 범위 선택 ---
        scope_box = QGroupBox(self._t("skill_lbl_scope"))
        scope_layout = QVBoxLayout()
        self.radio_global = QRadioButton(self._t("skill_scope_global"))
        self.radio_global.setChecked(True)
        self.radio_project = QRadioButton(self._t("skill_scope_project"))
        folder_row = QHBoxLayout()
        self.edit_folder = QLineEdit(os.path.expanduser("~"))
        self.edit_folder.setEnabled(False)
        self.btn_browse = QPushButton(self._t("skill_btn_browse"))
        self.btn_browse.setEnabled(False)
        self.btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.edit_folder, 1)
        folder_row.addWidget(self.btn_browse)
        self.radio_project.toggled.connect(self._on_scope_toggled)
        scope_layout.addWidget(self.radio_global)
        scope_layout.addWidget(self.radio_project)
        scope_layout.addLayout(folder_row)
        scope_box.setLayout(scope_layout)
        layout.addWidget(scope_box)

        # --- 결과 ---
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText(self._t("skill_result_ph"))
        layout.addWidget(self.result_view, 1)

        # --- 버튼 ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_install = QPushButton(self._t("skill_btn_install"))
        self.btn_install.clicked.connect(self._do_install)
        self.btn_close = QPushButton(self._t("btn_close"))
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_install)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.setLayout(layout)

        if install_skill is None:
            self.btn_install.setEnabled(False)
            self.result_view.setPlainText(self._t("skill_no_library"))

    def _t(self, key, **kwargs):
        try:
            return self._parent.tr_str(key, **kwargs)
        except Exception:
            return key

    def _on_scope_toggled(self, checked):
        self.edit_folder.setEnabled(checked)
        self.btn_browse.setEnabled(checked)

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, self._t("skill_pick_folder"),
                                             self.edit_folder.text())
        if d:
            self.edit_folder.setText(d)

    def _do_install(self):
        target = self.cmb_platform.currentData()
        try:
            if self.radio_global.isChecked():
                paths = install_skill(target=target, is_global=True)
            else:
                folder = self.edit_folder.text().strip()
                if not folder or not os.path.isdir(folder):
                    QMessageBox.warning(self, self._t("skill_dialog_title"),
                                        self._t("skill_invalid_folder"))
                    return
                paths = install_skill(target=target, is_global=False, cwd=folder)
        except Exception as e:
            self.result_view.setPlainText(self._t("skill_install_failed", err=str(e)))
            return
        if paths:
            self.result_view.setPlainText(
                self._t("skill_installed", paths="\n".join(paths)))
        else:
            self.result_view.setPlainText(self._t("skill_install_empty"))
