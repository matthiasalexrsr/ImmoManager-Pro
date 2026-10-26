"""Fail-closed local KoSIT/Mustang adapter with a deny-by-default Java policy.

The process inherits no application credentials. It can read only its pinned
bundle and private work directory, cannot open sockets, and is killed as an
owned process tree on timeout or output overflow. Uploaded markup is never used
as a command, path, schema selection or HTML response.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from ...config import settings
from ..assistant_provider_process import CliProcess
from ..safe_xml import fromstring

MAX_REPORT = 4 * 1024 * 1024


class ValidatorUnavailable(RuntimeError):
    pass


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bundle() -> tuple[Path, dict, str]:
    if not settings.e_invoice_bundle:
        raise ValidatorUnavailable("Das lokale E-Rechnung-Prüfpaket ist nicht eingerichtet.")
    root = Path(settings.e_invoice_bundle).resolve()
    try:
        manifest_raw = (root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        expected = json.loads(Path(__file__).with_name("assets.json").read_text(encoding="utf-8"))
        if manifest["assets"] != expected["assets"] or manifest["format"] != expected["format"]:
            raise ValueError("unreviewed assets")
        for asset in expected["assets"]:
            if file_sha(root / asset["filename"]) != asset["sha256"]:
                raise ValueError("asset checksum")
        # Includes extracted schemas, policies, resources and executable runtime.
        # Reject symlinks, traversal and additional code/rules not in the manifest.
        present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"}
        if present != set(manifest["files"]):
            raise ValueError("bundle inventory")
        for name, checksum in manifest["files"].items():
            path = root / name
            if not path.resolve().is_relative_to(root) or path.is_symlink() or file_sha(path) != checksum:
                raise ValueError("bundle checksum")
        # Compare the extracted bytes to the pinned ZIPs as well: modifying a
        # manifest cannot bless a substituted executable or XSL rule.
        from zipfile import ZipFile
        expected_files = {asset["filename"]: asset["sha256"] for asset in expected["assets"]}
        for asset in expected["assets"]:
            if "resource_directory" in asset:
                with ZipFile(root / asset["filename"]) as archive:
                    for entry in archive.infolist():
                        if not entry.is_dir() and entry.filename.startswith(tuple(asset["resource_prefixes"])):
                            name = asset["resource_directory"] + "/" + entry.filename
                            expected_files[name] = hashlib.sha256(archive.read(entry)).hexdigest()
                            if manifest["files"].get(name) != expected_files[name]:
                                raise ValueError("extracted resource checksum")
            if "extract" not in asset:
                continue
            with ZipFile(root / asset["filename"]) as archive:
                for entry in archive.infolist():
                    if not entry.is_dir():
                        name = asset["extract"] + "/" + entry.filename
                        expected_files[name] = hashlib.sha256(archive.read(entry)).hexdigest()
                        if manifest["files"].get(name) != expected_files[name]:
                            raise ValueError("extracted release checksum")
        if manifest["files"] != expected_files:
            raise ValueError("unreviewed bundle contents")
        return root, manifest, hashlib.sha256(manifest_raw).hexdigest()
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
        'permission java.lang.RuntimePermission "*";',
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
    version = "1.6.3 / XRechnung 3.0.2-2026-08-31" if engine == "kosit" else "2.26.0"
    digest = ""
    try:
        root, _manifest, digest = bundle()
        javas = list((root / "runtime").rglob("java.exe" if os.name == "nt" else "java"))
        if len(javas) != 1:
            raise ValidatorUnavailable("Die gepinnte Java-Laufzeit fehlt oder ist nicht eindeutig.")
        with tempfile.TemporaryDirectory(prefix="immo-e-invoice-") as directory:
            work = Path(directory)
            source = work / ("invoice.pdf" if container == "pdf" else "invoice.xml")
            source.write_bytes(content)
            policy = work / "validator.policy"
            policy.write_text(_policy(root, work), encoding="utf-8")
            argv = [str(javas[0]), "-Xmx384m", "-XX:MaxMetaspaceSize=128m", "-XX:MaxDirectMemorySize=64m",
                    "-Dfile.encoding=UTF-8", "-Djava.awt.headless=true", f"-Djava.io.tmpdir={work}",
                    f"-Duser.home={work}", "-Djava.security.manager", f"-Djava.security.policy=={policy.as_uri()}",
                    "-Djavax.xml.accessExternalDTD=", "-Djavax.xml.accessExternalSchema=file,jar",
                    "-Djavax.xml.accessExternalStylesheet=file,jar"]
            if engine == "kosit":
                argv += ["-jar", str(root / "validator-1.6.3-standalone.jar"), "-s", str(root / "rules/scenarios.xml"),
                         "-r", str(root / "rules"), "-o", str(work), str(source)]
            else:
                # veraPDF checks CMaps as filesystem paths before trying jar
                # streams. Put identical, hash-verified resources first, avoiding
                # invalid Windows jar pseudo-paths without opening filesystem access.
                argv += ["-cp", os.pathsep.join([str(root / "mustang-resources"), str(root / "Mustang-CLI-2.26.0.jar")]),
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
