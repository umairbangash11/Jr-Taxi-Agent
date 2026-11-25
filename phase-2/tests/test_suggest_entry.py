import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "phase-2"))
from suggest_entry import suggest, fmt_nok

# ---------------------------------------------------------------------------
# Minimal demo SAFT data — no real file I/O needed.
# ---------------------------------------------------------------------------

DEMO_SAFT = {
    "suppliers": [
        {"id": "50001", "name": "NIO"},
        {"id": "50002", "name": "ONEPARK"},
        {"id": "50004", "name": "AMBI SERVICE"},
        {"id": "50005", "name": "SPLIT SUPPLIER"},
    ],
    "supplier_vat_account_map": [
        # NIO: 25% → Drivstoff
        {
            "supplier_id": "50001",
            "supplier_name": "NIO",
            "vat_code": "2",
            "account_id": "7033",
            "account_description": "Drivstoff",
            "reason": None,
        },
        # ONEPARK: 0% → Parkering
        {
            "supplier_id": "50002",
            "supplier_name": "ONEPARK",
            "vat_code": "",
            "account_id": "7161",
            "account_description": "Parkering",
            "reason": None,
        },
        # ONEPARK: 25% → also known (some invoices have VAT)
        {
            "supplier_id": "50002",
            "supplier_name": "ONEPARK",
            "vat_code": "2",
            "account_id": "7161",
            "account_description": "Parkering",
            "reason": None,
        },
        # AMBI SERVICE: 25% → ambiguous, no account resolved
        {
            "supplier_id": "50004",
            "supplier_name": "AMBI SERVICE",
            "vat_code": "2",
            "account_id": "unknown",
            "account_description": "unknown",
            "reason": "ambiguous history",
        },
        # SPLIT SUPPLIER: 0% → 7170, 25% → 7790 (two different accounts by rate)
        {
            "supplier_id": "50005",
            "supplier_name": "SPLIT SUPPLIER",
            "vat_code": "",
            "account_id": "7170",
            "account_description": "Leie",
            "reason": None,
        },
        {
            "supplier_id": "50005",
            "supplier_name": "SPLIT SUPPLIER",
            "vat_code": "2",
            "account_id": "7790",
            "account_description": "Annen kostnad",
            "reason": None,
        },
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(vendor, lines):
    return {"vendor": vendor, "lines": lines, "check_status": "OK"}


def _line(net, vat, rate):
    return {"net_amount": net, "vat_amount": vat, "vat_rate": rate}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_fmt_nok():
    assert fmt_nok(2179.80) == "2 179,80"
    assert fmt_nok(100.00) == "100,00"
    assert fmt_nok(0.00) == "0,00"
    assert fmt_nok(None) == "—"
    assert fmt_nok(1000000.50) == "1 000 000,50"


def test_known_supplier_vat25():
    # debet = gross: 100.00 net + 25.00 vat = 125.00
    rows = suggest(_result("NIO", [_line(100.00, 25.00, 25)]), DEMO_SAFT)
    assert len(rows) == 1
    r = rows[0]
    assert r["konto"] == "7033"
    assert r["konto_name"] == "Drivstoff"
    assert r["mk"] == "2"
    assert r["debet"] == 125.00
    assert r["kredit"] == "50001"
    assert r["kredit_name"] == "NIO"
    assert not r["needs_review"]


def test_known_supplier_vat0():
    # debet = gross: 50.00 net + 0.00 vat = 50.00
    rows = suggest(_result("ONEPARK", [_line(50.00, 0.00, 0)]), DEMO_SAFT)
    assert len(rows) == 1
    r = rows[0]
    assert r["konto"] == "7161"
    assert r["mk"] == ""
    assert r["debet"] == 50.00
    assert r["kredit"] == "50002"
    assert r["kredit_name"] == "ONEPARK"
    assert not r["needs_review"]


def test_unknown_supplier_needs_review():
    rows = suggest(_result("GHOST CORP", [_line(100.00, 25.00, 25)]), DEMO_SAFT)
    assert len(rows) == 1
    assert rows[0]["needs_review"]
    assert "not found" in rows[0]["reason"].lower()


def test_ambiguous_account_needs_review():
    rows = suggest(_result("AMBI SERVICE", [_line(200.00, 50.00, 25)]), DEMO_SAFT)
    assert len(rows) == 1
    assert rows[0]["needs_review"]
    assert "50004" in rows[0]["reason"]


def test_missing_vat_entry_needs_review():
    # NIO has no entry for vat_code "" (0%), so it should flag NEEDS REVIEW.
    rows = suggest(_result("NIO", [_line(100.00, 0.00, 0)]), DEMO_SAFT)
    assert len(rows) == 1
    assert rows[0]["needs_review"]
    assert "50001" in rows[0]["reason"]


def test_unknown_vat_rate_needs_review():
    rows = suggest(_result("NIO", [_line(100.00, 15.00, 15)]), DEMO_SAFT)
    assert len(rows) == 1
    assert rows[0]["needs_review"]
    assert "15" in rows[0]["reason"]


def test_partial_vendor_name_match():
    # "Nio AS" should still match supplier "NIO".
    rows = suggest(_result("Nio AS", [_line(80.00, 20.00, 25)]), DEMO_SAFT)
    assert len(rows) == 1
    assert rows[0]["konto"] == "7033"
    assert not rows[0]["needs_review"]


def test_multiple_lines_same_account():
    # debet = gross per line: 125.00 and 62.50
    lines = [_line(100.00, 25.00, 25), _line(50.00, 12.50, 25)]
    rows = suggest(_result("NIO", lines), DEMO_SAFT)
    assert len(rows) == 2
    assert all(r["konto"] == "7033" and r["mk"] == "2" for r in rows)
    assert rows[0]["debet"] == 125.00
    assert rows[1]["debet"] == 62.50
    assert all(not r["needs_review"] for r in rows)


def test_same_supplier_two_vat_rates_two_accounts():
    # SPLIT SUPPLIER: 0% → 7170 Leie (gross 500), 25% → 7790 Annen kostnad (gross 250).
    lines = [_line(500.00, 0.00, 0), _line(200.00, 50.00, 25)]
    rows = suggest(_result("SPLIT SUPPLIER", lines), DEMO_SAFT)
    assert len(rows) == 2
    assert rows[0]["konto"] == "7170"
    assert rows[0]["konto_name"] == "Leie"
    assert rows[0]["mk"] == ""
    assert rows[0]["debet"] == 500.00
    assert rows[0]["kredit"] == "50005"
    assert rows[0]["kredit_name"] == "SPLIT SUPPLIER"
    assert not rows[0]["needs_review"]
    assert rows[1]["konto"] == "7790"
    assert rows[1]["konto_name"] == "Annen kostnad"
    assert rows[1]["mk"] == "2"
    assert rows[1]["debet"] == 250.00
    assert rows[1]["kredit"] == "50005"
    assert rows[1]["kredit_name"] == "SPLIT SUPPLIER"
    assert not rows[1]["needs_review"]


def test_empty_vendor_needs_review():
    rows = suggest(_result("", [_line(100.00, 25.00, 25)]), DEMO_SAFT)
    assert rows[0]["needs_review"]
