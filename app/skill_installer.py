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
from core.skill_install_extra import (
    EXTRA_TARGET_IDS, install_extra_skill, load_skill_content,
)

# (target_id, 라벨_ko, 라벨_en)
# gemini_cli/copilot/agy는 라이브러리 install_skill이 몰라서 GUI가 자체
# 설치한다 (core/skill_install_extra.py).
SKILL_TARGETS = [
    ("claude", "Claude Code", "Claude Code"),
    ("agents", "Cursor / Codex / Cline (범용)", "Cursor / Codex / Cline (generic)"),
    ("antigravity", "Antigravity / Gemini", "Antigravity / Gemini"),
    ("gemini_cli", "Gemini CLI", "Gemini CLI"),
    ("copilot", "Muse", "Muse"),
    ("agy", "agy (Antigravity CLI)", "agy (Antigravity CLI)"),
    ("all", "전체", "All"),
]


def target_ids():
    return [t[0] for t in SKILL_TARGETS]


def _as_paths(result):
    """install_skill 반환값을 경로 리스트로 정규화."""
    if result is None:
        return []
    if isinstance(result, (str, os.PathLike)):
        return [str(result)]
    return [str(p) for p in result]


def run_install(target, is_global, folder=None):
    """설치 실행. 반환: (설치 경로 목록, 실패 사유 목록).

    "all"은 대상별로 독립 실행해 일부가 실패해도 나머지를 설치하고,
    성공 내역과 실패 사유를 함께 돌려준다. 단일 대상은 예외를 그대로
    올린다 (호출자가 실패로 표시).
    """
    if target == "all":
        paths, errors = [], []
        if install_skill is not None:
            try:
                paths += _as_paths(install_skill(
                    target="all", is_global=is_global, cwd=folder))
            except Exception as e:
                errors.append(f"library: {e}")
        else:
            errors.append("library: install_skill unavailable")
        for extra in EXTRA_TARGET_IDS:
            try:
                paths += install_extra_skill(
                    extra, is_global=is_global, cwd=folder)
            except Exception as e:
                errors.append(f"{extra}: {e}")
        return paths, errors
    if target in EXTRA_TARGET_IDS:
        return install_extra_skill(target, is_global=is_global,
                                   cwd=folder), []
    if install_skill is None:
        raise RuntimeError(
            "라이브러리의 install_skill을 사용할 수 없습니다. "
            "gemini-srt-translator를 최신 버전으로 업데이트하세요."
        )
    if is_global:
        return _as_paths(install_skill(target=target, is_global=True)), []
    return _as_paths(install_skill(target=target, is_global=False,
                                   cwd=folder)), []


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

        # 라이브러리 install_skill이 없어도 확장 대상은 SKILL.md 내용만으로
        # 설치할 수 있으니, 둘 다 불가능할 때만 버튼을 막는다.
        if install_skill is None and load_skill_content() is None:
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
        is_global = self.radio_global.isChecked()
        folder = None
        if not is_global:
            folder = self.edit_folder.text().strip()
            if not folder or not os.path.isdir(folder):
                QMessageBox.warning(self, self._t("skill_dialog_title"),
                                    self._t("skill_invalid_folder"))
                return
        try:
            paths, errors = run_install(target, is_global, folder)
        except Exception as e:
            self.result_view.setPlainText(self._t("skill_install_failed", err=str(e)))
            return
        lines = []
        if paths:
            lines.append(self._t("skill_installed", paths="\n".join(paths)))
        elif not errors:
            lines.append(self._t("skill_install_empty"))
        for err in errors:
            lines.append(self._t("skill_install_failed", err=err))
        self.result_view.setPlainText("\n\n".join(lines))
