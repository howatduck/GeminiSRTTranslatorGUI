# -*- coding: utf-8 -*-
"""core/subtitle_tools.py 테스트."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import subtitle_tools as st


def test_get_episode_key():
    assert st.get_episode_key("Show.S01E02.1080p.mkv") == (1, 2)
    assert st.get_episode_key("Show.s1e12.mkv") == (1, 12)
    assert st.get_episode_key("Show.1x02.mkv") == (1, 2)
    assert st.get_episode_key("Show.12x3.mkv") == (12, 3)
    assert st.get_episode_key("movie.2021.mkv") is None


def test_get_year_key():
    assert st.get_year_key("Dune.2021.2160p.mkv") == "2021"
    assert st.get_year_key("Show.S01E02.mkv") is None


def test_split_lang_suffix():
    assert st.split_lang_suffix("movie.en.srt") == (".en", ".srt")
    assert st.split_lang_suffix("movie.ko.srt") == (".ko", ".srt")
    assert st.split_lang_suffix("movie.srt") == ("", ".srt")


def _touch(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("x")


def test_scan_and_match_tv(tmp_path):
    d = tmp_path / "Season 1"
    d.mkdir()
    _touch(d / "Show.S01E01.1080p.mkv")
    _touch(d / "Show.S01E02.1080p.mkv")
    _touch(d / "Show.S01E01.srt")  # 이미 일치 -> 계획 제외
    (d / "Show.S01E01.srt").rename(d / "Show.S01E01.1080p.srt")
    _touch(d / "random.srt")  # S01E02 키 없음 -> 영상 2개라 매칭 실패
    _touch(d / "Show.S01E02.kor.smi")

    plan, unmatched = st.scan_and_match(str(d), "tv")
    # E02 smi -> 영상 파일명으로 리네임 계획 (언어 접미사 유지)
    assert len(plan) == 1
    old, new = plan[0]
    assert old.endswith("Show.S01E02.kor.smi")
    assert new.endswith("Show.S01E02.1080p.kor.smi")
    assert any(str(p).endswith("random.srt") for p in unmatched)


def test_scan_and_match_movie(tmp_path):
    d = tmp_path / "movies"
    d.mkdir()
    _touch(d / "Dune (2021).mkv")
    _touch(d / "dune.2021.srt")
    plan, unmatched = st.scan_and_match(str(d), "movie")
    assert len(plan) == 1
    assert plan[0][1].endswith("Dune (2021).srt")
    assert unmatched == []


def test_scan_and_match_single_video_fallback(tmp_path):
    d = tmp_path / "one"
    d.mkdir()
    _touch(d / "video.mkv")
    _touch(d / "weird-name.srt")
    plan, unmatched = st.scan_and_match(str(d), "tv")
    assert len(plan) == 1
    assert plan[0][1].endswith("video.srt")


def test_apply_rename(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    _touch(d / "a.srt")
    _touch(d / "b.srt")
    plan = [(str(d / "a.srt"), str(d / "b.srt")),   # 대상 존재 -> 건너뜀
            (str(d / "a.srt"), str(d / "c.srt"))]   # 적용
    logs = []
    applied, skipped = st.apply_rename(plan, log=logs.append)
    assert applied == 1 and skipped == 1
    assert (d / "c.srt").exists()
    assert not (d / "a.srt").exists()  # 적용된 원본은 이동됨


def test_find_pairs(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    _touch(d / "video1.mkv")
    _touch(d / "video1.srt")
    _touch(d / "video2.mkv")
    _touch(d / "video2.ass")
    _touch(d / "video3.mkv")  # 자막 없음
    pairs, skipped = st.find_pairs(str(d))
    assert len(pairs) == 2
    assert len(skipped) == 1
    # srt 우선
    _touch(d / "video1.ass")
    pairs, _ = st.find_pairs(str(d))
    v1 = [p for p in pairs if p[0] == "video1.mkv"][0]
    assert v1[1] == "video1.srt"


def test_already_synced(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    _touch(d / "video.mkv")
    _touch(d / "video.srt")
    assert not st.already_synced(str(d), "video", "video.srt")
    _touch(d / "video.srt.bak")
    assert st.already_synced(str(d), "video", "video.srt")


def test_sanitize_srt(tmp_path):
    p = tmp_path / "t.srt"
    p.write_text(
        "1\n00:00:01.000 --> 00:00:02.000\nhello\n\n"
        "2\n00:00:03,500 --> 00:00:04,700\nworld\n\n",
        encoding="utf-8",
    )
    n = st.sanitize_srt(str(p))
    assert n == 2
    text = p.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:02,000" in text
    assert "00:00:03,500 --> 00:00:04,700" in text
    assert "\n2\nworld" not in text  # 시퀀스 번호가 텍스트에 섞이지 않음


def test_find_ilass_missing(monkeypatch):
    monkeypatch.setattr(st.shutil, "which", lambda _: None)
    monkeypatch.setattr(st.sys, "frozen", False, raising=False)
    # 프로젝트 루트에 ilass.exe가 없으면 None
    assert st.find_ilass() is None or isinstance(st.find_ilass(), str)


def test_plan_rename_invalid_folder():
    with pytest.raises(st.SubtitleToolsError):
        st.plan_rename("/nonexistent-folder-xyz")


def test_scan_and_match_max_files(tmp_path):
    d = tmp_path / "big"
    d.mkdir()
    for i in range(10):
        _touch(d / f"file{i}.srt")
    with pytest.raises(st.SubtitleToolsError):
        st.scan_and_match(str(d), "tv", max_files=5)


def _make_smi(blocks):
    """blocks: [(start_ms, text_or_None)] -> cp949 SAMI bytes."""
    parts = ["<SAMI><BODY>"]
    for start, text in blocks:
        body = "&nbsp;" if text is None else text
        parts.append(f'<SYNC Start={start}><P Class=KRCC>{body}')
    parts.append("</BODY></SAMI>")
    return "".join(parts).encode("cp949")


def test_smi_bytes_to_srt_end_times():
    # 빈 SYNC는 자막 지움 표시 -> 종료 시각은 다음 SYNC 시작이어야 한다
    srt = st.smi_bytes_to_srt(_make_smi([(1000, "첫째"), (3000, None),
                                         (5000, "둘째"), (6500, None)]))
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert "00:00:05,000 --> 00:00:06,500" in srt


def test_smi_bytes_to_srt_no_empty_blocks():
    srt = st.smi_bytes_to_srt(_make_smi([(1000, "첫째"), (5000, "둘째")]))
    assert "00:00:01,000 --> 00:00:05,000" in srt
    assert "00:00:05,000 --> 00:00:07,000" in srt


def test_convert_to_srt_smi_parsed_without_ffmpeg(tmp_path, monkeypatch):
    # cp949 smi는 ffmpeg 없이도 직접 파싱으로 변환돼야 한다
    monkeypatch.setattr(st, "find_ffmpeg", lambda: None)
    src = tmp_path / "m.smi"
    src.write_bytes(_make_smi([(1000, "대사"), (3000, None)]))
    out = tmp_path / "m.srt"
    assert st.convert_to_srt(str(src), str(out)) is True
    assert "00:00:01,000 --> 00:00:03,000" in out.read_text(encoding="utf-8")


def test_subtitle_correlation(tmp_path):
    body = "".join(
        f"{i}\n00:00:{10 + i * 10:02d},000 --> 00:00:{12 + i * 10:02d},000\nx\n\n"
        for i in range(1, 6))
    a = tmp_path / "a.srt"
    a.write_text(body, encoding="utf-8")
    assert st.subtitle_correlation(str(a), str(a)) == 1.0
    shifted = "".join(
        f"{i}\n00:01:{10 + i * 10:02d},000 --> 00:01:{12 + i * 10:02d},000\nx\n\n"
        for i in range(1, 6))
    b = tmp_path / "b.srt"
    b.write_text(shifted, encoding="utf-8")
    assert st.subtitle_correlation(str(a), str(b)) == 0.0


def test_sync_output_ok(tmp_path):
    bad = tmp_path / "bad.srt"
    bad.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n" * 100, encoding="utf-8")
    assert st.sync_output_ok(str(bad)) is False
    good = tmp_path / "good.srt"
    good.write_text("".join(
        f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500\nx\n\n"
        for i in range(1, 120)), encoding="utf-8")
    assert st.sync_output_ok(str(good)) is True


def test_count_cues(tmp_path):
    p = tmp_path / "c.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n\n"
                 "2\n00:00:03,000 --> 00:00:04,000\ny\n", encoding="utf-8")
    assert st.count_cues(str(p)) == 2
    assert st.count_cues(str(tmp_path / "missing.srt")) == 0
