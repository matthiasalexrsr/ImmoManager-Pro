"""Regenerate committed installer artwork from the existing application SVG.

Optional artwork tool only (PyMuPDF/Pillow), never an installer prerequisite.
The installer contains the resulting PNGs, not these renderer dependencies.
"""
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
mark = (ROOT / "frontend/public/immomanager.svg").read_text(encoding="utf-8")
brand = '''<svg xmlns="http://www.w3.org/2000/svg" width="656" height="1256" viewBox="0 0 656 1256">
<rect width="656" height="1256" fill="#183e39"/>
<circle cx="656" cy="80" r="320" fill="#23594f" fill-opacity=".24"/>
<circle cx="-80" cy="1180" r="430" fill="#24685b" fill-opacity=".19"/>
<path d="M96 466h68" stroke="#95cdb8" stroke-width="8" stroke-linecap="round"/>
<g stroke="#80baa4" stroke-width="3" stroke-linejoin="round" fill="none" opacity=".48">
<path d="M96 1100V760l124-76 124 76v340M124 1100V784l96-58 96 58v316"/>
<path d="M344 1100V608l114-70 114 70v492M372 1100V632l86-52 86 52v468"/>
<path d="M124 846h192M124 924h192M124 1002h192M372 710h172M372 788h172M372 866h172M372 944h172M372 1022h172"/>
<path d="M188 806v296M252 806v296M429 670v430M487 670v430"/>
<path d="M72 1100h524"/>
</g>
<g fill="#b7d9c8" opacity=".16"><rect x="142" y="866" width="27" height="37" rx="3"/><rect x="270" y="944" width="27" height="37" rx="3"/><rect x="389" y="808" width="22" height="37" rx="3"/><rect x="504" y="964" width="22" height="37" rx="3"/></g>
</svg>'''


def render(svg: str, destination: Path, size: tuple[int, int]) -> None:
    with pymupdf.open(stream=svg.encode(), filetype="svg") as source:
        with pymupdf.open(stream=source.convert_to_pdf(), filetype="pdf") as pdf:
            page = pdf[0]
            raster = page.get_pixmap(matrix=pymupdf.Matrix(size[0] / page.rect.width, size[1] / page.rect.height), alpha=True)
            with Image.open(BytesIO(raster.tobytes("png"))) as image:
                image.save(destination, optimize=True)


render(brand, HERE / "wizard-brand.png", (656, 1256))
render(mark, HERE / "wizard-mark.png", (192, 192))
with Image.open(HERE / "wizard-brand.png") as background, Image.open(HERE / "wizard-mark.png") as mark_image:
    logo = mark_image.resize((224, 224), Image.Resampling.LANCZOS)
    background.paste(logo, (96, 116), logo)
    background.save(HERE / "wizard-brand.png", optimize=True)
print("Generated high-DPI installer artwork from the canonical application mark.")
