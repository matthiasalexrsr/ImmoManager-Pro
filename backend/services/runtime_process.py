"""Choose a CLI host for private workers without opening a desktop console.

The desktop executable has no stdout/stderr console. Workers still need real
pipe handles and exit codes, so the windowed entry delegates to its CLI sibling
with CREATE_NO_WINDOW at the call site. A damaged installation must fail rather
than recursively opening another desktop launcher.
"""

import sys
from pathlib import Path


def frozen_cli_executable() -> str:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        companions = {"immomanager-pro.exe": "ImmoManager-Pro-CLI.exe", "immomanager-pro": "ImmoManager-Pro-CLI"}
        companion = companions.get(executable.name.casefold())
    else:
        # Source desktop launches may use pythonw.exe; its streams are None even
        # when the parent supplies pipes. Run worker commands through python.exe.
        companion = "python.exe" if executable.name.casefold() == "pythonw.exe" else None
    if companion is None:
        return sys.executable
    cli = executable.with_name(companion)
    if not cli.is_file():
        raise RuntimeError(
            f"Die Hintergrundkomponente {companion} fehlt. Bitte ImmoManager Pro erneut installieren."
        )
    return str(cli)
