# -*- coding: utf-8 -*-
"""Tkinter판 2단계 다이얼로그 — 미리보기 편집·스킬 설치·에이전트 교환·자막 도구.

PyQt판 app/preview_editor.py, app/skill_installer.py,
app/agent_exchange_dialog.py, app/subtitle_tools_dialog.py의 포팅.
비즈니스 로직(core/)은 그대로 공유하고 프레임워크 결합부만 교체했다.
"""

import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app_tk.theme import LISTBOX_STYLE, TEXT_STYLE
from app_tk.widgets import set_enabled
from core.subtitle_io import entry_cps, format_srt, parse_srt

CPS_WARN_THRESHOLD = 20.0  # 초당 글자수 경고 기준 (PyQt판과 동일)


class _DialogBase:
    """Toplevel 공통: tr 위임 + 스레드→UI 큐 디스패치."""

    def _init_dialog(self, root, app, title, geometry):
        self.root = root
        self.app = app
        self.dlg = tk.Toplevel(root)
        self.dlg.title(title)
        self.dlg.geometry(geometry)
        self.dlg.transient(root)
        self.dlg.grab_set()
        self._queue = queue.Queue()
        self.dlg.after(50, self._pump)

    def _t(self, key, **kwargs):
        try:
            return self.app.tr_str(key, **kwargs)
        except Exception:
            return key

    def _call(self, fn):
        """워커 스레드에서 UI 스레드로 호출 예약."""
        self._queue.put(fn)

    def _pump(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        try:
            self.dlg.after(50, self._pump)
        except Exception:
            pass

    def _close(self):
        try:
            self.dlg.grab_release()
        except Exception:
            pass
        self.dlg.destroy()


# ======================================================================
# 번역 결과 미리보기/편집
# ======================================================================
class SubtitlePreviewDialogTk(_DialogBase):
    COLS = ("num", "start", "end", "cps", "trans", "orig")

    def __init__(self, root, app, translated_path, original_path=None):
        self.translated_path = translated_path
        self.original_path = original_path
        self.trans_entries = []
        self.orig_entries = []
        self._dirty = False
        self._view_indices = []
        self._init_dialog(root, app, self._t("preview_title"), "1100x700")
        dlg = self.dlg
        dlg.protocol("WM_DELETE_WINDOW", self._request_close)

        bar = ttk.Frame(dlg)
        bar.pack(fill="x", padx=8, pady=6)
        self.lbl_trans = ttk.Label(bar)
        self.lbl_trans.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text=self._t("preview_open_translated"),
                   command=self._pick_translated).pack(side="left", padx=4)
        self.lbl_orig = ttk.Label(bar)
        self.lbl_orig.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text=self._t("preview_open_original"),
                   command=self._pick_original).pack(side="left", padx=4)

        sbar = ttk.Frame(dlg)
        sbar.pack(fill="x", padx=8, pady=2)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._populate())
        entry = ttk.Entry(sbar, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)
        self.lbl_rows = ttk.Label(sbar)
        self.lbl_rows.pack(side="left", padx=6)

        frame = ttk.Frame(dlg)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(frame, columns=self.COLS, show="headings")
        headings = (
            ("num", "preview_col_num", 50), ("start", "preview_col_start", 110),
            ("end", "preview_col_end", 110), ("cps", "preview_col_cps", 60),
            ("trans", "preview_col_trans", 380), ("orig", "preview_col_orig", 380),
        )
        for col, key, width in headings:
            self.tree.heading(col, text=self._t(key))
            self.tree.column(col, width=width,
                             stretch=col in ("trans", "orig"))
        self.tree.tag_configure("warn", background="#ffd7d7")
        yscroll = ttk.Scrollbar(frame, orient="vertical",
                                command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=6)
        self.btn_save = ttk.Button(row, text=self._t("btn_save"),
                                   command=self._save)
        set_enabled(self.btn_save, False)
        self.btn_save.pack(side="right")
        ttk.Button(row, text=self._t("btn_close"),
                   command=self._request_close).pack(side="right", padx=(0, 6))

        self._reload()

    # -- 데이터 ---------------------------------------------------------
    def _read_entries(self, path):
        if not path or not os.path.isfile(path):
            return []
        if path.lower().endswith(".ass"):
            messagebox.showwarning(
                self._t("preview_title"),
                self._t("preview_ass_unsupported",
                        file=os.path.basename(path)), parent=self.dlg)
            return []
        try:
            with open(path, encoding="utf-8-sig") as f:
                return parse_srt(f.read())
        except Exception as e:
            messagebox.showwarning(self._t("preview_title"), str(e),
                                   parent=self.dlg)
            return []

    def _reload(self):
        self.trans_entries = self._read_entries(self.translated_path)
        self.orig_entries = self._read_entries(self.original_path)
        self._dirty = False
        set_enabled(self.btn_save, False)
        self.lbl_trans.configure(text=self._t(
            "preview_translated_file",
            file=os.path.basename(self.translated_path or "")))
        self.lbl_orig.configure(text=self._t(
            "preview_original_file",
            file=os.path.basename(self.original_path or "")
            if self.original_path else "—"))
        self._populate()

    def _cps_of(self, entry):
        return entry_cps(entry)

    def _populate(self):
        q = self.search_var.get().strip().lower()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._view_indices = []
        for idx, e in enumerate(self.trans_entries):
            orig_text = (self.orig_entries[idx]["text"]
                         if idx < len(self.orig_entries) else "")
            if q and q not in (e["text"] + " " + orig_text).lower():
                continue
            cps = self._cps_of(e)
            cps_text = f"{cps:.1f}" if cps is not None else "—"
            tags = ("warn",) if (cps is not None and cps > CPS_WARN_THRESHOLD) else ()
            self.tree.insert(
                "", "end", iid=str(idx), tags=tags,
                values=(e["index"], e["start"], e["end"], cps_text,
                        e["text"].replace("\n", " ⏎ "),
                        orig_text.replace("\n", " ⏎ ")))
            self._view_indices.append(idx)
        self.lbl_rows.configure(text=self._t(
            "preview_rows", visible=len(self._view_indices),
            total=len(self.trans_entries)))

    # -- 편집/저장 --------------------------------------------------------
    def _on_double_click(self, event):
        if self.tree.identify_column(event.x) != "#5":  # trans 열만
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        idx = int(iid)
        self._edit_entry(idx)

    def _edit_entry(self, idx):
        entry = self.trans_entries[idx]
        dlg = tk.Toplevel(self.dlg)
        dlg.title(self._t("preview_edit_title", num=idx + 1))
        dlg.geometry("600x300")
        dlg.transient(self.dlg)
        dlg.grab_set()
        text = tk.Text(dlg, wrap="word", **TEXT_STYLE)
        text.pack(fill="both", expand=True, padx=8, pady=8)
        text.insert("1.0", entry["text"])
        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=(0, 8))

        def ok():
            new_text = text.get("1.0", "end-1c").strip()
            dlg.destroy()
            if new_text != entry["text"]:
                entry["text"] = new_text
                self._dirty = True
                set_enabled(self.btn_save, True)
                self._populate()

        ttk.Button(row, text="취소", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="확인", command=ok).pack(side="right", padx=(0, 6))

    def _confirm_discard(self):
        if not self._dirty:
            return True
        return messagebox.askyesno(
            self._t("preview_title"), self._t("preview_unsaved_close"),
            parent=self.dlg)

    def _request_close(self):
        if self._confirm_discard():
            self._close()

    def _pick_translated(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.dlg, title=self._t("preview_open_translated"),
            filetypes=[("Subtitles", "*.srt"), ("All Files", "*")])
        if path:
            self.translated_path = path
            self._reload()

    def _pick_original(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.dlg, title=self._t("preview_open_original"),
            filetypes=[("Subtitles", "*.srt"), ("All Files", "*")])
        if path:
            self.original_path = path
            self._reload()

    def _save(self):
        if not self._dirty or not self.translated_path:
            return
        bak = self.translated_path + ".bak"
        tmp = self.translated_path + ".tmp"
        try:
            text = format_srt(self.trans_entries)
            if os.path.isfile(self.translated_path):
                shutil.copy2(self.translated_path, bak)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.translated_path)
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            messagebox.showerror(self._t("preview_title"), str(e),
                                 parent=self.dlg)
            return
        self._dirty = False
        set_enabled(self.btn_save, False)
        messagebox.showinfo(
            self._t("preview_title"),
            self._t("preview_saved", bak=os.path.basename(bak)),
            parent=self.dlg)


