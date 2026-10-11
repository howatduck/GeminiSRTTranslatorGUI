# -*- coding: utf-8 -*-
"""core.subtitle_io 테스트."""

from core.subtitle_io import (
    entry_cps,
    format_srt,
    ms_to_timestamp,
    parse_srt,
    timestamp_to_ms,
)

SAMPLE = """1
00:00:01,000 --> 00:00:03,500
Hello world

2
00:00:04,000 --> 00:00:06,000
Second line
with two rows
"""


def test_parse_basic():
    entries = parse_srt(SAMPLE)
    assert len(entries) == 2
    assert entries[0]["start"] == "00:00:01,000"
    assert entries[0]["end"] == "00:00:03,500"
    assert entries[0]["text"] == "Hello world"
    assert entries[1]["text"] == "Second line\nwith two rows"


def test_parse_timestamps_ms():
    entries = parse_srt(SAMPLE)
    assert entries[0]["start_ms"] == 1000
    assert entries[0]["end_ms"] == 3500


def test_parse_skips_broken_blocks():
    entries = parse_srt("garbage\n\n" + SAMPLE)
    assert len(entries) == 2


def test_parse_empty():
    assert parse_srt("") == []
    assert parse_srt(None) == []


def test_roundtrip():
    entries = parse_srt(SAMPLE)
    assert parse_srt(format_srt(entries)) == entries


def test_timestamp_to_ms_invalid():
    assert timestamp_to_ms("not a time") is None
    assert timestamp_to_ms("") is None


def test_ms_to_timestamp():
    assert ms_to_timestamp(0) == "00:00:00,000"
    assert ms_to_timestamp(3723456) == "01:02:03,456"


def test_entry_cps():
    entries = parse_srt(SAMPLE)
    cps = entry_cps(entries[0])
    # "Helloworld" 10자 / 2.5초 = 4.0
    assert abs(cps - 4.0) < 0.01


def test_entry_cps_no_duration():
    assert entry_cps({"text": "abc", "start_ms": None, "end_ms": None}) is None
