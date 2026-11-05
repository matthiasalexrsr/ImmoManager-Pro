"""Qt-independent boundaries for the standalone application's local web content."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

PDF_EXTENSION = "mhjfbmdgcfjbbpaeojofohoefgiehjai"


def _url(value: str):
    if not isinstance(value, str) or not value or any(ord(char) < 32 or char == "\\" for char in value):
        return None
    try:
        result = urlsplit(value)
        if result.username is not None or result.password is not None:
            return None
        _ = result.port
        return result
    except ValueError:
        return None


@dataclass(frozen=True)
class LocalOrigin:
    scheme: str
    host: str
    port: int

    @classmethod
    def from_url(cls, value: str):
        parsed = _url(value)
        if (parsed is None or parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port is None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("Die Desktop-Anwendung benötigt eine eindeutige lokale Serveradresse.")
        return cls(parsed.scheme, parsed.hostname, parsed.port)

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def key(self) -> str:
        return hashlib.sha256(self.url.encode("ascii")).hexdigest()[:24]

    def local(self, value: str) -> bool:
        parsed = _url(value)
        return bool(parsed is not None and parsed.scheme == self.scheme and parsed.hostname == self.host and parsed.port == self.port)

    def local_blob(self, value: str) -> bool:
        return value.startswith("blob:") and self.local(value[5:])

    def document(self, value: str, *, blank: bool = False) -> bool:
        return self.local(value) or self.local_blob(value) or (blank and value in {"about:blank", "about:srcdoc"})

    def resource(self, value: str) -> bool:
        if self.document(value, blank=True):
            return True
        parsed = _url(value)
        if parsed is None:
            return False
        if parsed.scheme == "ws":
            return parsed.hostname == self.host and parsed.port == self.port
        # These bytes remain inside Chromium. No arbitrary data HTML or local
        # filesystem URL is trusted, and no network host exception is introduced.
        if value.startswith("data:"):
            return bool(re.match(r"data:(?:image/|font/|application/(?:font-|octet-stream|wasm))", value, re.I))
        if parsed.scheme == "chrome-extension":
            return parsed.hostname == PDF_EXTENSION
        return value.startswith("qrc:/qtwebengine/") or value.startswith("chrome://resources/")


def external_link(value: str) -> bool:
    parsed = _url(value)
    if parsed is None:
        return False
    if parsed.scheme in {"http", "https"}:
        try:
            host = parsed.hostname.encode("idna").decode("ascii") if parsed.hostname else ""
            return bool(host and re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", host))
        except UnicodeError:
            return False
    if parsed.scheme == "mailto":
        return bool(parsed.path and "@" in parsed.path)
    return parsed.scheme == "tel" and bool(re.fullmatch(r"[+()0-9 .\-]+", parsed.path))


def suggested_filename(value: str) -> str:
    name = PureWindowsPath(str(value).replace("/", "\\")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")[:180]
    if not name or name in {".", ".."} or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name, re.I):
        return "Download"
    return name


def validate_engine_environment(environment):
    """Never inherit flags that weaken the embedded engine's security boundary."""
    if "QTWEBENGINE_DISABLE_SANDBOX" in environment or environment.get("QTWEBENGINE_REMOTE_DEBUGGING"):
        raise RuntimeError("Unsichere Qt-WebEngine-Startoptionen sind gesetzt. Bitte Sandbox- oder Debug-Ausnahmen entfernen.")
    flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    forbidden = ("--no-sandbox", "--disable-setuid-sandbox", "--single-process", "--disable-web-security",
                 "--ignore-certificate-errors", "--allow-file-access-from-files", "--remote-debugging-",
                 "--unsafely-treat-insecure-origin-as-secure")
    if any(flag in flags.lower() for flag in forbidden):
        raise RuntimeError("Die Desktop-Oberfläche startet nicht mit abgeschalteten Sicherheitsprüfungen.")
    process = environment.get("QTWEBENGINEPROCESS_PATH")
    if process and not Path(process).is_file():
        raise RuntimeError("Die mitgelieferte Desktop-Komponente QtWebEngineProcess fehlt. Bitte die Installation reparieren.")


def _private_windows_directory(path: Path):
    from ctypes import wintypes

    security = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    convert.restype = wintypes.BOOL
    get_dacl = security.GetSecurityDescriptorDacl
    get_dacl.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL))
    get_dacl.restype = wintypes.BOOL
    security.SetNamedSecurityInfoW.argtypes = (wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    security.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
    present, defaulted = wintypes.BOOL(), wintypes.BOOL()
    if not convert("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise OSError("Der private Desktopprofilordner konnte nicht geschützt werden.")
    try:
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value:
            raise OSError("Die Profilberechtigungen konnten nicht geprüft werden.")
        # Protected owner/SYSTEM DACL, with inheritable rights for new Qt files.
        code = security.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None)
        if code:
            raise OSError(code, "Der Desktopprofilordner konnte nicht geschützt werden.")
    finally:
        kernel.LocalFree(descriptor)


def profile_paths(data_dir: Path, origin: LocalOrigin) -> tuple[Path, Path]:
    root = data_dir.expanduser().resolve()
    paths = [root / "desktop-profile", root / "desktop-profile" / origin.key]
    paths += [paths[-1] / "storage", paths[-1] / "cache"]
    for path in paths:
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
                raise OSError("Der Desktopprofilordner darf keine Dateiumleitung enthalten.")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "nt":
            _private_windows_directory(path)
        else:
            path.chmod(0o700)
        if not path.resolve().is_relative_to(root):
            raise OSError("Der Desktopprofilordner liegt außerhalb des Datenordners.")
    return paths[-2], paths[-1]
