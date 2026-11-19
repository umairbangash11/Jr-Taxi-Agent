import pdfplumber

pdf_path = "private_samples/bil glass.pdf"          # the scan
image_path = "private_samples/bil_glass_page1.png"   # where the picture goes

with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[0]                       # first page
    picture = page.to_image(resolution=200)   # turn the page into a picture
    picture.save(image_path)                  # save it as a .png

print("Saved:", image_path)