# -*- coding: utf-8 -*-
"""core.update_check 테스트 (네트워크 호출 제외)."""

from core.update_check import _parse_version, is_newer


def test_parse_simple():
    assert _parse_version("3.8.3") == (3, 8, 3)
    assert _parse_version("10.0") == (10, 0)


def test_parse_prerelease_is_none():
    assert _parse_version("3.8.3b1") is None
    assert _parse_version("3.8.3rc1") is None
    assert _parse_version("3.8.3.dev0") is None


def test_parse_invalid_is_none():
    assert _parse_version("") is None
    assert _parse_version(None) is None
    assert _parse_version("not-a-version") is None


def test_is_newer():
    assert is_newer("3.8.4", "3.8.3") is True
    assert is_newer("3.8.3", "3.8.3") is False
    assert is_newer("3.8.3", "3.8.4") is False
    assert is_newer("4.0", "3.9.9") is True


def test_is_newer_uncomparable():
    assert is_newer(None, "3.8.3") is False
    assert is_newer("3.8.4", None) is False
    assert is_newer("3.8.4b1", "3.8.3") is False
