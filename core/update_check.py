# -*- coding: utf-8 -*-
"""gemini-srt-translator 라이브러리 업데이트 확인 (순수 함수).

라이브러리 내장 `utils.get_latest_pypi_version()`은 타임아웃이 없어
GUI 스레드에서 직접 호출하기 위험하므로, 타임아웃을 적용한 자체 구현을 사용한다.
"""

import json
import urllib.request

PACKAGE_NAME = "gemini-srt-translator"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
REQUEST_TIMEOUT = 10


def get_installed_version():
    """설치된 라이브러리 버전. 없으면 None."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        return version(PACKAGE_NAME)
    except Exception:
        return None


def _parse_version(v_str):
    """'3.8.3' -> (3, 8, 3). 숫자 부분만 비교, pre-release는 None."""
    import re
    v_str = (v_str or "").strip()
    # pre-release/dev 태그가 있으면 stable이 아님
    if re.search(r"(a|b|rc|alpha|beta|dev|post)\d*$", v_str, re.IGNORECASE):
        return None
    parts = []
    for p in v_str.split("."):
        m = re.match(r"(\d+)", p)
        if not m:
            return None
        parts.append(int(m.group(1)))
    return tuple(parts) if parts else None


def fetch_latest_version(timeout=REQUEST_TIMEOUT):
    """PyPI에서 최신 stable 버전 조회. 실패 시 None."""
    try:
        req = urllib.request.Request(
            PYPI_URL, headers={"User-Agent": "GeminiSRTTranslatorGUI"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
        versions = []
        for v_str in data.get("releases", {}):
            v = _parse_version(v_str)
            if v:
                versions.append((v, v_str))
        if versions:
            return max(versions)[1]
    except Exception:
        pass
    return None


def is_newer(latest, installed):
    """latest가 installed보다 새 버전이면 True. 비교 불가 시 False."""
    lv, iv = _parse_version(latest), _parse_version(installed)
    if not lv or not iv:
        return False
    return lv > iv
