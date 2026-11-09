# -*- coding: utf-8 -*-
"""EXAONE 전수 리뷰(2026-11-09) 지적 M-01·m-07·m-08 수정 회귀 테스트.

- M-01: get_ilass 추출 실패 시 부분 파일이 dest에 남지 않고, 0바이트
  기존 파일은 재다운로드 대상이 되며, 추출 크기를 아카이브 기록과 대조.
- m-07: 저장 패치 임시 파일이 고유명으로 생성되고 성공/실패 모두
  잔존물을 남기지 않으며, 실패 시 기존 출력이 보존된다.
- m-08: 배치 항목에 "index" 키가 없어도 KeyError 없이 폴백 매핑된다.
"""

import os
import shutil
import sys
import urllib.request
import zipfile
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import get_ilass
from get_ilass import download_ilass


# ---------------------------------------------------------------- M-01

def _mock_download(monkeypatch, src):
    monkeypatch.setattr(
        urllib.request, "urlretrieve",
        lambda url, filename: shutil.copy(str(src), filename))


def _make_zip(path, data=b"fake-ilass-binary", member="ilass.exe"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, data)


def test_ilass_corrupt_archive_leaves_no_dest(tmp_path, monkeypatch):
    src = tmp_path / "broken.zip"
    src.write_bytes(b"this is not a zip")
    _mock_download(monkeypatch, src)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(Exception):
        download_ilass(str(tmp_path), log=lambda m: None)
    # 부분 파일이 설치본으로 남으면 안 되고, 임시물도 정리돼야 한다
    assert not (tmp_path / "ilass.exe").exists()
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name not in ("broken.zip",)]
    assert leftovers == []


def test_ilass_zero_byte_existing_redownloads(tmp_path, monkeypatch):
    (tmp_path / "ilass.exe").write_bytes(b"")
    src = tmp_path / "ok.zip"
    _make_zip(src)
    _mock_download(monkeypatch, src)
    monkeypatch.setattr(sys, "platform", "win32")
    dest = download_ilass(str(tmp_path), log=lambda m: None)
    assert open(dest, "rb").read() == b"fake-ilass-binary"


def test_ilass_zip_happy_path_no_leftovers(tmp_path, monkeypatch):
    src = tmp_path / "ok.zip"
    _make_zip(src)
    _mock_download(monkeypatch, src)
    monkeypatch.setattr(sys, "platform", "win32")
    dest = download_ilass(str(tmp_path), log=lambda m: None)
    assert open(dest, "rb").read() == b"fake-ilass-binary"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["ilass.exe", "ok.zip"]


# ---------------------------------------------------------------- m-07

class _Sub:
    def __init__(self, content, start_s=0):
        self.content = content
        self.start = timedelta(seconds=start_s)
        self.end = timedelta(seconds=start_s + 2)
        self.index = 1


def _save(subs, out):
    from core.gst_patches import _patched_save_subtitle_file
    _patched_save_subtitle_file("in.srt", subs, str(out))


def test_save_patch_no_temp_leftovers(tmp_path):
    out = tmp_path / "out.srt"
    _save([_Sub("안녕", 0)], out)
    assert out.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["out.srt"]


def test_save_patch_failure_preserves_output_and_cleans(tmp_path):
    out = tmp_path / "out.srt"
    _save([_Sub("원본", 0)], out)
    before = out.read_text(encoding="utf-8")
    with pytest.raises(Exception):
        _save([_Sub(None, 0)], out)
    assert out.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["out.srt"]


# ---------------------------------------------------------------- m-08

class _TSub:
    def __init__(self):
        self.content = ""


def test_process_lines_missing_batch_index_falls_back():
    from core.gst_patches import _patched_process_translated_lines

    subs = [_TSub(), _TSub()]
    lines = [{"text": "번역0", "index": 0}]
    batch = [{"text": "원본0"}]  # "index" 키 없음
    _patched_process_translated_lines(object(), lines, subs, batch, True)
    assert subs[0].content == "번역0"


def test_process_lines_batch_index_still_wins():
    from core.gst_patches import _patched_process_translated_lines

    subs = [_TSub(), _TSub()]
    lines = [{"text": "번역1"}]
    batch = [{"index": 1, "text": "원본1"}]
    _patched_process_translated_lines(object(), lines, subs, batch, True)
    assert subs[1].content == "번역1"
    assert subs[0].content == ""
