import sys

import pypdfium2 as pdfium
import pytesseract
from PIL import ImageOps

from ingest import loaders  # noqa: F401  (sets the Tesseract location from .env)

page = pdfium.PdfDocument(sys.argv[1])[0]
img = ImageOps.grayscale(page.render(scale=300 / 72).to_pil())

for psm in (3, 4, 6, 11):
    text = pytesseract.image_to_string(img, lang="eng", config=f"--psm {psm}")
    print(f"\n===== psm {psm} =====")
    for line in text.splitlines():
        if any(ch.isdigit() for ch in line):
            print(line)