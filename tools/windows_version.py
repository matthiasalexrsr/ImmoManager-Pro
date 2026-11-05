"""Explorer version metadata derived from the application's authoritative version."""

import re
import tomllib
from pathlib import Path


def version_fields(root: Path, filename: str, description: str) -> dict:
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(.*)", version)
    if not match or any(int(part) > 65535 for part in match.groups()[:3]):
        raise ValueError("Application version cannot be represented in a Windows version resource")
    number = (*map(int, match.groups()[:3]), 0)
    return {"number": number, "prerelease": bool(match.group(4)), "strings": {
        "CompanyName": "ImmoManager Pro", "ProductName": "ImmoManager Pro", "ProductVersion": version,
        "FileVersion": ".".join(map(str, number)), "FileDescription": description,
        "OriginalFilename": filename, "InternalName": Path(filename).stem,
    }}


def version_resource(root: Path, filename: str, description: str):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    data = version_fields(root, filename, description)
    return VSVersionInfo(ffi=FixedFileInfo(filevers=data["number"], prodvers=data["number"],
        mask=0x3F, flags=2 if data["prerelease"] else 0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040704B0", [StringStruct(key, value) for key, value in data["strings"].items()])]),
              VarFileInfo([VarStruct("Translation", [0x0407, 1200])])])
