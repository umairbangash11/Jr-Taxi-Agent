"""Validates the JSON answer produced by vision_read and returns a status."""

import json
import re


VALID_VAT_RATES = {0, 12, 15, 25}
ROUNDING_TOLERANCE = 0.05


def check(answer_text: str) -> dict:
    # Strip ```json fences so raw LLM output is accepted without crashing.
    cleaned = re.sub(r"```(?:json)?", "", answer_text).strip().strip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"check_status": "NEEDS REVIEW", "check_reason": "Response is not valid JSON"}

    # Null or missing top-level total cannot be validated; flag immediately.
    if data.get("total_amount") is None:
        data["check_status"] = "NEEDS REVIEW"
        data["check_reason"] = "total_amount is null or missing"
        return data

    lines = data.get("lines", [])

    # Each line must use an allowed VAT rate; anything else signals a parse error.
    for line in lines:
        rate = line.get("vat_rate")
        if rate not in VALID_VAT_RATES:
            data["check_status"] = "NEEDS REVIEW"
            data["check_reason"] = f"Invalid vat_rate {rate!r}; must be one of {sorted(VALID_VAT_RATES)}"
            return data

    # Null net_amount or vat_amount on any line means the extraction failed.
    for i, line in enumerate(lines):
        for field in ("net_amount", "vat_amount"):
            if line.get(field) is None:
                data["check_status"] = "NEEDS REVIEW"
                data["check_reason"] = f"Line {i}: {field} is null or missing"
                return data

    # The sum of (net + vat) across all lines must equal the invoice total.
    computed_total = sum(
        float(line["net_amount"]) + float(line["vat_amount"])
        for line in lines
    )
    stated_total = float(data["total_amount"])
    if abs(computed_total - stated_total) > ROUNDING_TOLERANCE:
        data["check_status"] = "NEEDS REVIEW"
        data["check_reason"] = (
            f"Line totals {computed_total:.2f} do not match total_amount {stated_total:.2f}"
        )
        return data

    data["check_status"] = "OK"
    return data

if __name__ == "__main__":
    import sys
    from vision_read import read_images

    answer = read_images(sys.argv[1:])      # AI reads the picture(s)
    result = check(answer)                  # our code checks the answer
    print("Status:", result["check_status"])
    if "check_reason" in result:
        print("Reason:", result["check_reason"])