# ======================================================================
# AI Agent Skill 설치
# ======================================================================
SKILL_TARGETS = [
    ("claude", "Claude Code", "Claude Code"),
    ("agents", "Cursor / Codex / Cline (범용)", "Cursor / Codex / Cline (generic)"),
    ("antigravity", "Antigravity / Gemini", "Antigravity / Gemini"),
    ("gemini_cli", "Gemini CLI", "Gemini CLI"),
    ("copilot", "Muse", "Muse"),
    ("agy", "agy (Antigravity CLI)", "agy (Antigravity CLI)"),
    ("all", "전체", "All"),
]


def _as_paths(result):
    if result is None:
        return []
    if isinstance(result, (str, os.PathLike)):
        return [str(result)]
    return [str(p) for p in result]


def run_install(target, is_global, folder=None):
    """스킬 설치 실행 (PyQt판 app/skill_installer.py와 동일 로직)."""
    from core.gst_compat import install_skill
    from core.skill_install_extra import EXTRA_TARGET_IDS, install_extra_skill

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


class SkillInstallDialogTk(_DialogBase):
    def __init__(self, root, app):
        self._init_dialog(root, app, self._t("skill_dialog_title"), "560x420")
        dlg = self.dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close)

        plat_box = ttk.LabelFrame(dlg, text=self._t("skill_lbl_platform"))
        plat_box.pack(fill="x", padx=8, pady=6)
        self._target_ids = [t[0] for t in SKILL_TARGETS]
        name_idx = 1 if getattr(app, "app_lang", "ko") == "ko" else 2
        labels = [t[name_idx] for t in SKILL_TARGETS]
        self.cmb_platform = ttk.Combobox(
            plat_box, values=labels, state="readonly")
        self.cmb_platform.pack(fill="x", padx=6, pady=6)
        self.cmb_platform.current(0)

        scope_box = ttk.LabelFrame(dlg, text=self._t("skill_lbl_scope"))
        scope_box.pack(fill="x", padx=8, pady=2)
        self.scope_var = tk.IntVar(value=0)  # 0=전역, 1=프로젝트
        ttk.Radiobutton(scope_box, text=self._t("skill_scope_global"),
                        variable=self.scope_var, value=0,
                        command=self._on_scope_changed).pack(
                            anchor="w", padx=6, pady=2)
        ttk.Radiobutton(scope_box, text=self._t("skill_scope_project"),
                        variable=self.scope_var, value=1,
                        command=self._on_scope_changed).pack(
                            anchor="w", padx=6, pady=2)
        frow = ttk.Frame(scope_box)
        frow.pack(fill="x", padx=6, pady=4)
        self.folder_var = tk.StringVar(value=os.path.expanduser("~"))
        self.edit_folder = ttk.Entry(frow, textvariable=self.folder_var)
        self.edit_folder.pack(side="left", fill="x", expand=True)
        self.btn_browse = ttk.Button(frow, text=self._t("skill_btn_browse"),
                                     command=self._browse_folder)
        self.btn_browse.pack(side="left", padx=(4, 0))
        self._on_scope_changed()

        self.result = tk.Text(dlg, wrap="word", height=8, **TEXT_STYLE)
        self.result.pack(fill="both", expand=True, padx=8, pady=6)

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_install = ttk.Button(row, text=self._t("skill_btn_install"),
                                      command=self._do_install)
        self.btn_install.pack(side="right")
        ttk.Button(row, text=self._t("btn_close"),
                   command=self._close).pack(side="right", padx=(0, 6))

        from core.gst_compat import install_skill
        from core.skill_install_extra import load_skill_content
        if install_skill is None and load_skill_content() is None:
            set_enabled(self.btn_install, False)
            self._set_result(self._t("skill_no_library"))

    def _set_result(self, text):
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)

    def _on_scope_changed(self):
        is_project = self.scope_var.get() == 1
        set_enabled(self.edit_folder, is_project)
        set_enabled(self.btn_browse, is_project)

    def _browse_folder(self):
        d = filedialog.askdirectory(
            parent=self.dlg, title=self._t("skill_pick_folder"),
            initialdir=self.folder_var.get())
        if d:
            self.folder_var.set(d)

    def _do_install(self):
        idx = self.cmb_platform.current()
        target = self._target_ids[idx] if idx >= 0 else "claude"
        is_global = self.scope_var.get() == 0
        folder = None
        if not is_global:
            folder = self.folder_var.get().strip()
            if not folder or not os.path.isdir(folder):
                messagebox.showwarning(
                    self._t("skill_dialog_title"),
                    self._t("skill_invalid_folder"), parent=self.dlg)
                return
        try:
            paths, errors = run_install(target, is_global, folder)
        except Exception as e:
            self._set_result(self._t("skill_install_failed", err=str(e)))
            return
        lines = []
        if paths:
            lines.append(self._t("skill_installed", paths="\n".join(paths)))
        elif not errors:
            lines.append(self._t("skill_install_empty"))
        for err in errors:
            lines.append(self._t("skill_install_failed", err=err))
        self._set_result("\n\n".join(lines))


