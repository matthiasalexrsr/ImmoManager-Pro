"""Regenerate the PNG/Windows icon from the application's canonical SVG mark.

Uses the optional local document-tool runtime (PyMuPDF and Pillow); no build-time
or application dependency is added. Commit the generated icon assets.
"""
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = root / 'frontend/public/immomanager.svg'
with pymupdf.open(stream=source.read_bytes(), filetype='svg') as vector:
    with pymupdf.open(stream=vector.convert_to_pdf(), filetype='pdf') as pdf:
        page = pdf[0]
        raster = page.get_pixmap(matrix=pymupdf.Matrix(1024 / page.rect.width, 1024 / page.rect.height), alpha=True)
        image = Image.open(BytesIO(raster.tobytes('png')))
        image.resize((256, 256), Image.Resampling.LANCZOS).save(root / 'frontend/public/immomanager.png')
        icons = root / 'assets'
        icons.mkdir(exist_ok=True)
        image.save(icons / 'immomanager.ico', format='ICO', sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])

print('Generated the application PNG and Windows icon from its SVG.')
