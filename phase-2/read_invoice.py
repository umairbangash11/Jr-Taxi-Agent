import pdfplumber
import json


def read_invoice(pdf_path):
    """Read one invoice/receipt PDF and return a suggested bilag."""

    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text()

    lines = text.split("\n")
    vendor = lines[0].replace("FAKTURA", "").replace("KVITTERING", "").strip()

    date = ""
    for line in lines:
        if "Fakturadato" in line:
            date = line.split("Forfallsdato")[0]
            date = date.replace("Fakturadato:", "").strip()

    amount = ""
    vat = ""
    for line in lines:
        if "Å betale" in line:
            amount = line
        if "MVA" in line and "%" in line:
            vat = line

    amount_text = amount.split("NOK")[1].strip().replace(" ", "").replace(",", ".")
    amount_number = float(amount_text)

    with open("phase-1/saft_data.json", encoding="utf-8") as f:
        saft = json.load(f)

    account = "unknown"
    for supplier in saft["supplier_account_map"]:
        if supplier["supplier_name"] in vendor:
            account = supplier["account_id"]
            break

    if "Betalt" in text or "Kvittering" in text:
        credit_account = "1930 Bank"
    else:
        credit_account = "2400 Leverandørgjeld"

    if account == "unknown":
        status = "NEEDS REVIEW"
    else:
        status = "READY"

    return {
        "vendor": vendor,
        "date": date,
        "amount": amount_number,
        "vat": vat,
        "debit_account": account,
        "credit_account": credit_account,
        "status": status,
    }


if __name__ == "__main__":
    result = read_invoice("samples/kvittering_onepark.pdf")
    print("Vendor:", result["vendor"])
    print("Date  :", result["date"])
    print("VAT   :", result["vat"])
    print("Amount:", result["amount"])
    print("\n--- Suggested Entry ---")
    print(f"Debit : {result['debit_account']}   {result['amount']}")
    print(f"Credit: {result['credit_account']}   {result['amount']}")
    print("\nStatus:", result["status"])