# ======================================================================
# 에이전트 파일 교환
# ======================================================================
class AgentExchangeDialogTk(_DialogBase):
    def __init__(self, root, app):
        from core import agent_bridge
        self._bridge = agent_bridge
        self._init_dialog(root, app, self._t("agent_dialog_title"), "600x480")
        dlg = self.dlg
        dlg.protocol("WM_DELETE_WINDOW", self._close)

        in_box = ttk.LabelFrame(dlg, text=self._t("agent_grp_input"))
        in_box.pack(fill="x", padx=8, pady=6)
        row = ttk.Frame(in_box)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text=self._t("agent_lbl_file")).pack(side="left")
        self.file_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.file_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text=self._t("agent_btn_browse"),
                   command=self._browse_file).pack(side="left")
        row = ttk.Frame(in_box)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=self._t("agent_lbl_language")).pack(side="left")
        self.lang_var = tk.StringVar(value="Korean")
        ttk.Entry(row, textvariable=self.lang_var, width=16).pack(
            side="left", padx=4)
        ttk.Label(row, text=self._t("agent_lbl_batch")).pack(
            side="left", padx=(10, 2))
        self.batch_var = tk.IntVar(value=agent_bridge.DEFAULT_BATCH_SIZE)
        ttk.Spinbox(row, from_=10, to=300, textvariable=self.batch_var,
                    width=7).pack(side="left")
        row = ttk.Frame(in_box)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text=self._t("agent_lbl_style")).pack(side="left")
        from core.style_presets import all_presets
        lang = getattr(app, "app_lang", "ko")
        custom = getattr(app, "custom_presets", None)
        name_key = "name_ko" if lang == "ko" else "name_en"
        self._style_ids = []
        labels = []
        for p in all_presets(custom, lang):
            labels.append(p.get(name_key) or p["id"])
            self._style_ids.append(p["id"])
        self.cmb_style = ttk.Combobox(row, values=labels, state="readonly")
        self.cmb_style.pack(side="left", fill="x", expand=True, padx=4)
        if labels:
            self.cmb_style.current(0)
        self._prefill()

        act = ttk.Frame(dlg)
        act.pack(fill="x", padx=8, pady=2)
        self.btn_export = ttk.Button(act, text=self._t("agent_btn_export"),
                                     command=self._do_export)
        self.btn_import = ttk.Button(act, text=self._t("agent_btn_import"),
                                     command=self._do_import)
        self.btn_status = ttk.Button(act, text=self._t("agent_btn_status"),
                                     command=self._do_status)
        self.btn_reset = ttk.Button(act, text=self._t("agent_btn_reset"),
                                    command=self._do_reset)
        for b in (self.btn_export, self.btn_import, self.btn_status,
                  self.btn_reset):
            b.pack(side="left", padx=(0, 4))

        self.result = tk.Text(dlg, wrap="word", **TEXT_STYLE)
        self.result.pack(fill="both", expand=True, padx=8, pady=6)

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(row, text=self._t("btn_close"),
                   command=self._close).pack(side="right")

        if agent_bridge.SubtitleSession is None:
            for b in (self.btn_export, self.btn_import, self.btn_status,
                      self.btn_reset):
                set_enabled(b, False)
            self._set_result(self._t("agent_no_library"))

    def _set_result(self, text):
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)

    def _prefill(self):
        app = self.app
        try:
            for f in getattr(app, "input_files", None) or []:
                if f.lower().endswith((".srt", ".ass")):
                    self.file_var.set(f)
                    break
        except Exception:
            pass
        try:
            checked = app.cmb_langs.checked_items()
            if checked:
                self.lang_var.set(checked[0])
        except Exception:
            pass
        try:
            pid = app._current_style_id()
            if pid in self._style_ids:
                self.cmb_style.current(self._style_ids.index(pid))
        except Exception:
            pass

    def _browse_file(self):
        path = filedialog.askopenfilename(
            parent=self.dlg, title=self._t("agent_pick_input"),
            initialdir=os.path.dirname(self.file_var.get()) or None,
            filetypes=[("Subtitle", "*.srt *.ass"), ("All Files", "*")])
        if path:
            self.file_var.set(path)

    def _input_file(self):
        path = self.file_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning(
                self._t("agent_dialog_title"),
                self._t("agent_invalid_input"), parent=self.dlg)
            return None
        return path

    def _style_instruction(self):
        from core.style_presets import preset_instruction
        idx = self.cmb_style.current()
        pid = self._style_ids[idx] if idx >= 0 else None
        custom = getattr(self.app, "custom_presets", None)
        try:
            return preset_instruction(pid, custom) or ""
        except Exception:
            return ""

    def _progress_text(self, status):
        return (f"{status.get('completed_lines', 0)}/"
                f"{status.get('total_lines', 0)} "
                f"({status.get('progress_percent', 0)}%)")

    def _show_ready(self, key, result):
        status = result.get("status") or {}
        lines = [self._t(key, path=result.get("batch_file", ""))]
        inst = result.get("instructions_file")
        if inst:
            lines.append(inst)
        lines.append(self._progress_text(status))
        self._set_result("\n".join(lines))

    def _show_completed(self, result):
        self._set_result(self._t(
            "agent_completed", path=result.get("output_file", "")))

    def _batch(self):
        try:
            return max(10, min(300, int(self.batch_var.get())))
        except Exception:
            return self._bridge.DEFAULT_BATCH_SIZE

    def _do_export(self):
        path = self._input_file()
        if not path:
            return
        lang = self.lang_var.get().strip() or "Korean"
        try:
            result = self._bridge.start_exchange(
                path, lang, batch_size=self._batch(),
                style_instruction=self._style_instruction())
        except Exception as e:
            self._set_result(self._t("agent_failed", err=str(e)))
            return
        if result["state"] == "completed":
            self._show_completed(result)
        else:
            self._show_ready("agent_export_done", result)

    def _do_import(self):
        path = self._input_file()
        if not path:
            return
        start_dir = self._bridge.exchange_dir_for(path)
        translated = filedialog.askopenfilename(
            parent=self.dlg, title=self._t("agent_pick_translated"),
            initialdir=start_dir if os.path.isdir(start_dir) else None,
            filetypes=[("JSON", "*.json"), ("All Files", "*")])
        if not translated:
            return
        try:
            result = self._bridge.commit_exchange(
                path, translated, batch_size=self._batch())
        except Exception as e:
            self._set_result(self._t("agent_failed", err=str(e)))
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
            result = self._bridge.exchange_status(
                path, batch_size=self._batch())
        except Exception as e:
            self._set_result(self._t("agent_failed", err=str(e)))
            return
        if result["state"] == "completed":
            self._show_completed(result)
        else:
            status = result.get("status") or {}
            self._set_result(self._t(
                "agent_status", progress=self._progress_text(status),
                path=result.get("batch_file", "")))

    def _do_reset(self):
        path = self._input_file()
        if not path:
            return
        if not messagebox.askyesno(
                self._t("agent_dialog_title"),
                self._t("agent_reset_confirm"), parent=self.dlg):
            return
        try:
            self._bridge.reset_exchange(path)
        except Exception as e:
            self._set_result(self._t("agent_failed", err=str(e)))
            return
        self._set_result(self._t("agent_reset_done"))


