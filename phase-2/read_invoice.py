import pdfplumber
import json


def read_invoice(pdf_path, saft_path="phase-1/saft_data.json"):
    """Read one invoice/receipt PDF and return a suggested bilag."""

    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text()

    if not text or not text.strip():
        return {
            "vendor": "", "date": "", "invoice_number": "",
            "amount": 0.0, "vat": "",
            "debit_account": "unknown", "supplier_id": "",
            "credit_account": "",
            "status": "NEEDS REVIEW: scanned document, no text",
        }

    lines = text.split("\n")
    vendor = lines[0].replace("FAKTURA", "").replace("KVITTERING", "").strip()

    date = ""
    for line in lines:
        if "Fakturadato" in line:
            date = line.split("Forfallsdato")[0]
            date = date.replace("Fakturadato:", "").strip()

    invoice_number = ""
    for line in lines:
        if "Fakturanr" in line:
            invoice_number = line.replace("Fakturanr:", "").strip()

    amount = ""
    vat = ""
    for line in lines:
        if "Å betale" in line:
            amount = line
        if "MVA" in line and "%" in line:
            vat = line

    amount_text = amount.split("NOK")[1].strip().replace(" ", "").replace(",", ".")
    amount_number = float(amount_text)

    with open(saft_path, encoding="utf-8") as f:
        saft = json.load(f)

    account = "unknown"
    supplier_id = ""
    for supplier in saft["supplier_account_map"]:
        if supplier["supplier_name"] in vendor:
            account = supplier["account_id"]
            supplier_id = supplier["supplier_id"]
            break

    if "KVITTERING" in text.upper():
        credit_account = "1930 Bank"
    elif supplier_id:
        credit_account = f"{supplier_id} - {vendor}"
    else:
        credit_account = "2400 Leverandørgjeld"

    if account == "unknown":
        status = "NEEDS REVIEW"
    else:
        status = "READY"

    return {
        "vendor": vendor,
        "date": date,
        "invoice_number": invoice_number,
        "amount": amount_number,
        "vat": vat,
        "debit_account": account,
        "supplier_id": supplier_id,
        "credit_account": credit_account,
        "status": status,
    }


if __name__ == "__main__":
    result = read_invoice("samples/faktura_nio.pdf")
    print("Vendor :", result["vendor"])
    print("Date   :", result["date"])
    print("Fakt.nr:", result["invoice_number"])
    print("Amount :", result["amount"])
    print("VAT    :", result["vat"])
    print("\n--- Suggested Entry ---")
    print(f"Debit : {result['debit_account']}   {result['amount']}")
    print(f"Credit: {result['credit_account']}   {result['amount']}")
    print("\nStatus:", result["status"])