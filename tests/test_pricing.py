# -*- coding: utf-8 -*-
"""core.pricing 테스트."""

import json
import os
import tempfile

from core.pricing import (
    estimate_cost,
    get_model_rates,
    read_report_cost,
    token_report_path_for,
)

FAKE_PRICING = {
    "currency": "USD",
    "unit": "per 1 million tokens",
    "models": {
        "gemini-2.5-flash": {
            "standard": {"input": 0.3, "output": 2.5},
        },
    },
}


def test_get_model_rates():
    rates = get_model_rates("gemini-2.5-flash", pricing=FAKE_PRICING)
    assert rates == (0.3, 2.5)


def test_get_model_rates_unknown():
    assert get_model_rates("no-such-model", pricing=FAKE_PRICING) is None
    assert get_model_rates("gemini-2.5-flash", pricing={}) is None


def test_estimate_cost():
    cost = estimate_cost("gemini-2.5-flash", 1_000_000, 1_000_000,
                         pricing=FAKE_PRICING)
    assert cost["input"] == 0.3
    assert cost["output"] == 2.5
    assert cost["total"] == 2.8
    assert cost["tier"] == "standard"


def test_estimate_cost_unknown_model():
    assert estimate_cost("nope", 100, 100, pricing=FAKE_PRICING) is None


def test_token_report_path_for():
    p = token_report_path_for("/out/movie.ko.srt")
    assert p == "/out/.token_reports/movie.ko_tokens.json"


def test_read_report_cost():
    report = {"cost": {"input": 0.001, "output": 0.002, "total": 0.003}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(report, f)
        path = f.name
    try:
        assert read_report_cost(path)["total"] == 0.003
    finally:
        os.unlink(path)


def test_read_report_cost_missing():
    assert read_report_cost("/nonexistent/path.json") is None
