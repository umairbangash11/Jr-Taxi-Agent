import json
import os

DEFAULT_SAFT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "phase-1", "saft_data.json")
)

_VAT_RATE_TO_MK = {25: "2", 0: ""}


def fmt_nok(value):
    """Format a number in Norwegian style: 2 179,80 (space=thousands, comma=decimal)."""
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", " ")


def load_saft(path=None):
    with open(path or DEFAULT_SAFT, encoding="utf-8") as f:
        return json.load(f)


def _find_supplier(saft_data, vendor_name):
    if not vendor_name:
        return None
    vendor_lower = vendor_name.lower()
    for s in saft_data.get("suppliers", []):
        name = (s.get("name") or "").lower()
        if name in ("unknown", ""):
            continue
        if name in vendor_lower or vendor_lower in name:
            return s
    return None


def _find_vat_account(saft_data, supplier_id, vat_code):
    for entry in saft_data.get("supplier_vat_account_map", []):
        if entry.get("supplier_id") == supplier_id and entry.get("vat_code") == vat_code:
            return entry
    return None


def suggest(result, saft_data):
    """Return a list of suggested journal entry rows for a checked invoice.

    Each row dict: konto, konto_name, mk, debet, kredit, needs_review, reason.
    """
    vendor = result.get("vendor") or ""
    lines = result.get("lines") or []

    supplier = _find_supplier(saft_data, vendor)
    if supplier is None:
        return [
            {
                "konto": None,
                "konto_name": None,
                "mk": None,
                "debet": None,
                "kredit": None,
                "needs_review": True,
                "reason": f"Supplier not found for vendor '{vendor}'",
            }
        ]

    supplier_id = supplier["id"]
    rows = []
    for line in lines:
        vat_rate = line.get("vat_rate")
        net_amount = line.get("net_amount")
        vat_amount = line.get("vat_amount")
        # Debet = gross (net + vat) per JR Taxi format
        if net_amount is None:
            gross = None
        else:
            gross = (net_amount or 0) + (vat_amount or 0)

        mk = _VAT_RATE_TO_MK.get(vat_rate)
        mk_unknown = mk is None
        if mk_unknown:
            mk = f"unknown({vat_rate})"

        reasons = []
        account_id = None
        account_name = None

        if mk_unknown:
            reasons.append(f"Unknown VAT rate {vat_rate}")
        else:
            entry = _find_vat_account(saft_data, supplier_id, mk)
            if entry is None:
                reasons.append(
                    f"No account mapping for supplier {supplier_id} + VAT code '{mk}'"
                )
            elif entry.get("account_id") in (None, "unknown"):
                reasons.append(
                    f"Ambiguous account for supplier {supplier_id} + VAT code '{mk}'"
                )
            else:
                account_id = entry["account_id"]
                account_name = entry.get("account_description") or ""
                if account_name == "unknown":
                    account_name = None
                    reasons.append(f"Account {account_id} description unknown")

        rows.append(
            {
                "konto": account_id,
                "konto_name": account_name,
                "mk": mk,
                "debet": gross,
                "kredit": supplier_id,
                "kredit_name": supplier.get("name") or "",
                "needs_review": bool(reasons),
                "reason": "; ".join(reasons) if reasons else None,
            }
        )

    return rows


def print_suggested_entries(rows, total_amount=None):
    W_KONTO, W_MK, W_AMT = 26, 4, 14
    SEP = "─" * (W_KONTO + 2 + W_MK + 2 + W_AMT + 2 + W_AMT + 2)

    print()
    print("Forslag til bilag:")
    print(f"  {'Konto':<{W_KONTO}} {'MK':<{W_MK}} {'Debet':>{W_AMT}}  {'Kredit':>{W_AMT}}")
    print("  " + SEP)

    debet_sum = 0.0
    any_needs_review = any(r["needs_review"] for r in rows)

    for row in rows:
        if row["needs_review"]:
            print(f"  {'MÅ SJEKKES'}")
            print(f"    Årsak: {row['reason']}")
        else:
            konto_str = f"{row['konto']} {row['konto_name']}"
            amt = row["debet"] if row["debet"] is not None else 0.0
            debet_sum += amt
            print(
                f"  {konto_str:<{W_KONTO}} {row['mk']:<{W_MK}} {fmt_nok(amt):>{W_AMT}}"
            )

    if not any_needs_review and rows:
        supplier_id = rows[0]["kredit"]
        supplier_name = rows[0].get("kredit_name") or ""
        kredit_label = f"{supplier_id} {supplier_name}".strip()
        kredit_amt = total_amount if total_amount is not None else debet_sum
        print(
            f"  {kredit_label:<{W_KONTO}} {'':>{W_MK}} {'':>{W_AMT}}  {fmt_nok(kredit_amt):>{W_AMT}}"
        )
        print("  " + SEP)
        bal_ok = abs(debet_sum - kredit_amt) < 0.005
        bal_sym = "✓" if bal_ok else "✗"
        print(
            f"  {'Sum':<{W_KONTO}} {'':>{W_MK}} {fmt_nok(debet_sum):>{W_AMT}}  {fmt_nok(kredit_amt):>{W_AMT}}  {bal_sym}"
        )
    print()
