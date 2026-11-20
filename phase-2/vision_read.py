import base64
import os
import sys

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

PROMPT = """You are reading a Norwegian supplier invoice (faktura) or receipt (kvittering).
The images are the pages of ONE document, in order.
Return ONLY a JSON object with these keys:
vendor, invoice_number, invoice_date, due_date, total_amount, vat_amount, vat_rate, document_type, lines.
- vendor: the company name only, without words like FAKTURA.
- invoice_date and due_date: format DD.MM.YYYY.
- total_amount and vat_amount: money in NOK, as numbers with a dot, like 1500.00.
- vat_rate: the VAT percentage (0, 12, 15 or 25). If the invoice has more than one rate, use null.
- document_type: "faktura" or "kvittering".
- lines: one entry per VAT rate, from the VAT summary table if there is one.
  Each entry: {"vat_rate": number, "net_amount": number, "vat_amount": number}.
If you cannot read a field clearly, use null. Never guess."""


def read_images(image_paths):
    content = [{"type": "text", "text": PROMPT}]
    for path in image_paths:                                   # add every page as a picture
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        temperature=0,
        max_tokens=700,                                        # a bit more room for the lines
        messages=[{"role": "user", "content": content}],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(read_images(sys.argv[1:]))                           # all pictures given on the command line