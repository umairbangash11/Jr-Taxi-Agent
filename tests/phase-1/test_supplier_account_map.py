"""US2: supplier→account map (T014) — Phase 1 exit criterion.

Expected values are derived from samples/saft_sample.xml as specified in tasks.md T004.
"""

import pytest

import saft_reader
from saft_reader import read_saft


@pytest.fixture(scope="module")
def mapping():
    import os
    sample = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "saft_sample.xml")
    data = read_saft(sample)
    return data, {m["supplier_id"]: m for m in data["supplier_account_map"]}


def cands(m):
    return [(c["account_id"], c["invoice_count"]) for c in m["candidates"]]


def test_nio_maps_at_exactly_80_percent(mapping):
    _, by_id = mapping
    nio = by_id["50001"]
    assert (nio["supplier_name"], nio["account_id"], nio["account_description"]) == \
        ("NIO", "7033", "Drivstoff")
    assert nio["share"] == 0.8
    assert nio["invoice_count"] == 5            # payment + netting transaction not counted
    assert cands(nio) == [("7033", 4), ("7026", 1)]
    assert nio["reason"] is None
    assert nio["vat_codes_seen"] == ["2"]


def test_onepark_and_ra_forsikring(mapping):
    _, by_id = mapping
    onepark = by_id["50002"]
    assert (onepark["account_id"], onepark["share"], onepark["invoice_count"]) == ("7161", 1, 3)
    assert onepark["vat_codes_seen"] == ["", "2"]   # one invoice without VAT code
    ra = by_id["50003"]
    assert (ra["supplier_name"], ra["account_id"], ra["invoice_count"]) == \
        ("RA FORSIKRING", "7027", 2)
    assert ra["vat_codes_seen"] == [""]


def test_ambiguous_history_is_unknown(mapping):
    _, by_id = mapping
    ambi = by_id["50004"]
    assert (ambi["account_id"], ambi["reason"], ambi["share"]) == \
        ("unknown", "ambiguous history", None)
    assert ambi["account_description"] == "unknown"
    assert [(c["account_id"], c["invoice_count"], c["share"]) for c in ambi["candidates"]] == \
        [("7026", 2, 0.667), ("7155", 1, 0.333)]


def test_split_invoices_are_unknown(mapping):
    _, by_id = mapping
    split = by_id["50005"]
    assert (split["account_id"], split["reason"]) == \
        ("unknown", "multiple accounts on the same invoices")
    assert cands(split) == [("7026", 2), ("7155", 2)]


def test_no_history_is_unknown(mapping):
    _, by_id = mapping
    for sid in ("50006", "50007"):
        m = by_id[sid]
        assert (m["account_id"], m["reason"], m["invoice_count"], m["candidates"]) == \
            ("unknown", "no booking history", 0, [])
    assert by_id["50007"]["supplier_name"] == "unknown"


def test_supplier_only_in_ledger(mapping):
    data, by_id = mapping
    m = by_id["50099"]
    assert (m["account_id"], m["supplier_name"]) == ("7026", "unknown")
    sup = {s["id"]: s for s in data["suppliers"]}["50099"]
    assert sup["in_master_data"] is False and sup["name"] == "unknown"
    assert any("50099" in w for w in data["summary"]["warnings"])


def test_balance_sheet_accounts_never_mapped(mapping):
    data, _ = mapping
    for m in data["supplier_account_map"]:
        assert m["account_id"] == "unknown" or m["account_id"][0] in "345678"
        for c in m["candidates"]:
            assert c["account_id"] not in ("1930", "2400") and not c["account_id"].startswith("27")


def test_counts(mapping):
    data, by_id = mapping
    counts = data["summary"]["counts"]
    assert counts["supplier_invoices"] == 19 - 3       # minus payment, netting, sales
    assert counts["mapped_suppliers"] == 4             # NIO, ONEPARK, RA FORSIKRING, 50099
    assert counts["unknown_mappings"] == 4             # AMBI, SPLITT, 50006, 50007
    assert [m["supplier_id"] for m in data["supplier_account_map"]] == \
        ["50001", "50002", "50003", "50004", "50005", "50006", "50007", "50099"]


# -- rule unit tests on hand-built invoice sets -----------------------------------

def decide(invoices):
    """invoices: list of sets of accounts on each invoice."""
    return saft_reader.decide_mapping(
        "S1", "Test", [{"accounts": set(acc), "vat": set()} for acc in invoices],
        {"7026": "Reparasjoner", "7155": "Bespisning/Mat"})


def test_rule_boundary_80_percent_maps():
    m = decide([{"7026"}] * 4 + [{"7155"}]).to_dict()
    assert (m["account_id"], m["share"]) == ("7026", 0.8)


def test_rule_75_percent_is_unknown():
    m = decide([{"7026"}] * 3 + [{"7155"}]).to_dict()
    assert (m["account_id"], m["reason"]) == ("unknown", "ambiguous history")


def test_rule_invoices_without_cost_account():
    m = decide([set(), set()]).to_dict()
    assert (m["account_id"], m["reason"], m["invoice_count"]) == \
        ("unknown", "no cost account on invoices", 2)


def test_rule_invoice_without_cost_line_lowers_share():
    m = decide([{"7026"}] * 3 + [set()]).to_dict()   # 3/4 = 75 %
    assert m["account_id"] == "unknown"
