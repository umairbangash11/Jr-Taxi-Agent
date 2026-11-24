import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "phase-2"))
from check_result import check

# Helpers that build a minimal valid JSON payload.

def _make_payload(total_amount, lines):
    return json.dumps({"total_amount": total_amount, "lines": lines})


AUTOSYNC_LINES = [
    {"net_amount": 2120.80, "vat_amount": 0.00, "vat_rate": 0},
    {"net_amount": 47.20,   "vat_amount": 11.80, "vat_rate": 25},
]


def test_autosync_ok():
    # Correct total 2179.80 matches the sum of both lines (2120.80+0+47.20+11.80).
    result = check(_make_payload(2179.80, AUTOSYNC_LINES))
    assert result["check_status"] == "OK"


def test_autosync_wrong_total():
    # Total 2100.00 does not match the line sum, so the invoice needs review.
    result = check(_make_payload(2100.00, AUTOSYNC_LINES))
    assert result["check_status"] == "NEEDS REVIEW"
    assert "total" in result["check_reason"].lower() or "match" in result["check_reason"].lower()


def test_invalid_vat_rate():
    # vat_rate 11.8 is not in {0, 12, 15, 25}, so the result should be flagged.
    lines = [{"net_amount": 100.00, "vat_amount": 11.80, "vat_rate": 11.8}]
    result = check(_make_payload(111.80, lines))
    assert result["check_status"] == "NEEDS REVIEW"
    assert "vat_rate" in result["check_reason"]


def test_null_total_amount():
    # total_amount: null in the JSON must return NEEDS REVIEW without crashing.
    result = check(json.dumps({"total_amount": None, "lines": AUTOSYNC_LINES}))
    assert result["check_status"] == "NEEDS REVIEW"
    assert "total_amount" in result["check_reason"]


def test_broken_json():
    # Malformed text must not raise; it should return NEEDS REVIEW gracefully.
    result = check("{ not json")
    assert result["check_status"] == "NEEDS REVIEW"
    assert "JSON" in result["check_reason"]
