"""US3: gaps are "unknown", never guessed, and counted (T018)."""

import pytest

from saft_reader import read_saft

ALLOWED_NONE = {"share", "reason", "effective_date", "expiration_date"}


@pytest.fixture
def data(sample_path):
    return read_saft(sample_path)


def count_unknowns(value):
    if value == "unknown":
        return 1
    if isinstance(value, dict):
        return sum(count_unknowns(v) for v in value.values())
    if isinstance(value, list):
        return sum(count_unknowns(v) for v in value)
    return 0


def nones_outside_allowed(value, key=None):
    if value is None:
        return [] if key in ALLOWED_NONE else [key]
    if isinstance(value, dict):
        return [k for kk, v in value.items() for k in nones_outside_allowed(v, kk)]
    if isinstance(value, list):
        return [k for v in value for k in nones_outside_allowed(v, key)]
    return []


def test_incomplete_records_are_unknown(data):
    assert {a["id"]: a for a in data["accounts"]}["7770"]["description"] == "unknown"
    code99 = [c for c in data["vat_codes"] if c["code"] == "99"]
    assert len(code99) == 1 and code99[0]["percentage"] == "unknown"   # not 0, not None
    assert {s["id"]: s for s in data["suppliers"]}["50007"]["name"] == "unknown"


def test_unknown_counts_match_output(data):
    counts = data["summary"]["unknown_values"]
    assert set(counts) == {"accounts", "vat_codes", "suppliers", "supplier_account_map"}
    for section, n in counts.items():
        assert n == count_unknowns(data[section]), section
    assert counts["accounts"] >= 1 and counts["vat_codes"] >= 1 and counts["suppliers"] >= 1


def test_no_unexpected_nulls(data):
    for section in ("accounts", "vat_codes", "suppliers", "supplier_account_map"):
        assert nones_outside_allowed(data[section]) == [], section


def test_skipped_records(data):
    skipped = data["summary"]["skipped"]
    assert len(skipped) == 1
    assert "AccountID" in skipped[0]
