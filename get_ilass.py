# -*- coding: utf-8 -*-
"""ilass 실행 파일 다운로드 (빌드용 + 앱 내 원클릭 설치용).

ilass(SandroHc/ilass, AGPL-3.0)의 GitHub 릴리즈에서 현재 플랫폼에 맞는
바이너리만 추출해 둔다. PyInstaller spec이 자동으로 번들에 포함한다.

사용법:
    python get_ilass.py [--version 2.1.0] [--dest DIR]

라이브러리:
    from get_ilass import download_ilass, platform_asset
"""

import os
import stat
import sys
import tarfile
import urllib.request
import zipfile

ILASS_VERSION = "2.1.0"
ILASS_HOMEPAGE = "https://github.com/SandroHc/ilass"
RELEASE_BASE = ILASS_HOMEPAGE + "/releases/download/v{ver}"


def platform_asset(version=ILASS_VERSION):
    """현재 플랫폼에 맞는 (에셋 파일명, 압축 형식, 바이너리 이름) 반환.

    지원하지 않는 플랫폼이면 (None, None, None).
    """
    base = RELEASE_BASE.format(ver=version)
    if sys.platform == "win32":
        name = f"ilass-{version}-win-x86_64.zip"
        return f"{base}/{name}", "zip", "ilass.exe"
    if sys.platform.startswith("linux"):
        name = f"ilass-{version}-linux-x86_64.tar.gz"
        return f"{base}/{name}", "tar.gz", "ilass"
    return None, None, None


def download_ilass(dest_dir=None, version=ILASS_VERSION, log=None):
    """ilass 바이너리를 다운로드해 dest_dir에 둔다. 반환: 바이너리 경로.

    이미 있으면 다운로드 없이 기존 경로 반환.
    지원하지 않는 플랫폼이면 RuntimeError 발생.
    """
    log = log or (lambda msg: None)
    url, fmt, bin_name = platform_asset(version)
    if url is None:
        raise RuntimeError(
            f"이 플랫폼({sys.platform})용 ilass 빌드가 없습니다. "
            f"{ILASS_HOMEPAGE} 참고"
        )

    dest_dir = dest_dir or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, bin_name)
    if os.path.isfile(dest):
        log(f"ilass가 이미 있습니다: {dest}")
        return dest

    log(f"ilass v{version} 다운로드 중: {url}")
    archive = dest + (".zip" if fmt == "zip" else ".tar.gz")
    try:
        urllib.request.urlretrieve(url, archive)
        if fmt == "zip":
            with zipfile.ZipFile(archive) as zf:
                member = next(
                    (n for n in zf.namelist()
                     if n.lower().endswith(bin_name.lower())), None
                )
                if member is None:
                    raise RuntimeError("zip 안에 ilass 바이너리가 없습니다.")
                with zf.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())
        else:
            with tarfile.open(archive, "r:gz") as tf:
                member = next(
                    (m for m in tf.getmembers()
                     if os.path.basename(m.name).lower() == bin_name.lower()),
                    None,
                )
                if member is None:
                    raise RuntimeError("tar.gz 안에 ilass 바이너리가 없습니다.")
                with tf.extractfile(member) as src, open(dest, "wb") as out:
                    out.write(src.read())

        if bin_name == "ilass":  # Linux: 실행 권한
            os.chmod(dest, os.stat(dest).st_mode
                     | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        log(f"ilass 저장 완료: {dest} ({os.path.getsize(dest)} bytes)")
        log("라이선스: AGPL-3.0 — " + ILASS_HOMEPAGE)
        return dest
    finally:
        if os.path.exists(archive):
            os.remove(archive)


def _safe_print(msg):
    """Windows CI(cp1252 stdout)에서도 죽지 않는 출력."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(str(msg).encode("ascii", "replace").decode("ascii"))


def main(argv):
    version = ILASS_VERSION
    dest_dir = None
    if "--version" in argv:
        version = argv[argv.index("--version") + 1]
    if "--dest" in argv:
        dest_dir = argv[argv.index("--dest") + 1]
    try:
        download_ilass(dest_dir, version, log=_safe_print)
        return 0
    except Exception as e:
        _safe_print(f"[ERROR] ilass download failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
