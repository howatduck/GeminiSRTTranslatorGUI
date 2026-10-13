# -*- coding: utf-8 -*-
"""gen_version_info 버전 파싱 테스트."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gen_version_info import parse_version


def test_parse_tag():
    assert parse_version("v1.2") == (1, 2, 0, 0)
    assert parse_version("1.2") == (1, 2, 0, 0)


def test_parse_full():
    assert parse_version("v2.0.1") == (2, 0, 1, 0)
    assert parse_version("1.2.3.4") == (1, 2, 3, 4)


def test_parse_invalid():
    assert parse_version("") == (0, 0, 0, 0)
    assert parse_version(None) == (0, 0, 0, 0)
    assert parse_version("main") == (0, 0, 0, 0)