# ======================================================================
# 자막 정리 도구 (리네임 / ilass 싱크)
# ======================================================================
STEP_RENAME, STEP_SYNC, STEP_BOTH = "rename", "sync", "both"


class SubtitleToolsDialogTk(_DialogBase):
    def __init__(self, root, app):
        from core import subtitle_tools as st
        self._st = st
        self._worker = None
        self._dl_worker = None
        self._init_dialog(root, app, self._t("subtools_dialog_title"),
                          "720x640")
        dlg = self.dlg
        dlg.protocol("WM_DELETE_WINDOW", self._request_close)

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text=self._t("subtools_lbl_folder")).pack(side="left")
        self.folder_var = tk.StringVar()
        self.edit_folder = ttk.Entry(row, textvariable=self.folder_var)
        self.edit_folder.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_browse = ttk.Button(row, text=self._t("subtools_btn_browse"),
                                     command=self._browse_folder)
        self.btn_browse.pack(side="left")
        self.btn_refresh = ttk.Button(
            row, text=self._t("subtools_btn_refresh"),
            command=self._refresh_preview)
        self.btn_refresh.pack(side="left", padx=(4, 0))

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text=self._t("subtools_lbl_mode")).pack(side="left")
        self._mode_ids = ["tv", "movie"]
        self.cmb_mode = ttk.Combobox(
            row, values=[self._t("subtools_mode_tv"),
                         self._t("subtools_mode_movie")],
            state="readonly", width=10)
        self.cmb_mode.pack(side="left", padx=4)
        self.cmb_mode.current(0)
        self.cmb_mode.bind("<<ComboboxSelected>>",
                           lambda e: self._refresh_preview())
        ttk.Label(row, text=self._t("subtools_lbl_step")).pack(
            side="left", padx=(12, 2))
        self.step_var = tk.IntVar(value=0)  # 0 rename, 1 sync, 2 both
        for val, key in ((0, "subtools_radio_rename"),
                         (1, "subtools_radio_sync"),
                         (2, "subtools_radio_both")):
            ttk.Radiobutton(row, text=self._t(key), variable=self.step_var,
                            value=val,
                            command=self._on_step_changed).pack(side="left")

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=2)
        self.lbl_ilass = ttk.Label(row)
        self.lbl_ilass.pack(side="left", fill="x", expand=True)
        self.btn_ilass_dl = ttk.Button(
            row, text=self._t("subtools_btn_ilass_dl"),
            command=self._download_ilass)
        self.btn_ilass_dl.pack(side="left")
        self._refresh_ilass_status()

        prev_box = ttk.LabelFrame(dlg, text=self._t("subtools_grp_preview"))
        prev_box.pack(fill="x", padx=8, pady=4)
        self.tree = ttk.Treeview(prev_box, columns=("c1", "c2"),
                                 show="headings", height=7)
        self.tree.pack(fill="x", padx=4, pady=4)

        self.sync_box = ttk.LabelFrame(dlg,
                                       text=self._t("subtools_grp_sync_opts"))
        self.sync_box.pack(fill="x", padx=8, pady=2)
        row = ttk.Frame(self.sync_box)
        row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text=self._t("subtools_lbl_ref_lang")).pack(side="left")
        self.cmb_lang = ttk.Combobox(row, values=list(st.SYNC_LANG_CHOICES),
                                     state="readonly", width=8)
        self.cmb_lang.pack(side="left", padx=4)
        if "eng" in list(st.SYNC_LANG_CHOICES):
            self.cmb_lang.set("eng")
        ttk.Label(row, text=self._t("subtools_lbl_split")).pack(
            side="left", padx=(12, 2))
        self.split_var = tk.IntVar(value=0)
        self.spin_split = ttk.Spinbox(row, from_=0, to=1000,
                                      textvariable=self.split_var, width=7)
        self.spin_split.pack(side="left")
        ttk.Label(row, text="(0 = " + self._t("subtools_split_auto") + ")").pack(
            side="left", padx=4)
        row = ttk.Frame(self.sync_box)
        row.pack(fill="x", padx=6, pady=3)
        self.no_split_var = tk.BooleanVar(value=False)
        self.force_var = tk.BooleanVar(value=False)
        self.backup_var = tk.BooleanVar(value=True)
        self.chk_no_split = ttk.Checkbutton(
            row, text=self._t("subtools_chk_no_split"),
            variable=self.no_split_var)
        self.chk_no_split.pack(side="left")
        self.chk_force = ttk.Checkbutton(
            row, text=self._t("subtools_chk_force"), variable=self.force_var,
            command=self._refresh_preview)
        self.chk_force.pack(side="left", padx=8)
        self.chk_backup = ttk.Checkbutton(
            row, text=self._t("subtools_chk_backup"),
            variable=self.backup_var)
        self.chk_backup.pack(side="left")
        self._sync_widgets = [self.cmb_lang, self.spin_split,
                              self.chk_no_split, self.chk_force,
                              self.chk_backup]

        self.progress = ttk.Progressbar(dlg, maximum=100)
        self.log = tk.Text(dlg, wrap="word", **TEXT_STYLE)
        self.log.pack(fill="both", expand=True, padx=8, pady=6)

        row = ttk.Frame(dlg)
        row.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_run = ttk.Button(row, text=self._t("subtools_btn_run"),
                                  command=self._run)
        self.btn_run.pack(side="right")
        self.btn_close = ttk.Button(row, text=self._t("btn_close"),
                                    command=self._request_close)
        self.btn_close.pack(side="right", padx=(0, 6))
        self._on_step_changed()

    # -- 상태 -------------------------------------------------------------
    def _step(self):
        return (STEP_RENAME, STEP_SYNC, STEP_BOTH)[self.step_var.get()]

    def _uses_sync(self):
        return self._step() in (STEP_SYNC, STEP_BOTH)

    def _mode(self):
        idx = self.cmb_mode.current()
        return self._mode_ids[idx] if idx >= 0 else "tv"

    def _log(self, msg):
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")

    def _refresh_ilass_status(self):
        st = self._st
        path = st.find_ilass()
        if path:
            self.lbl_ilass.configure(
                text=self._t("subtools_ilass_found", path=path))
            self.btn_ilass_dl.pack_forget()
        else:
            self.lbl_ilass.configure(text=self._t(
                "subtools_ilass_missing", url=st.ILASS_HOMEPAGE))
            from get_ilass import platform_asset
            url, _fmt, _bin = platform_asset()
            if url is not None:
                self.btn_ilass_dl.pack(side="left")
            else:
                self.btn_ilass_dl.pack_forget()

    def _ilass_dest_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _download_ilass(self):
        set_enabled(self.btn_ilass_dl, False)
        self._log(self._t("subtools_ilass_dl_start"))
        dest = self._ilass_dest_dir()

        def work():
            try:
                from get_ilass import download_ilass
                path = download_ilass(
                    dest, log=lambda m: self._call(lambda: self._log(m)))
                self._call(lambda: self._on_ilass_dl_done(path))
            except Exception as e:
                self._call(lambda: self._on_ilass_dl_error(str(e)))

        self._dl_worker = threading.Thread(target=work, daemon=True)
        self._dl_worker.start()

    def _on_ilass_dl_done(self, path):
        self._log(self._t("subtools_ilass_dl_done", path=path))
        set_enabled(self.btn_ilass_dl, True)
        self._refresh_ilass_status()
        self._dl_worker = None

    def _on_ilass_dl_error(self, msg):
        self._log(f"[오류] {msg}")
        messagebox.showwarning(self._t("subtools_dialog_title"), msg,
                               parent=self.dlg)
        set_enabled(self.btn_ilass_dl, True)
        self._dl_worker = None

    # -- 미리보기 -----------------------------------------------------------
    def _browse_folder(self):
        d = filedialog.askdirectory(
            parent=self.dlg, title=self._t("subtools_lbl_folder"))
        if d:
            self.folder_var.set(d)
            self._refresh_preview()

    def _on_step_changed(self):
        for w in self._sync_widgets:
            set_enabled(w, self._uses_sync())
        self._refresh_ilass_status()
        self._refresh_preview()

    def _set_preview_columns(self, cols):
        self.tree.configure(columns=tuple(f"c{i+1}" for i in range(len(cols))))
        for i, title in enumerate(cols):
            self.tree.heading(f"c{i+1}", text=title)
            self.tree.column(f"c{i+1}", stretch=True)

    def _refresh_preview(self):
        if self._worker is not None and self._worker.is_alive():
            return
        st = self._st
        folder = self.folder_var.get().strip()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if not folder or not os.path.isdir(folder):
            return
        if self._step() in (STEP_RENAME, STEP_BOTH):
            self._set_preview_columns(
                [self._t("subtools_col_before"), self._t("subtools_col_after")])
            try:
                plan, unmatched = st.plan_rename(folder, self._mode())
            except st.SubtitleToolsError as e:
                self._log(f"[오류] {e}")
                return
            for old, new in plan:
                self.tree.insert("", "end", values=(
                    os.path.basename(old), os.path.basename(new)))
            if unmatched:
                self.tree.insert("", "end", values=(
                    self._t("subtools_unmatched_n", n=len(unmatched)), "-"))
            self._log(self._t("subtools_preview_done",
                              n=len(plan), m=len(unmatched)))
        else:
            self._set_preview_columns(
                [self._t("subtools_col_video"), self._t("subtools_col_sub"),
                 self._t("subtools_col_status")])
            pairs, skipped = st.find_pairs(folder)
            force = self.force_var.get()
            n_skip = 0
            for video, sub, _ext in pairs:
                base, _ = os.path.splitext(video)
                synced = st.already_synced(folder, base, sub)
                status = (self._t("subtools_status_synced")
                          if (synced and not force)
                          else self._t("subtools_status_pending"))
                if synced and not force:
                    n_skip += 1
                self.tree.insert("", "end", values=(video, sub, status))
            for video in skipped:
                self.tree.insert("", "end", values=(
                    video, self._t("subtools_no_sub"), "-"))
            self._log(self._t("subtools_sync_preview_done",
                              n=len(pairs), s=n_skip, m=len(skipped)))

    # -- 실행 ---------------------------------------------------------------
    def _worker_running(self):
        if self._worker is not None and self._worker.is_alive():
            return True
        return self._dl_worker is not None and self._dl_worker.is_alive()

    def _request_close(self):
        if self._worker_running():
            messagebox.showwarning(
                self._t("subtools_dialog_title"),
                self._t("subtools_running_close"), parent=self.dlg)
            return
        self._close()

    def _set_running(self, running):
        widgets = [self.btn_run, self.btn_refresh, self.btn_browse,
                   self.btn_ilass_dl, self.btn_close, self.edit_folder,
                   self.cmb_mode, self.cmb_lang, self.spin_split]
        for w in widgets:
            set_enabled(w, not running)
        for w in self._sync_widgets:
            set_enabled(w, not running and self._uses_sync())
        if running:
            self.progress.pack(fill="x", padx=8, pady=2, before=self.log)
            self.progress.configure(value=0)
        else:
            self.progress.pack_forget()

    def _run(self):
        st = self._st
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                self._t("subtools_dialog_title"),
                self._t("subtools_invalid_folder"), parent=self.dlg)
            return
        step = self._step()
        if self._uses_sync() and not st.find_ilass():
            messagebox.showwarning(
                self._t("subtools_dialog_title"),
                self._t("subtools_ilass_missing", url=st.ILASS_HOMEPAGE),
                parent=self.dlg)
            return
        split_val = self.split_var.get() if str(
            self.split_var.get()).isdigit() else 0
        sync_opts = {
            "lang": self.cmb_lang.get() or "eng",
            "split_penalty": split_val if split_val > 0 else None,
            "no_split": self.no_split_var.get(),
            "no_backup": not self.backup_var.get(),
            "force_resync": self.force_var.get(),
        }
        mode = self._mode()
        self._set_running(True)

        def work():
            try:
                summary = {}
                if step in (STEP_RENAME, STEP_BOTH):
                    self._call(lambda: self._log("=== 자막 리네임 시작 ==="))
                    plan, unmatched = st.plan_rename(folder, mode)
                    if not plan:
                        self._call(lambda: self._log("리네임 대상이 없습니다."))
                    applied, skipped = st.apply_rename(
                        plan, log=lambda m: self._call(
                            lambda m=m: self._log(m)))
                    for u in unmatched:
                        self._call(lambda u=u: self._log(
                            f"[매칭 실패] {u} (수동 확인 필요)"))
                    summary["rename"] = {
                        "applied": applied, "skipped": skipped,
                        "unmatched": len(unmatched)}
                    self._call(lambda: self._log(
                        f"리네임 완료: 적용 {applied} / 건너뜀 {skipped} / "
                        f"매칭실패 {len(unmatched)}"))
                if step in (STEP_SYNC, STEP_BOTH):
                    self._call(lambda: self._log("=== ilass 자막 싱크 시작 ==="))
                    summary["sync"] = st.run_sync(
                        folder,
                        log=lambda m: self._call(lambda m=m: self._log(m)),
                        progress=lambda d, t: self._call(
                            lambda d=d, t=t: self._on_progress(d, t)),
                        **sync_opts)
                self._call(lambda: self._on_finished(summary))
            except st.SubtitleToolsError as e:
                self._call(lambda e=e: self._on_error(str(e)))
            except Exception as e:  # noqa: BLE001
                self._call(lambda e=e: self._on_error(f"예상치 못한 오류: {e}"))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.configure(value=int(done * 100 / total))

    def _on_finished(self, summary):
        self._set_running(False)
        self._log(self._t("subtools_done"))
        self._worker = None
        self._refresh_preview()

    def _on_error(self, msg):
        self._set_running(False)
        self._log(f"[오류] {msg}")
        messagebox.showwarning(self._t("subtools_dialog_title"), msg,
                               parent=self.dlg)
        self._worker = None
