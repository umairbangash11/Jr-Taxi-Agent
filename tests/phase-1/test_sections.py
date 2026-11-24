"""US1: reference data sections (T005)."""

from saft_reader import read_saft


def by_id(items, key="id"):
    return {item[key]: item for item in items}


def test_top_level_keys(sample_path):
    data = read_saft(sample_path)
    assert list(data) == ["summary", "accounts", "vat_codes", "suppliers",
                          "supplier_account_map", "supplier_vat_account_map"]
    for section in ("accounts", "vat_codes", "suppliers", "supplier_account_map",
                    "supplier_vat_account_map"):
        assert data[section], f"{section} is empty"


def test_accounts_exact_and_sorted(sample_path):
    data = read_saft(sample_path)
    accounts = by_id(data["accounts"])
    assert accounts["7026"]["description"] == "Reparasjoner"
    assert accounts["7155"]["description"] == "Bespisning/Mat"
    assert accounts["1930"]["description"] == "Bedriftskonto"
    assert accounts["2400"]["description"] == "Leverandørgjeld"   # æøå intact
    ids = [a["id"] for a in data["accounts"]]
    assert ids == sorted(ids, key=int)
    assert len(ids) == 10                                          # ID-less account dropped
    assert any("AccountID" in s for s in data["summary"]["skipped"])


def test_vat_codes(sample_path):
    codes = read_saft(sample_path)["vat_codes"]
    assert codes[0] == {"code": "", "percentage": 0, "description": "Ingen mva-kode (blank)",
                        "standard_tax_code": "unknown", "effective_date": None,
                        "expiration_date": None, "source": "implicit"}
    code2 = [c for c in codes if c["code"] == "2"]
    assert [c["percentage"] for c in code2] == [25]
    code12 = [c for c in codes if c["code"] == "12"]
    assert [(c["percentage"], c["effective_date"], c["expiration_date"]) for c in code12] == [
        (10, "2020-04-01", "2021-09-30"), (12, "2021-10-01", None)]
    assert all(c["source"] == "tax_table" for c in codes[1:])
    assert [c["code"] for c in codes] == ["", "2", "11", "12", "12", "99"]


def test_suppliers(sample_path):
    suppliers = by_id(read_saft(sample_path)["suppliers"])
    assert suppliers["50001"]["name"] == "NIO"
    assert suppliers["50002"]["name"] == "ONEPARK"
    assert suppliers["50003"]["name"] == "RA FORSIKRING"
    assert suppliers["50001"]["in_master_data"] is True


def test_summary_header(sample_path):
    summary = read_saft(sample_path)["summary"]
    assert summary["saft_version"] == "1.30"
    assert summary["company_name"] == "Testtaxi Demo AS"
    assert summary["company_registration_number"] == "999999999"
    assert summary["period"] == {"start": "1", "start_year": "2025", "end": "12", "end_year": "2025"}
    assert summary["source_file"] == "saft_sample.xml"
