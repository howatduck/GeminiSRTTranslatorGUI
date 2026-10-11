# -*- coding: utf-8 -*-
"""core.config 상수 무결성 테스트."""

from core import config


def test_app_identity():
    assert config.APP_NAME
    assert config.SETTINGS_ORG
    assert config.SETTINGS_APP


def test_api_key_slots():
    assert config.NUM_API_KEYS == 10
    assert len(config.API_KEY_SETTINGS) == config.NUM_API_KEYS
    assert len(set(config.API_KEY_SETTINGS)) == config.NUM_API_KEYS


def test_defaults():
    assert config.DEFAULT_MODEL
    assert config.DEFAULT_BATCH_SIZE > 0
