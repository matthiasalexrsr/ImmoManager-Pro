"""Isolated Pillow header/normalization worker; no application imports or writes.

Run by the bounded OCR process runner. The frozen launcher dispatches the same
entry point before loading private configuration or starting the application.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--frame", type=int)
    parser.add_argument("--max-pages", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        print(json.dumps({"error": "ocr_image_dependency_missing"}))
        return 1
    # Explicit budgets are checked in the parent before any raster is decoded.
    # Header parsing/seek and raster decoding are both inside its OS worker.
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(args.input) as image:
            if args.frame is None:
                sizes = []
                for index in range(args.max_pages + 1):
                    try:
                        image.seek(index)
                    except EOFError:
                        break
                    sizes.append(list(image.size))
                print(json.dumps({"sizes": sizes}))
            else:
                image.seek(args.frame)
                if not args.output:
                    raise ValueError("Missing output")
                # Normalize one frame at a time; retain the original source.
                with image.convert("RGB") as normalized:
                    normalized.save(Path(args.output), format="PNG")
                print(json.dumps({"normalized": True}))
        return 0
    except (UnidentifiedImageError, OSError, ValueError, EOFError):
        print(json.dumps({"error": "ocr_invalid_image"}))
        return 1
    except MemoryError:
        print(json.dumps({"error": "ocr_ram_budget"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
