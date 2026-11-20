import base64
import os
import sys

from dotenv import load_dotenv
from groq import Groq

load_dotenv()                                   # reads GROQ_API_KEY from .env

PROMPT = """You are reading a Norwegian supplier invoice (faktura) or receipt (kvittering).
Return ONLY a JSON object with these keys:
vendor, invoice_number, invoice_date, due_date, total_amount, vat_amount, vat_rate, document_type.
document_type is "faktura" or "kvittering".
Write amounts as numbers with a dot, like 1500.00.
If you cannot read a field clearly, use null. Never guess."""


def read_image(image_path):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")   # picture -> text Groq can receive

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",                                         # the best model for reading invoices
        temperature=0,                                     # same answer every time, less creativity
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(read_image(sys.argv[1]))

# import base64
# import os
# import sys

# from dotenv import load_dotenv
# from groq import Groq

# load_dotenv()

# with open(sys.argv[1], "rb") as f:
#     b64 = base64.b64encode(f.read()).decode("utf-8")

# client = Groq(api_key=os.environ["GROQ_API_KEY"])
# response = client.chat.completions.create(
#     model="qwen/qwen3.8-27b",
#     messages=[{
#         "role": "user",
#         "content": [
#             {"type": "text", "text": "Write out all the text you can see in this image."},
#             {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
#         ],
#     }],
# )
# print(response.choices[0].message.content)