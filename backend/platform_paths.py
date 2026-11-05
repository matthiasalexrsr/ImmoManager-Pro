"""Native per-user desktop locations without importing application settings.

This module is safe for GUI bootstrap and CLI setup before backend.config is
loaded. Explicit DATA_DIR/CLI choices are handled by their callers; defaults
never depend on the working directory or a writable installation folder.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

APP_DIR_NAME = "ImmoManagerPro"


def default_user_data_dir(*, testversion: bool = False, platform: str | None = None,
                          environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    platform = sys.platform if platform is None else platform
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)
    name = APP_DIR_NAME + ("-Testversion" if testversion else "")
    if platform == "win32":
        configured = environment.get("LOCALAPPDATA", "")
        base = Path(configured) if configured and PureWindowsPath(configured).is_absolute() else user_home / "AppData" / "Local"
        return base / name
    if platform == "darwin":
        return user_home / "Library" / "Application Support" / name
    # The XDG specification requires an absolute value; a relative one must not
    # accidentally create a database below whichever folder launched the app.
    configured = environment.get("XDG_DATA_HOME", "")
    base = Path(configured) if configured and PurePosixPath(configured).is_absolute() else user_home / ".local" / "share"
    return base / name
