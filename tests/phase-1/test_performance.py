"""Polish: SC-005 performance (50 000 booking lines < 30 s) and SC-004 determinism (T020)."""

import time

from saft_reader import NS, read_saft, write_saft_data

SUPPLIERS = 200
INVOICES = 25_000          # 2 lines each -> 50 000 booking lines


def _big_saft(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<AuditFile xmlns="{NS}">'
                 "<Header><AuditFileVersion>1.30</AuditFileVersion>"
                 "<Company><Name>Ytelsestest AS</Name></Company></Header><MasterFiles>"
                 "<GeneralLedgerAccounts>"
                 "<Account><AccountID>2400</AccountID><AccountDescription>Leverandørgjeld"
                 "</AccountDescription></Account>"
                 "<Account><AccountID>7026</AccountID><AccountDescription>Reparasjoner"
                 "</AccountDescription></Account></GeneralLedgerAccounts><Suppliers>")
        for s in range(SUPPLIERS):
            fh.write(f"<Supplier><Name>Leverandør {s}</Name><SupplierID>{60000 + s}"
                     "</SupplierID></Supplier>")
        fh.write("</Suppliers></MasterFiles><GeneralLedgerEntries><Journal>"
                 "<JournalID>GL</JournalID>")
        for i in range(INVOICES):
            sid = 60000 + i % SUPPLIERS
            fh.write(f"<Transaction><TransactionID>{i}</TransactionID>"
                     "<TransactionDate>2025-06-01</TransactionDate>"
                     "<Line><AccountID>7026</AccountID><DebitAmount><Amount>100.00</Amount>"
                     "</DebitAmount></Line>"
                     f"<Line><AccountID>2400</AccountID><SupplierID>{sid}</SupplierID>"
                     "<CreditAmount><Amount>100.00</Amount></CreditAmount></Line></Transaction>")
        fh.write("</Journal></GeneralLedgerEntries></AuditFile>\n")


def test_50000_lines_under_30_seconds(tmp_path):
    path = tmp_path / "big.xml"
    _big_saft(path)
    start = time.perf_counter()
    data = read_saft(str(path))
    elapsed = time.perf_counter() - start
    assert elapsed < 30, f"took {elapsed:.1f} s"
    assert data["summary"]["counts"]["supplier_invoices"] == INVOICES
    assert data["summary"]["counts"]["mapped_suppliers"] == SUPPLIERS
    assert {m["account_id"] for m in data["supplier_account_map"]} == {"7026"}


def test_same_input_same_bytes(sample_path, tmp_path):
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    write_saft_data(read_saft(sample_path), str(first))
    write_saft_data(read_saft(sample_path), str(second))
    assert first.read_bytes() == second.read_bytes()
