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