# -*- coding: utf-8 -*-
"""app.skill_installer 테스트 (위젯 생성 없이 실행 가능한 부분)."""

import pytest

import app.skill_installer as si
from app.skill_installer import SKILL_TARGETS, target_ids


def test_target_ids_unique():
    ids = target_ids()
    assert len(ids) == len(set(ids))
    assert set(ids) == {"claude", "agents", "antigravity",
                        "gemini_cli", "copilot", "agy", "all"}


# ---------- run_install 분기 ----------


def test_run_install_extra_single(monkeypatch):
    monkeypatch.setattr(
        si, "install_extra_skill",
        lambda target, is_global=False, cwd=None: [f"/{target}/SKILL.md"])
    paths, errors = si.run_install("copilot", False, "/proj")
    assert paths == ["/copilot/SKILL.md"]
    assert errors == []


def test_run_install_all_partial_failure(monkeypatch):
    monkeypatch.setattr(
        si, "install_skill",
        lambda target, is_global, cwd=None: ["/lib/SKILL.md"])

    def fake_extra(target, is_global=False, cwd=None):
        if target == "copilot":
            raise RuntimeError("boom")
        return [f"/{target}/SKILL.md"]

    monkeypatch.setattr(si, "install_extra_skill", fake_extra)
    paths, errors = si.run_install("all", True)
    # 실패한 copilot만 errors에 남고 나머지는 설치된다
    assert "/lib/SKILL.md" in paths
    assert "/gemini_cli/SKILL.md" in paths
    assert "/agy/SKILL.md" in paths
    assert len(errors) == 1 and "copilot" in errors[0]


def test_run_install_all_without_library(monkeypatch):
    monkeypatch.setattr(si, "install_skill", None)
    monkeypatch.setattr(
        si, "install_extra_skill",
        lambda target, is_global=False, cwd=None: [f"/{target}/SKILL.md"])
    paths, errors = si.run_install("all", True)
    assert len(paths) == 3  # 확장 대상 3종은 라이브러리 없이도 설치
    assert len(errors) == 1 and "library" in errors[0]


def test_run_install_library_target_without_library(monkeypatch):
    monkeypatch.setattr(si, "install_skill", None)
    with pytest.raises(RuntimeError):
        si.run_install("claude", True)


def test_target_labels_bilingual():
    for tid, ko, en in SKILL_TARGETS:
        assert tid.strip()
        assert ko.strip()
        assert en.strip()
