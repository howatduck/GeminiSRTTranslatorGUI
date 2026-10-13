# -*- coding: utf-8 -*-
"""자막 정리 도구 다이얼로그 (리네임 / ilass 싱크 중 단일 작업 실행).

kracc 서버의 subs_toolkit.py 기능을 GUI로 제공한다:
  - 리네임: 영상 파일명에 맞춰 외부 자막 파일명 변경 (미리보기 지원)
  - 싱크: ilass로 영상 기준 자막 타이밍 보정
한 번에 하나의 작업만 실행한다. 폴더 내용이 바뀌면 새로고침으로 다시 스캔.
"""

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QLineEdit, QFileDialog, QTextEdit, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QSpinBox, QMessageBox,
    QAbstractItemView, QRadioButton, QButtonGroup,
)

from core import subtitle_tools as st

STEP_RENAME = "rename"
STEP_SYNC = "sync"


class SubtitleToolsWorker(QThread):
    """리네임/싱크 단일 작업 백그라운드 워커."""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, folder, mode, step, sync_opts):
        super().__init__()
        self.folder = folder
        self.mode = mode
        self.step = step
        self.sync_opts = dict(sync_opts)

    def _log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        try:
            summary = {}
            if self.step == STEP_RENAME:
                self._log("=== 자막 리네임 시작 ===")
                plan, unmatched = st.plan_rename(self.folder, self.mode)
                if not plan:
                    self._log("리네임 대상이 없습니다.")
                applied, skipped = st.apply_rename(plan, log=self._log)
                for u in unmatched:
                    self._log(f"[매칭 실패] {u} (수동 확인 필요)")
                summary = {"applied": applied, "skipped": skipped,
                           "unmatched": len(unmatched)}
                self._log(f"리네임 완료: 적용 {applied} / 건너뜀 {skipped} / "
                          f"매칭실패 {len(unmatched)}")
            else:
                self._log("=== ilass 자막 싱크 시작 ===")
                summary = st.run_sync(
                    self.folder,
                    log=self._log,
                    progress=lambda d, t: self.progress_signal.emit(d, t),
                    **self.sync_opts,
                )
            self.finished_signal.emit(summary)
        except st.SubtitleToolsError as e:
            self.error_signal.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.error_signal.emit(f"예상치 못한 오류: {e}")


class SubtitleToolsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle(self._t("subtools_dialog_title"))
        self.resize(720, 640)
        self._worker = None

        layout = QVBoxLayout()

        # --- 폴더 선택 + 새로고침 ---
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(self._t("subtools_lbl_folder")))
        self.edit_folder = QLineEdit(os.path.expanduser("~"))
        self.btn_browse = QPushButton(self._t("subtools_btn_browse"))
        self.btn_browse.clicked.connect(self._browse_folder)
        self.btn_refresh = QPushButton(self._t("subtools_btn_refresh"))
        self.btn_refresh.clicked.connect(self._refresh_preview)
        folder_row.addWidget(self.edit_folder, 1)
        folder_row.addWidget(self.btn_browse)
        folder_row.addWidget(self.btn_refresh)
        layout.addLayout(folder_row)

        # --- 모드 + 작업 선택 (단일) ---
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel(self._t("subtools_lbl_mode")))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem(self._t("subtools_mode_tv"), "tv")
        self.cmb_mode.addItem(self._t("subtools_mode_movie"), "movie")
        self.cmb_mode.currentIndexChanged.connect(lambda _: self._refresh_preview())
        opt_row.addWidget(self.cmb_mode)
        opt_row.addWidget(QLabel(self._t("subtools_lbl_step")))
        self.radio_rename = QRadioButton(self._t("subtools_radio_rename"))
        self.radio_sync = QRadioButton(self._t("subtools_radio_sync"))
        self.radio_rename.setChecked(True)
        step_group = QButtonGroup(self)
        step_group.addButton(self.radio_rename)
        step_group.addButton(self.radio_sync)
        self.radio_rename.toggled.connect(self._on_step_changed)
        opt_row.addWidget(self.radio_rename)
        opt_row.addWidget(self.radio_sync)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # --- ilass 상태 ---
        self.lbl_ilass = QLabel()
        self._refresh_ilass_status()
        layout.addWidget(self.lbl_ilass)

        # --- 미리보기 ---
        prev_box = QGroupBox(self._t("subtools_grp_preview"))
        prev_layout = QVBoxLayout()
        self.tbl_preview = QTableWidget(0, 3)
        self.tbl_preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.tbl_preview.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_preview.setMaximumHeight(180)
        prev_layout.addWidget(self.tbl_preview)
        prev_box.setLayout(prev_layout)
        layout.addWidget(prev_box)

        # --- 싱크 옵션 (싱크 선택 시만 활성) ---
        self.sync_box = QGroupBox(self._t("subtools_grp_sync_opts"))
        sync_layout = QVBoxLayout()
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(self._t("subtools_lbl_ref_lang")))
        self.cmb_lang = QComboBox()
        for code in st.SYNC_LANG_CHOICES:
            self.cmb_lang.addItem(code, code)
        self.cmb_lang.setCurrentText("eng")
        row1.addWidget(self.cmb_lang)
        row1.addWidget(QLabel(self._t("subtools_lbl_split")))
        self.spin_split = QSpinBox()
        self.spin_split.setRange(0, 1000)
        self.spin_split.setValue(0)
        self.spin_split.setSpecialValueText(self._t("subtools_split_auto"))
        row1.addWidget(self.spin_split)
        row1.addStretch()
        sync_layout.addLayout(row1)
        row2 = QHBoxLayout()
        self.chk_no_split = QCheckBox(self._t("subtools_chk_no_split"))
        self.chk_force = QCheckBox(self._t("subtools_chk_force"))
        self.chk_backup = QCheckBox(self._t("subtools_chk_backup"))
        self.chk_backup.setChecked(True)
        self.chk_force.toggled.connect(lambda _: self._refresh_preview())
        row2.addWidget(self.chk_no_split)
        row2.addWidget(self.chk_force)
        row2.addWidget(self.chk_backup)
        row2.addStretch()
        sync_layout.addLayout(row2)
        self.sync_box.setLayout(sync_layout)
        layout.addWidget(self.sync_box)

        # --- 진행률 + 로그 ---
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText(self._t("subtools_log_ph"))
        layout.addWidget(self.log_view, 1)

        # --- 버튼 ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_run = QPushButton(self._t("subtools_btn_run"))
        self.btn_run.clicked.connect(self._run)
        self.btn_close = QPushButton(self._t("btn_close"))
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._on_step_changed()

    # -- helpers -------------------------------------------------
    def _t(self, key, **kwargs):
        try:
            return self._parent.tr_str(key, **kwargs)
        except Exception:
            return key

    def _step(self):
        return STEP_SYNC if self.radio_sync.isChecked() else STEP_RENAME

    def _refresh_ilass_status(self):
        path = st.find_ilass()
        if path:
            self.lbl_ilass.setText(self._t("subtools_ilass_found", path=path))
        else:
            self.lbl_ilass.setText(
                self._t("subtools_ilass_missing", url=st.ILASS_HOMEPAGE))

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, self._t("subtools_lbl_folder"))
        if d:
            self.edit_folder.setText(d)
            self._refresh_preview()

    def _on_step_changed(self):
        is_sync = self._step() == STEP_SYNC
        self.sync_box.setEnabled(is_sync)
        self._refresh_ilass_status()
        self._refresh_preview()

    def _refresh_preview(self):
        """폴더를 다시 스캔해 미리보기 테이블 갱신."""
        if self._worker and self._worker.isRunning():
            return
        folder = self.edit_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            self.tbl_preview.setRowCount(0)
            return
        mode = self.cmb_mode.currentData()
        self.tbl_preview.setRowCount(0)

        if self._step() == STEP_RENAME:
            self.tbl_preview.setColumnCount(2)
            self.tbl_preview.setHorizontalHeaderLabels(
                [self._t("subtools_col_before"), self._t("subtools_col_after")])
            try:
                plan, unmatched = st.plan_rename(folder, mode)
            except st.SubtitleToolsError as e:
                self._log(f"[오류] {e}")
                return
            for old, new in plan:
                r = self.tbl_preview.rowCount()
                self.tbl_preview.insertRow(r)
                self.tbl_preview.setItem(
                    r, 0, QTableWidgetItem(os.path.basename(old)))
                self.tbl_preview.setItem(
                    r, 1, QTableWidgetItem(os.path.basename(new)))
            if unmatched:
                r = self.tbl_preview.rowCount()
                self.tbl_preview.insertRow(r)
                self.tbl_preview.setItem(
                    r, 0, QTableWidgetItem(
                        self._t("subtools_unmatched_n", n=len(unmatched))))
                self.tbl_preview.setItem(r, 1, QTableWidgetItem("-"))
            self._log(self._t("subtools_preview_done",
                              n=len(plan), m=len(unmatched)))
        else:
            self.tbl_preview.setColumnCount(3)
            self.tbl_preview.setHorizontalHeaderLabels(
                [self._t("subtools_col_video"), self._t("subtools_col_sub"),
                 self._t("subtools_col_status")])
            pairs, skipped = st.find_pairs(folder)
            force = self.chk_force.isChecked()
            n_skip = 0
            for video, sub, _ext in pairs:
                base, _ = os.path.splitext(video)
                synced = st.already_synced(folder, base, sub)
                status = (self._t("subtools_status_synced") if (synced and not force)
                          else self._t("subtools_status_pending"))
                if synced and not force:
                    n_skip += 1
                r = self.tbl_preview.rowCount()
                self.tbl_preview.insertRow(r)
                self.tbl_preview.setItem(r, 0, QTableWidgetItem(video))
                self.tbl_preview.setItem(r, 1, QTableWidgetItem(sub))
                self.tbl_preview.setItem(r, 2, QTableWidgetItem(status))
            for video in skipped:
                r = self.tbl_preview.rowCount()
                self.tbl_preview.insertRow(r)
                self.tbl_preview.setItem(r, 0, QTableWidgetItem(video))
                self.tbl_preview.setItem(
                    r, 1, QTableWidgetItem(self._t("subtools_no_sub")))
                self.tbl_preview.setItem(r, 2, QTableWidgetItem("-"))
            self._log(self._t("subtools_sync_preview_done",
                              n=len(pairs), s=n_skip, m=len(skipped)))

    def _log(self, msg):
        self.log_view.append(msg)

    def _set_running(self, running):
        for w in (self.btn_run, self.btn_refresh, self.btn_browse,
                  self.edit_folder, self.cmb_mode, self.cmb_lang,
                  self.spin_split, self.radio_rename, self.radio_sync,
                  self.chk_no_split, self.chk_force, self.chk_backup):
            w.setEnabled(not running)
        self.sync_box.setEnabled(not running and self._step() == STEP_SYNC)
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def _run(self):
        folder = self.edit_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, self._t("subtools_dialog_title"),
                                self._t("subtools_invalid_folder"))
            return
        step = self._step()
        if step == STEP_SYNC and not st.find_ilass():
            QMessageBox.warning(
                self, self._t("subtools_dialog_title"),
                self._t("subtools_ilass_missing", url=st.ILASS_HOMEPAGE))
            return

        split_val = self.spin_split.value()
        sync_opts = {
            "lang": self.cmb_lang.currentData(),
            "split_penalty": split_val if split_val > 0 else None,
            "no_split": self.chk_no_split.isChecked(),
            "no_backup": not self.chk_backup.isChecked(),
            "force_resync": self.chk_force.isChecked(),
        }

        self._set_running(True)
        self._worker = SubtitleToolsWorker(
            folder, self.cmb_mode.currentData(), step, sync_opts,
        )
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.error_signal.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.setValue(int(done * 100 / total))

    def _on_finished(self, summary):
        self._set_running(False)
        self._log(self._t("subtools_done"))
        self._refresh_preview()  # 실행 후 결과 반영
        self._worker = None

    def _on_error(self, msg):
        self._set_running(False)
        self._log(f"[오류] {msg}")
        QMessageBox.warning(self, self._t("subtools_dialog_title"), msg)
        self._worker = None
