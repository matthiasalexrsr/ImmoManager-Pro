"""Internal child-process entry point; never starts a server or opens a database."""
import json
import os
import sys

from fastapi import HTTPException

from .document_pdf import inspect_pdf, transform, validate_annotations
from .filesystem_paths import filesystem_path


def main(folder_argument: str | None = None):
    folder = filesystem_path(folder_argument or sys.argv[1]).resolve(strict=True)
    owned = os.environ.get('IMMO_PDF_WORK_DIR')
    if (not owned or folder != filesystem_path(owned).resolve(strict=True)
            or not folder.name.startswith('work-') or folder.parent.name != 'document-pdf-jobs'):
        raise RuntimeError("Owned PDF work folder required")
    request = json.loads((folder / "input.json").read_text(encoding="utf-8"))
    content = (folder / "source.pdf").read_bytes()
    try:
        if request["action"] == "inspect":
            result = {"result": inspect_pdf(content, **request["options"])}
        elif request["action"] == "validate_annotations":
            validate_annotations(content, request["annotations"])
            result = {"result": {"valid": True}}
        else:
            extras = [(folder / f"extra-{index}.pdf").read_bytes() for index in range(request["extra_count"])]
            outputs = transform(content, request["action"], request["options"], extras, request["annotations"])
            result = {"outputs": []}
            for index, (name, _media, value) in enumerate(outputs):
                (folder / f"output-{index}.pdf").write_bytes(value)
                result["outputs"].append({"filename": name})
    except HTTPException as error:
        result = {"status": error.status_code, "error": str(error.detail)}
    except Exception:
        result = {"status": 422, "error": "Das PDF konnte nicht verarbeitet werden. Bitte Eingabedatei und Werkzeugangaben prüfen."}
    temporary = folder / "result.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, folder / "result.json")


if __name__ == "__main__":
    main()
