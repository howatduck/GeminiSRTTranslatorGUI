# -*- coding: utf-8 -*-
"""ilass.exe 다운로드 스크립트 (Windows 빌드용).

ilass(SandroHc/ilass, AGPL-3.0)의 Windows 릴리즈 zip에서 ilass.exe만
추출해 프로젝트 루트에 둔다. PyInstaller spec이 자동으로 번들에 포함한다.

사용법:
    python get_ilass.py [--version 2.1.0]
"""

import os
import sys
import urllib.request
import zipfile

ILASS_VERSION = "2.1.0"
ILASS_URL = (
    "https://github.com/SandroHc/ilass/releases/download/"
    "v{ver}/ilass-{ver}-win-x86_64.zip"
)
TARGET = "ilass.exe"


def main(argv):
    version = ILASS_VERSION
    if "--version" in argv:
        version = argv[argv.index("--version") + 1]

    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), TARGET)
    if os.path.exists(dest):
        print(f"ilass.exe가 이미 있습니다: {dest}")
        return 0

    url = ILASS_URL.format(ver=version)
    print(f"ilass v{version} 다운로드 중: {url}")
    zip_path = dest + ".zip"
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            exe_name = next(
                (n for n in names if n.lower().endswith("ilass.exe")), None
            )
            if exe_name is None:
                print(f"[오류] zip 안에 ilass.exe가 없습니다: {names}")
                return 1
            with zf.open(exe_name) as src, open(dest, "wb") as out:
                out.write(src.read())
        print(f"ilass.exe 저장 완료: {dest} ({os.path.getsize(dest)} bytes)")
        print("라이선스: AGPL-3.0 — https://github.com/SandroHc/ilass")
        return 0
    except Exception as e:
        print(f"[오류] ilass 다운로드 실패: {e}")
        return 1
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
