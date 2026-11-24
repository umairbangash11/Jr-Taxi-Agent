"""supplier_vat_account_map — per (supplier, VAT code) expense-account mapping."""

import pytest
from saft_reader import read_saft


@pytest.fixture(scope="module")
def vat_map():
    import os
    sample = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "saft_sample.xml")
    data = read_saft(sample)
    rows = data["supplier_vat_account_map"]
    by_key = {(m["supplier_id"], m["vat_code"]): m for m in rows}
    return rows, by_key


def test_nio_vat2_maps_at_80_percent(vat_map):
    # NIO has 5 invoices for VAT "2"; 4 use 7033 → exactly 80 % share.
    _, by_key = vat_map
    m = by_key[("50001", "2")]
    assert (m["account_id"], m["account_description"]) == ("7033", "Drivstoff")
    assert m["share"] == 0.8
    assert m["invoice_count"] == 5
    assert m["reason"] is None


def test_onepark_vat2_maps_to_7161(vat_map):
    _, by_key = vat_map
    m = by_key[("50002", "2")]
    assert (m["account_id"], m["share"], m["invoice_count"]) == ("7161", 1, 2)


def test_onepark_blank_vat_maps_to_7161(vat_map):
    # One ONEPARK invoice had no VAT code; it still maps cleanly to 7161.
    _, by_key = vat_map
    m = by_key[("50002", "")]
    assert (m["account_id"], m["invoice_count"]) == ("7161", 1)


def test_ra_forsikring_blank_vat_maps_to_7027(vat_map):
    _, by_key = vat_map
    m = by_key[("50003", "")]
    assert (m["account_id"], m["share"], m["invoice_count"]) == ("7027", 1, 2)


def test_ambi_vat2_ambiguous(vat_map):
    # AMBI uses 7026 on 2 of 3 invoices (67 %) — below the 80 % threshold.
    _, by_key = vat_map
    m = by_key[("50004", "2")]
    assert m["account_id"] == "unknown"
    assert m["reason"] == "ambiguous history"
    assert [(c["account_id"], c["invoice_count"]) for c in m["candidates"]] == [
        ("7026", 2), ("7155", 1)]


def test_splitt_vat2_multiple_accounts(vat_map):
    # Every SPLITT invoice has two cost accounts at once — always ambiguous.
    _, by_key = vat_map
    m = by_key[("50005", "2")]
    assert m["account_id"] == "unknown"
    assert m["reason"] == "multiple accounts on the same invoices"


def test_ledger_only_supplier_vat2(vat_map):
    _, by_key = vat_map
    m = by_key[("50099", "2")]
    assert (m["account_id"], m["invoice_count"]) == ("7026", 1)


def test_no_history_suppliers_absent(vat_map):
    # Suppliers with zero invoices produce no entries (nothing to infer from).
    _, by_key = vat_map
    for sid in ("50006", "50007"):
        assert not any(k[0] == sid for k in by_key), f"{sid} should not appear"


def test_balance_sheet_accounts_excluded(vat_map):
    rows, _ = vat_map
    for m in rows:
        assert m["account_id"] == "unknown" or m["account_id"][0] in "345678"
        for c in m["candidates"]:
            assert c["account_id"] not in ("1930", "2400") and not c["account_id"].startswith("27")


def test_ordering(vat_map):
    rows, _ = vat_map
    keys = [(m["supplier_id"], m["vat_code"]) for m in rows]
    assert keys == [
        ("50001", "2"),
        ("50002", ""),
        ("50002", "2"),
        ("50003", ""),
        ("50004", "2"),
        ("50005", "2"),
        ("50099", "2"),
    ]
