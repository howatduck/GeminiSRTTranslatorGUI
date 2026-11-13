# -*- coding: utf-8 -*-
"""Tkinter판 설정 저장소 — QSettings 대체 (JSON 파일 + 기존 설정 마이그레이션).

PyQt판은 QSettings(윈도우 레지스트리 / 리눅스 ~/.config ini)에 설정을
저장한다. Tkinter판은 같은 키·기본값을 JSON 파일에 저장하고, 파일이
없을 때 한 번만 기존 QSettings 저장소에서 값을 읽어와 이전한다
(PyQt6가 있으면 QSettings로 정확히, 없으면 ini/레지스트리 직접 파싱).

인터페이스는 QSettings의 value()/setValue()와 호환되게 맞췄다.
"""

import configparser
import json
import os
import sys


def default_settings_path(org, app):
    """플랫폼별 설정 파일 경로."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, org, f"{app}.json")
    if sys.platform == "darwin":
        return os.path.expanduser(
            os.path.join("~", "Library", "Preferences", org, f"{app}.json"))
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, org, f"{app}.json")


def _cast(value, default, type_):
    """QSettings의 type= 캐스팅과 같은 규칙으로 변환한다."""
    if type_ is None:
        return value
    try:
        if type_ is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in ("true", "1", "yes", "on")
        if type_ is int:
            return int(float(value)) if isinstance(value, str) else int(value)
        if type_ is float:
            return float(value)
        if type_ is str:
            return "" if value is None else str(value)
    except (TypeError, ValueError):
        return default
    return value


def _read_qsettings_via_pyqt(org, app):
    """PyQt6가 설치돼 있으면 QSettings에서 그대로 읽는다 (가장 정확)."""
    try:
        from PyQt6.QtCore import QSettings
    except Exception:
        return None
    try:
        qs = QSettings(org, app)
        data = {}
        for key in qs.allKeys():
            data[key] = qs.value(key)
        return data
    except Exception:
        return None


def _read_qsettings_ini(org, app):
    """리눅스/맥: ~/.config/<org>/<app>.conf 를 직접 파싱 (best effort)."""
    if sys.platform.startswith("win"):
        return None
    path = os.path.expanduser(os.path.join("~", ".config", org, f"{app}.conf"))
    if not os.path.isfile(path):
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return None
    data = {}
    for section in parser.sections():
        for key, val in parser.items(section):
            # QSettings는 그룹을 'group/key'로 평탄화한다
            data[key if section == "General" else f"{section}/{key}"] = val
    return data


def _read_qsettings_registry(org, app):
    """윈도우: HKCU\\Software\\<org>\\<app> 레지스트리를 직접 읽는다."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except Exception:
        return None
    data = {}
    try:
        root = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, os.path.join("Software", org, app))
    except OSError:
        return None
    try:
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(root, i)
            except OSError:
                break
            data[name.replace("\\", "/")] = val
            i += 1
    finally:
        winreg.CloseKey(root)
    return data


def migrate_qsettings(org, app):
    """기존 QSettings 저장소에서 설정을 읽어온다. 실패하면 빈 dict."""
    for reader in (_read_qsettings_via_pyqt, _read_qsettings_ini,
                   _read_qsettings_registry):
        try:
            data = reader(org, app)
        except Exception:
            data = None
        if data:
            return dict(data)
    return {}


class JsonSettings:
    """QSettings 호환 인터페이스를 가진 JSON 설정 저장소."""

    def __init__(self, org, app, path=None):
        self._org = org
        self._app = app
        self._path = path or default_settings_path(org, app)
        self._data = {}
        if os.path.isfile(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data = loaded
            except (OSError, ValueError):
                self._data = {}
        else:
            # 첫 실행: 기존(PyQt판) 설정을 한 번만 이전한다
            self._data = migrate_qsettings(org, app)
            if self._data:
                self.sync()

    # -- QSettings 호환 API -------------------------------------------------
    def value(self, key, default=None, type=None):
        if key not in self._data:
            return _cast(default, default, type) if type is not None else default
        return _cast(self._data[key], default, type)

    def setValue(self, key, val):
        self._data[key] = val
        self.sync()

    def contains(self, key):
        return key in self._data

    def remove(self, key):
        if key in self._data:
            del self._data[key]
            self.sync()

    def allKeys(self):
        return list(self._data.keys())

    def sync(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except OSError:
            pass

    @property
    def path(self):
        return self._path
