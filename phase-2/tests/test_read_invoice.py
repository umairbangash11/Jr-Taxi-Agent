import sys
import os

# tell the test where read_invoice.py lives
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "phase-2"))
from read_invoice import read_invoice


def test_onepark_receipt():
    result = read_invoice("samples/kvittering_onepark.pdf")

    assert result["vendor"] == "ONEPARK"
    assert result["debit_account"] == "7161"
    assert result["credit_account"] == "1930 Bank"
    assert result["amount"] == 500.0
    assert result["status"] == "READY"


def test_nio_invoice():
    result = read_invoice("samples/faktura_nio.pdf")

    assert result["vendor"] == "NIO"
    assert result["debit_account"] == "7033"
    assert result["credit_account"] == "2400 Leverandørgjeld"
    assert result["amount"] == 2000.0
    assert result["vat"] == "MVA 25 % 400,00"


def test_unknown_supplier_needs_review():
    result = read_invoice("samples/faktura.pdf")

    assert result["debit_account"] == "unknown"      # supplier not in Phase 1 data
    assert result["status"] == "NEEDS REVIEW"        # so a human must check
    assert result["amount"] == 6000.0                # 6 000,00 as a number
    assert result["vat"] == "MVA 25 % 1 200,00"      # 25% VAT on a 6000 invoice