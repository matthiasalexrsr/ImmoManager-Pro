"""Fail-closed local KoSIT/Mustang adapter with a deny-by-default Java policy.

The process inherits no application credentials. It can read only its pinned
bundle and private work directory, cannot open sockets, and is killed as an
owned process tree on timeout or output overflow. Uploaded markup is never used
as a command, path, schema selection or HTML response.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ...config import settings
from ..assistant_provider_process import CliProcess
from ..filesystem_paths import filesystem_path
from ..safe_xml import fromstring
from .asset_bundle import safe_name
from .asset_bundle import verify as verify_bundle

MAX_REPORT = 4 * 1024 * 1024
# The JDK's Windows launcher still bounds the path to bin/server/jvm.dll,
# independently of Python/Windows extended-path support. Leave room below
# MAX_PATH for all native launcher suffixes and the terminating NUL.
MAX_JAVA_NATIVE_PATH = 240


class ValidatorUnavailable(RuntimeError):
    pass


def _windows_display_path(path: str | Path) -> Path:
    """Remove the I/O-only prefix; do not resolve an 8.3 alias back to long form."""
    value = str(path)
    if value.startswith('\\\\?\\UNC\\'):
        return Path('\\\\' + value[8:])
    return Path(value[4:] if value.startswith('\\\\?\\') else value)


def _local_windows_path(path: Path) -> bool:
    return path.is_absolute() and len(path.drive) == 2 and path.drive[1] == ':'


def _short_windows_path(path: Path) -> Path | None:
    """Use an existing alias only. No global mapping, rename or 8.3 setting."""
    import ctypes
    from ctypes import wintypes

    kernel = getattr(ctypes, 'WinDLL')('kernel32', use_last_error=True)
    short_name = kernel.GetShortPathNameW
    short_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    short_name.restype = wintypes.DWORD
    source = str(filesystem_path(path))
    required = short_name(source, None, 0)
    if not required or required > 32768:
        return None
    buffer = ctypes.create_unicode_buffer(required)
    written = short_name(source, buffer, required)
    if not written or written >= required:
        return None
    candidate = _windows_display_path(buffer.value)
    try:
        if _local_windows_path(candidate) and filesystem_path(candidate).samefile(filesystem_path(path)):
            return candidate
    except OSError:
        pass
    return None


def _native_path_fits(path: Path) -> bool:
    return _local_windows_path(path) and len(str(path).encode('utf-16-le')) // 2 < MAX_JAVA_NATIVE_PATH


def _runtime_path_fits(root: Path, java_relative: Path) -> bool:
    java = root / java_relative
    return _native_path_fits(java) and _native_path_fits(java.parent / 'server/jvm.dll')


def _protect_windows_directory(path: Path) -> None:
    """Protect the newly created empty directory before copying or writing.

    Explicit inheritable owner/SYSTEM rights also cover Python 3.11/3.12,
    where mkdir(mode=0o700) alone does not install a private Windows DACL.
    """
    import ctypes
    from ctypes import wintypes

    security = getattr(ctypes, 'WinDLL')('advapi32', use_last_error=True)
    kernel = getattr(ctypes, 'WinDLL')('kernel32', use_last_error=True)
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = security.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_security = security.SetNamedSecurityInfoW
    set_security.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_security.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
    present, defaulted = wintypes.BOOL(), wintypes.BOOL()
    if not convert('D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)', 1, ctypes.byref(descriptor), None):
        raise ValidatorUnavailable('Der private Windows-Prüfordner konnte nicht geschützt werden.')
    try:
        if (not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
                or not present.value or not dacl.value
                or set_security(str(filesystem_path(path)), 1, 0x80000004, None, None, dacl, None) != 0):
            raise ValidatorUnavailable('Der private Windows-Prüfordner konnte nicht geschützt werden.')
    finally:
        kernel.LocalFree(descriptor)


def _copy_verified_bundle(root: Path, destination: Path, manifest: dict, digest: str) -> None:
    """Copy only the pinned inventory, then verify every archive/extracted byte.

    A newly added file in the source tree is never copied. Changed files or
    links fail the second verification before any Java process is launched.
    """
    target = filesystem_path(destination)
    try:
        target.mkdir()
        for name in ('manifest.json', *manifest['files']):
            relative = safe_name(name)
            source = filesystem_path(root / relative)
            if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
                raise ValueError('Bundle links are forbidden')
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output, follow_symlinks=False)
        copied_manifest, copied_digest = verify_bundle(destination)
        if copied_manifest != manifest or copied_digest != digest:
            raise ValueError('Copied bundle differs from the verified source')
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidatorUnavailable('Die temporäre Kopie des Prüfpakets konnte nicht vollständig geprüft werden.') from None


@contextmanager
def _execution_paths(root: Path, manifest: dict, digest: str, java_relative: Path) -> Iterator[tuple[Path, Path]]:
    if os.name != 'nt':
        with tempfile.TemporaryDirectory(prefix='immo-e-invoice-') as directory:
            yield root, Path(directory)
        return

    try:
        temp_base = _windows_display_path(tempfile.gettempdir())
    except OSError:
        raise ValidatorUnavailable('Der lokale TEMP/TMP-Prüfordner ist nicht verfügbar oder nicht beschreibbar.') from None
    if not _local_windows_path(temp_base):
        raise ValidatorUnavailable('Für die lokale Prüfung muss TEMP/TMP auf einen beschreibbaren lokalen Ordner zeigen.')
    # Python's extended path is retained by TemporaryDirectory for reliable
    # cleanup; only the Java-facing paths use the ordinary/8.3 spelling.
    try:
        temporary = tempfile.TemporaryDirectory(prefix='imv-', dir=filesystem_path(temp_base))
    except OSError:
        raise ValidatorUnavailable('Der lokale TEMP/TMP-Prüfordner ist nicht verfügbar oder nicht beschreibbar.') from None
    with temporary as directory:
        owned = _windows_display_path(directory)
        _protect_windows_directory(owned)
        short_owned = _short_windows_path(owned) or owned
        work = short_owned / 'w'
        if not _native_path_fits(work / 'validator.policy'):
            raise ValidatorUnavailable('Der temporäre Prüfpfad ist zu lang. Bitte TEMP/TMP auf einen kürzeren lokalen Ordner setzen.')
        filesystem_path(work).mkdir()
        execution_root = root
        if not _runtime_path_fits(execution_root, java_relative):
            alias = _short_windows_path(root)
            if alias is not None and _runtime_path_fits(alias, java_relative):
                execution_root = alias
            else:
                execution_root = short_owned / 'b'
                if not _runtime_path_fits(execution_root, java_relative):
                    raise ValidatorUnavailable('Die Java-Laufzeit benötigt einen kürzeren Prüfpfad. Bitte TEMP/TMP auf einen kürzeren lokalen Ordner setzen.')
                _copy_verified_bundle(root, execution_root, manifest, digest)
        yield execution_root, work


def bundle() -> tuple[Path, dict, str]:
    if not settings.e_invoice_bundle:
        raise ValidatorUnavailable("Das lokale E-Rechnung-Prüfpaket ist nicht eingerichtet.")
    root = Path(settings.e_invoice_bundle).resolve()
    try:
        manifest, digest = verify_bundle(root)
        return root, manifest, digest
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidatorUnavailable("Das Prüfpaket fehlt, ist unvollständig oder seine Prüfsummen stimmen nicht.") from None


def _policy(root: Path, work: Path) -> str:
    def quoted(path: Path) -> str:
        return json.dumps(path.as_posix() + "/-")
    return "\n".join([
        "grant {",
        f'permission java.io.FilePermission {json.dumps(root.as_posix())}, "read";',
        f'permission java.io.FilePermission {json.dumps(work.as_posix())}, "read,write,delete";',
        f'permission java.io.FilePermission {quoted(root)}, "read";',
        f'permission java.io.FilePermission {quoted(work)}, "read,write,delete";',
        'permission java.util.PropertyPermission "*", "read,write";',
        *[f'permission java.lang.RuntimePermission "{name}";' for name in (
            "accessDeclaredMembers", "getClassLoader", "createClassLoader", "accessClassInPackage.*",
            "accessSystemModules", "loadLibrary.*", "modifyThread", "modifyThreadGroup", "getProtectionDomain",
            "getenv.*", "setContextClassLoader", "shutdownHooks", "exitVM.*", "readFileDescriptor",
            "writeFileDescriptor", "setIO")],
        'permission java.lang.reflect.ReflectPermission "suppressAccessChecks";',
        'permission java.security.SecurityPermission "getProperty.*";',
        'permission java.util.logging.LoggingPermission "control";',
        'permission javax.management.MBeanServerPermission "createMBeanServer";',
        "};",
    ])


def _run(argv: list[str], profile: Path, *, environment: dict[str, str] | None = None) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}}
    env.update(TEMP=str(profile), TMP=str(profile), HOME=str(profile), USERPROFILE=str(profile), LANG="C.UTF-8")
    env.update(environment or {})
    if os.name != 'nt':
        # A child exec wrapper avoids unsafe preexec_fn in the multithreaded
        # API process. CPU, address space, output files and open FDs are bounded.
        mode = 'java' if Path(argv[0]).name == 'java' else 'extract'
        wrapper = ([sys.executable, 'e-invoice-limit-worker'] if getattr(sys, 'frozen', False) else
                   [sys.executable, '-m', 'backend.services.e_invoice.posix_worker'])
        env.update(E_INVOICE_LIMIT_DIR=str(profile), PYTHONPATH=str(Path(__file__).resolve().parents[3]))
        argv = [*wrapper, str(profile), mode, str(settings.e_invoice_timeout_seconds), *argv]
    outputs: dict[str, list[str]] = {"stdout": [], "stderr": []}
    size = 0
    closed: set[str] = set()
    deadline = time.monotonic() + settings.e_invoice_timeout_seconds
    with CliProcess(argv, profile, env=env, memory_limit_bytes=768 * 1024 * 1024) as process:
        # KoSIT checks stdin.available(); a closed pipe works on Windows where
        # DEVNULL/console handles can raise 'Invalid function'.
        assert process.process.stdin is not None
        process.process.stdin.close()
        while len(closed) < 2:
            if time.monotonic() > deadline:
                raise ValidatorUnavailable("Die lokale Prüfung hat ihr Zeitlimit überschritten.")
            item = process.next_line(.1)
            if item is None:
                continue
            channel, line = item
            if channel.endswith("_closed"):
                closed.add(channel)
                continue
            size += len(line.encode("utf-8"))
            if size > MAX_REPORT:
                raise ValidatorUnavailable("Der Prüfbericht überschreitet die zulässige Größe.")
            outputs[channel].append(line)
        code = process.process.wait(timeout=5)
    return code, "".join(outputs["stdout"]), "".join(outputs["stderr"])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_report(report: str, engine: str) -> tuple[str, list[dict]]:
    if not report or len(report.encode("utf-8")) > MAX_REPORT:
        raise ValidatorUnavailable("Der Validator hat keinen vollständigen Prüfbericht geliefert.")
    try:
        root = fromstring(report)
    except Exception:
        raise ValidatorUnavailable("Der lokale Prüfbericht ist nicht auswertbar.") from None
    messages = []
    if engine == "mustang":
        summary = root.find("summary")
        if root.tag != "validation" or summary is None:
            raise ValidatorUnavailable("Der Mustang-Abschlussnachweis fehlt.")
        state = summary.get("status")
        if state not in {"valid", "invalid"}:
            raise ValidatorUnavailable("Unbekannter Mustang-Prüfstatus.")
        for node in root.iter():
            if node.tag in {"error", "fatal", "warning", "notice"}:
                messages.append({"severity": node.tag, "code": node.get("type", ""),
                                 "location": node.get("location", ""), "text": "".join(node.itertext()).strip()})
    else:
        ns = "http://www.xoev.de/de/validator/varl/1"
        # Accept only the official namespace/assessment, never a similarly named
        # element embedded in the source invoice or the HTML reading.
        assessments = root.findall(".//{" + ns + "}assessment")
        if _local(root.tag) != "report" or len(assessments) != 1:
            raise ValidatorUnavailable("Der KoSIT-Abschlussnachweis fehlt.")
        accepted = assessments[0].find("{" + ns + "}accept") is not None
        rejected = assessments[0].find("{" + ns + "}reject") is not None
        if accepted == rejected:
            raise ValidatorUnavailable("Der KoSIT-Prüfstatus ist nicht eindeutig.")
        state = "valid" if accepted else "invalid"
        for node in root.iter():
            if _local(node.tag) in {"failed-assert", "message"}:
                severity = node.get("flag") or node.get("severity") or "error"
                messages.append({"severity": severity, "code": node.get("id", ""),
                                 "location": node.get("location", ""), "text": "".join(node.itertext()).strip()})
    if state == "valid" and messages:
        state = "warning"
    return state, messages


def validate(content: bytes, container: str, invoice_format: str) -> dict:
    engine = "kosit" if invoice_format == "xrechnung" else "mustang"
    version = "1.6.3 immo1 / XRechnung 3.0.2-2026-08-31" if engine == "kosit" else "2.26.0 immo1"
    digest = ""
    try:
        root, manifest, digest = bundle()
        assets = {asset["name"]: asset for asset in manifest["assets"]}
        javas = list((filesystem_path(root) / "runtime").rglob("java.exe" if os.name == "nt" else "java"))
        if len(javas) != 1:
            raise ValidatorUnavailable("Die gepinnte Java-Laufzeit fehlt oder ist nicht eindeutig.")
        java_relative = javas[0].relative_to(filesystem_path(root))
        with _execution_paths(root, manifest, digest, java_relative) as (root, work):
            source = work / ("invoice.pdf" if container == "pdf" else "invoice.xml")
            source.write_bytes(content)
            policy = work / "validator.policy"
            policy.write_text(_policy(root, work), encoding="utf-8")
            argv = [str(root / java_relative), "-Xmx384m", "-XX:MaxMetaspaceSize=128m", "-XX:MaxDirectMemorySize=64m",
                    "-XX:CompressedClassSpaceSize=64m", "-XX:ReservedCodeCacheSize=64m", "-XX:ActiveProcessorCount=2", "-XX:+UseSerialGC",
                    "-Dfile.encoding=UTF-8", "-Djava.awt.headless=true", f"-Djava.io.tmpdir={work}",
                    f"-Duser.home={work}", "-Djava.security.manager", f"-Djava.security.policy=={policy.as_uri()}",
                    "-Djavax.xml.accessExternalDTD=", "-Djavax.xml.accessExternalSchema=file,jar",
                    "-Djavax.xml.accessExternalStylesheet=file,jar"]
            if engine == "kosit":
                argv += ["-jar", str(root / assets["kosit"]["filename"]), "-s", str(root / "rules/scenarios.xml"),
                         "-r", str(root / "rules"), "-o", str(work), str(source)]
            else:
                # veraPDF checks CMaps as filesystem paths before trying jar
                # streams. Put identical, hash-verified resources first, avoiding
                # invalid Windows jar pseudo-paths without opening filesystem access.
                argv += ["-cp", os.pathsep.join([str(root / "mustang-resources"), str(root / assets["mustang"]["filename"])]),
                         "org.mustangproject.commandline.Main", "--action", "validate", "--source", str(source),
                         "--disable-file-logging"]
            code, stdout, stderr = _run(argv, work)
            if engine == "kosit":
                reports = [p for p in work.glob("*.xml") if p != source]
                if len(reports) != 1 or reports[0].stat().st_size > MAX_REPORT:
                    raise ValidatorUnavailable("KoSIT hat keinen eindeutigen Prüfbericht erzeugt.")
                report = reports[0].read_text(encoding="utf-8")
            else:
                start, end = stdout.find("<validation"), stdout.rfind("</validation>")
                if start < 0 or end < start:
                    raise ValidatorUnavailable("Mustang hat keinen vollständigen Prüfbericht erzeugt.")
                report = stdout[start:end + len("</validation>")]
            state, messages = parse_report(report, engine)
            # Some validators return nonzero for an invalid invoice. A purported
            # success plus a failed process is always a technical failure.
            if code != 0 and state != "invalid":
                raise ValidatorUnavailable("Der Validator wurde ohne sicheren Abschluss beendet.")
            if "AccessControlException" in stderr:
                raise ValidatorUnavailable("Der Validator hat einen gesperrten Zugriff versucht.")
            return {"engine": engine, "engine_version": version, "bundle_sha256": digest,
                    "state": state, "messages": messages, "report": report}
    except Exception as error:
        message = str(error) if isinstance(error, ValidatorUnavailable) else "Die lokale Prüfung wurde technisch unterbrochen."
        return {"engine": engine, "engine_version": version, "bundle_sha256": digest,
                "state": "technical_error", "messages": [{"severity": "technical_error", "text": message}], "report": ""}
