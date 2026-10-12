# -*- coding: utf-8 -*-
"""app.skill_installer 테스트 (Qt 없이 실행 가능한 순수 부분)."""

from app.skill_installer import SKILL_TARGETS, target_ids


def test_target_ids_unique():
    ids = target_ids()
    assert len(ids) == len(set(ids))
    assert set(ids) == {"claude", "agents", "antigravity", "all"}


def test_target_labels_bilingual():
    for tid, ko, en in SKILL_TARGETS:
        assert tid.strip()
        assert ko.strip()
        assert en.strip()
