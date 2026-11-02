# -*- coding: utf-8 -*-
"""get_ilass.py 테스트."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import get_ilass
from get_ilass import download_ilass, platform_asset


def test_platform_asset_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    url, fmt, bin_name = platform_asset()
    assert fmt == "tar.gz"
    assert bin_name == "ilass"
    assert "linux-x86_64" in url
    assert url.startswith("https://github.com/SandroHc/ilass/releases/download/")


def test_platform_asset_win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    url, fmt, bin_name = platform_asset()
    assert fmt == "zip"
    assert bin_name == "ilass.exe"
    assert "win-x86_64" in url


def test_platform_asset_unsupported(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform_asset() == (None, None, None)


def test_download_existing_no_network(tmp_path):
    # 이미 있으면 네트워크 없이 기존 경로 반환
    dest = tmp_path / "ilass"
    dest.write_bytes(b"fake")
    assert download_ilass(str(tmp_path), log=lambda m: None) == str(dest)


def test_download_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(RuntimeError):
        download_ilass(str(tmp_path), log=lambda m: None)


def _make_tar_gz(path, symlink=False):
    """ilass 멤버가 일반 파일 또는 심볼릭 링크인 tar.gz를 만든다."""
    import tarfile
    import io

    with tarfile.open(path, "w:gz") as tf:
        if symlink:
            info = tarfile.TarInfo("ilass")
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            tf.addfile(info)
            data = b"target-data"
            target = tarfile.TarInfo("target")
            target.size = len(data)
            tf.addfile(target, io.BytesIO(data))
        else:
            data = b"fake-ilass-binary"
            info = tarfile.TarInfo("ilass")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_download_tar_symlink_member_rejected(tmp_path, monkeypatch):
    """tar.gz 안 ilass가 심볼릭 링크면 명확한 RuntimeError로 거부한다."""
    import shutil
    import urllib.request

    src = tmp_path / "src.tar.gz"
    _make_tar_gz(str(src), symlink=True)
    monkeypatch.setattr(
        urllib.request, "urlretrieve",
        lambda url, filename: shutil.copy(str(src), filename))
    with pytest.raises(RuntimeError, match="유효한 ilass 바이너리"):
        download_ilass(str(tmp_path), log=lambda m: None)


def test_download_tar_regular_member_ok(tmp_path, monkeypatch):
    """일반 파일 멤버는 그대로 추출되고 실행 권한이 붙는다."""
    import shutil
    import urllib.request

    src = tmp_path / "src.tar.gz"
    _make_tar_gz(str(src), symlink=False)
    monkeypatch.setattr(
        urllib.request, "urlretrieve",
        lambda url, filename: shutil.copy(str(src), filename))
    dest = download_ilass(str(tmp_path), log=lambda m: None)
    assert open(dest, "rb").read() == b"fake-ilass-binary"
    assert os.access(dest, os.X_OK)


def test_find_ilass_prefers_project_root(tmp_path, monkeypatch):
    # 프로젝트 루트에 ilass가 있으면 PATH보다 먼저 찾음
    from core import subtitle_tools as st

    fake_core_dir = tmp_path / "proj" / "core"
    fake_core_dir.mkdir(parents=True)
    (tmp_path / "proj" / "ilass").write_bytes(b"fake")

    real_abspath = os.path.abspath
    monkeypatch.setattr(
        st.os.path, "abspath",
        lambda p: (str(fake_core_dir / "subtitle_tools.py")
                   if p == st.__file__ else real_abspath(p)),
    )
    monkeypatch.setattr(st.shutil, "which", lambda _: None)
    assert st.find_ilass() == str(tmp_path / "proj" / "ilass")
