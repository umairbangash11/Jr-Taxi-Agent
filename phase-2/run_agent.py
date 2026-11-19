import json
from read_invoice import read_invoice

entry = read_invoice("samples/faktura_nio.pdf")
print("Entry:", entry)

answer = input("Approve? (y/n): ")

if answer == "y":
    try:
        with open("booked_entries.json", encoding="utf-8") as f:
            booked = json.load(f)
    except FileNotFoundError:
        booked = []

    booked.append(entry)

    with open("booked_entries.json", "w", encoding="utf-8") as f:
        json.dump(booked, f, indent=2, ensure_ascii=False)

    print("Approved and saved")
else:
    print("Not booked")