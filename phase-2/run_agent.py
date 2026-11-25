import argparse
import json
import sys

from vision_read import read_images
from check_result import check
from suggest_entry import load_saft, suggest, print_suggested_entries, fmt_nok


def _s(value):
    return str(value) if value is not None else "—"


def print_summary(result):
    check = result.get("check_status", "—")
    if check == "NEEDS REVIEW":
        check = "MÅ SJEKKES"
    print()
    print(f"Leverandør   : {result.get('vendor') or '—'}")
    print(
        f"Fakturanr    : {_s(result.get('invoice_number')):<14}  "
        f"Fakturadato: {_s(result.get('invoice_date')):<14}  "
        f"Forfallsdato: {result.get('due_date') or '—'}"
    )
    print(
        f"Totalt       : {fmt_nok(result.get('total_amount')):<16}  "
        f"MVA: {fmt_nok(result.get('vat_amount'))}"
    )
    lines = result.get("lines") or []
    label = "Linjer       :"
    for line in lines:
        rate = line.get("vat_rate")
        net  = line.get("net_amount")
        vat  = line.get("vat_amount")
        rate_str = f"{rate}%" if rate is not None else "—"
        print(f"{label} {rate_str:<6} netto {fmt_nok(net):<16}  mva {fmt_nok(vat)}")
        label = "              "
    if not lines:
        print("Linjer       : —")
    print(f"Kontroll     : {check}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Run invoice agent")
    parser.add_argument("images", nargs="+", help="Invoice image paths")
    parser.add_argument(
        "--saft",
        default=None,
        help="Path to saft_data.json (default: phase-1/saft_data.json)",
    )
    args = parser.parse_args()

    # Let the vision model read all pages of the invoice.
    answer_text = read_images(args.images)

    # Validate totals, VAT rates, and null fields.
    result = check(answer_text)

    print_summary(result)

    if result["check_status"] == "NEEDS REVIEW":
        print("MÅ SJEKKES:", result.get("check_reason", "se over"))
        sys.exit(1)

    # Only reach here when check says OK.
    saft_data = load_saft(args.saft)
    rows = suggest(result, saft_data)
    print_suggested_entries(rows, total_amount=result.get("total_amount"))

    any_needs_review = any(r["needs_review"] for r in rows)
    if any_needs_review:
        print("Inneholder linjer som MÅ SJEKKES — kan ikke bokføres.")
        sys.exit(1)
    answer = input("Godkjenn? (j/n): ").strip().lower()

    if answer in ("j", "y"):
        try:
            with open("booked_entries.json", encoding="utf-8") as f:
                booked = json.load(f)
        except FileNotFoundError:
            booked = []

        booked.append(result)

        with open("booked_entries.json", "w", encoding="utf-8") as f:
            json.dump(booked, f, indent=2, ensure_ascii=False)

        print("Godkjent og lagret")
    else:
        print("Ikke bokført")


if __name__ == "__main__":
    main()
