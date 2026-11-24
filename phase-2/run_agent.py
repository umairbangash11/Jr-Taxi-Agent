import json
import sys

from vision_read import read_images
from check_result import check


def _fmt(value, width=12):
    return str(value if value is not None else "—").ljust(width)


def print_summary(result):
    print()
    print(f"Supplier : {result.get('vendor') or '—'}")
    print(
        f"Invoice  : {_fmt(result.get('invoice_number'))} "
        f"Date: {_fmt(result.get('invoice_date'), 12)} "
        f"Due: {result.get('due_date') or '—'}"
    )
    print(
        f"Total    : {_fmt(result.get('total_amount'))} "
        f"VAT: {result.get('vat_amount') or '—'}"
    )
    lines = result.get("lines") or []
    label = "Lines    :"
    for line in lines:
        rate = line.get("vat_rate")
        net  = line.get("net_amount")
        vat  = line.get("vat_amount")
        print(f"{label} {str(rate) + '%':<5} net {net:<10} vat {vat}")
        label = "          "
    if not lines:
        print("Lines    : —")
    print(f"Check    : {result.get('check_status', '—')}")
    print()


def main():
    image_paths = sys.argv[1:]
    if not image_paths:
        print("Usage: python run_agent.py <image1> [image2 ...]")
        sys.exit(1)

    # Let the vision model read all pages of the invoice.
    answer_text = read_images(image_paths)

    # Validate totals, VAT rates, and null fields.
    result = check(answer_text)

    print_summary(result)

    if result["check_status"] == "NEEDS REVIEW":
        print("NEEDS REVIEW:", result.get("check_reason", "see above"))
        sys.exit(1)

    # Only reach here when check says OK.
    answer = input("Approve? (y/n): ").strip().lower()

    if answer == "y":
        try:
            with open("booked_entries.json", encoding="utf-8") as f:
                booked = json.load(f)
        except FileNotFoundError:
            booked = []

        booked.append(result)

        with open("booked_entries.json", "w", encoding="utf-8") as f:
            json.dump(booked, f, indent=2, ensure_ascii=False)

        print("Approved and saved")
    else:
        print("Not booked")


if __name__ == "__main__":
    main()
