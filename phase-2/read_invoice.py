import pdfplumber
import json

# --- read the PDF ---
with pdfplumber.open("samples/kvittering_onepark.pdf") as pdf:   # open the NIO invoice
    text = pdf.pages[0].extract_text()                    # get all text from page 1

lines = text.split("\n")                      # split text into a list of lines
vendor = lines[0].replace("FAKTURA", "").strip()   # vendor = first line (cleaned)

# --- get the date ---
date = ""
for line in lines:
    if "Fakturadato" in line:
        date = line.split("Forfallsdato")[0]            # take part before Forfallsdato
        date = date.replace("Fakturadato:", "").strip() # remove the label

# --- get amount + VAT lines ---
amount = ""
vat = ""
for line in lines:
    if "Å betale" in line:
        amount = line
    if "MVA" in line and "%" in line:   # must have MVA AND % (real VAT line)
        vat = line

print("Vendor:", vendor)
print("Date  :", date)
print("Amount:", amount)
print("VAT   :", vat)

# --- turn amount text into a real number ---
amount_text = amount.split("NOK")[1]        # part after "NOK"
amount_text = amount_text.strip()           # remove spaces at ends
amount_text = amount_text.replace(" ", "")  # remove space in "6 000"
amount_text = amount_text.replace(",", ".") # comma → dot for Python
amount_number = float(amount_text)          # text → number
print("Amount as number:", amount_number)

# --- look up the account from Phase 1's brain ---
with open("phase-1/saft_data.json", encoding="utf-8") as f:
    saft = json.load(f)                     # load what Phase 1 learned

account = "unknown"                             # start unknown (don't guess!)
for supplier in saft["supplier_account_map"]:   # go through learned suppliers
    if supplier["supplier_name"] in vendor:     # name matches our vendor?
        account = supplier["account_id"]        # found → use that account
        break

# --- build the entry (bilag) ---
debit_account = account                   # the expense account

if "Betalt" in text or "Kvittering" in text:   # paid already?
    credit_account = "1930 Bank"                # yes → money left the bank
else:
    credit_account = "2400 Leverandørgjeld"     # no → we still owe supplier

print("\n--- Suggested Entry ---")
print(f"Debit : {debit_account}   {amount_number}")
print(f"Credit: {credit_account}   {amount_number}")

# --- balance check ---
if amount_number == amount_number:
    print("Balanced: YES ✅")
else:
    print("Balanced: NO ❌")

# --- status: ready or needs human? ---
if account == "unknown":
    status = "NEEDS REVIEW ⚠️  (account unknown - human must check)"
else:
    status = "READY ✅  (account found, balanced)"

print("\nStatus:", status)

