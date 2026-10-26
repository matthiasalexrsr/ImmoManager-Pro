"""Actual old/new Windows bundles: upgrade, full restore and fresh customer reimport."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.filesystem_paths import filesystem_path  # noqa: E402
from scripts.run_daily_browser_qa import BinaryServer  # noqa: E402
from scripts.run_integration_browser_qa import Binary, seed  # noqa: E402
from tools.xstress.core import Client, Findings, fresh_directory, setup_users  # noqa: E402


def last_json(text):
    decoder = json.JSONDecoder()
    values = []
    for offset in range(len(text)):
        if text[offset] == "{" and (offset == 0 or text[offset - 1] == "\n"):
            try:
                value, _ = decoder.raw_decode(text[offset:])
                if isinstance(value, dict):
                    values.append(value)
            except ValueError:
                pass
    return values[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    binary, previous = args.binary.resolve(strict=True), args.previous.resolve(strict=True)
    assert all(p.is_relative_to(ROOT) for p in (binary, previous))
    output = fresh_directory(ROOT / "artifacts/integrated-ops", "windows")
    servers, clients, checks = [], [], []
    findings = Findings()
    print("RESULT_DIR=" + str(output), flush=True)

    def check(name):
        checks.append({"name": name, "passed": True})
        print("PASS " + name, flush=True)

    def call(client, method, route, data=None, **kw):
        response = client.http.request(
            method,
            client.server.base + route,
            json=data,
            headers={"Authorization": "Bearer " + client.token, **kw.pop("headers", {})},
            **kw,
        )
        assert response.is_success, (method, route, response.status_code, response.text[:600])
        return response.json()

    def cmd(server, label, *arguments):
        with (output / (label + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [str(binary), *arguments, "--data-dir", str(server.dir)],
                cwd=server.dir,
                env=server.env(),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        assert result.returncode == 0, (label, result.returncode)
        raw = (output / (label + ".log")).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Frozen Windows console streams use the active ANSI code page;
            # retain its characters and normalize only this owned test log.
            text = raw.decode("cp1252")
            (output / (label + ".log")).write_text(text, encoding="utf-8")
        return text

    def request_file(client, route):
        response = client.http.get(client.server.base + route, headers={"Authorization": "Bearer " + client.token})
        assert response.is_success, (route, response.status_code, response.text[:300])
        return response.content

    def wait_row(client, route, states):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            row = call(client, "GET", route)
            if row["state"] in states:
                return row
            assert row["state"] == "queued", row
            time.sleep(0.5)
        raise AssertionError("Durable job did not finish: " + route)

    try:
        old = BinaryServer(output, previous)
        servers.append(old)
        old.start(timeout=180)
        users = setup_users(old, findings)
        clients.extend(users.values())
        legacy = call(
            users["owner"],
            "POST",
            "/tenants",
            {"full_name": "QA Legacy Upgrade Witness", "email": "legacy@example.test"},
        )
        old.stop(hard=True)
        upgrade = cmd(old, "upgrade", "upgrade")
        assert "Upgrade abgeschlossen" in upgrade and "Vollbackup" in upgrade
        check("Previous audited Windows installation upgrades with automatic verified pre-upgrade backup")

        current = Binary(output, binary)
        servers.append(current)
        current.dir, current.log, current.secret = old.dir, output / "current-server.log", old.secret
        current.start(timeout=180)
        notices = filesystem_path(binary.parent / "_internal" / "THIRD_PARTY_NOTICES")
        catalog = json.loads((notices / "catalog.json").read_text(encoding="utf-8"))
        assert len(catalog["components"]) == 258
        for entry in catalog["files"]:
            target = notices / entry["path"]
            assert target.stat().st_size == entry["bytes"]
            with target.open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"]
        with httpx.Client(timeout=180) as public:
            legal = public.get(current.base + "/legal")
            assert legal.status_code == 200 and "CEN und DIN" in legal.text
            assert "default-src 'none'" in legal.headers["content-security-policy"]
            assert public.get(current.base + "/legal/files/" + "0" * 64).status_code == 404
            for filename in (
                "source-certifi-2026.10.19.tar.gz",
                "e-invoice/sources/cen-en16931-validation-1.3.16.tar.gz",
                "e-invoice/sources/freefont-sfd-20100919.tar.gz",
                "e-invoice/sources/net.sf.saxon-Saxon-HE-12.10-sources.jar",
                "e-invoice/sources/OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz",
            ):
                entry = next(row for row in catalog["files"] if row["path"] == filename)
                digest, size = hashlib.sha256(), 0
                with public.stream("GET", current.base + "/legal/files/" + entry["id"]) as response:
                    assert response.status_code == 200
                    for chunk in response.iter_bytes():
                        digest.update(chunk)
                        size += len(chunk)
                assert size == entry["bytes"] and digest.hexdigest() == entry["sha256"]
        check(
            "All 819 notice/source files match their catalog; public source downloads are byte-identical without login"
        )
        owner = Client(current, findings, "owner")
        clients.append(owner)
        assert call(owner, "GET", "/tenants/" + legacy["id"])["full_name"] == legacy["full_name"]
        seed(current, owner, output)
        fixture = json.loads((output / "fixture.json").read_text(encoding="utf-8"))
        first, second = fixture["households"]
        raw = Path(fixture["invoice"]).read_bytes()
        response = owner.http.post(
            current.base + "/e-invoice-intakes",
            headers={"Authorization": "Bearer " + owner.token, "Idempotency-Key": uuid4().hex},
            data={"property_id": fixture["property"]["id"]},
            files={"file": ("invoice.xml", raw, "application/xml")},
        )
        assert response.status_code == 201, response.text[:500]
        receipt = wait_row(owner, "/e-invoice-intakes/" + response.json()["id"], ("valid", "warning"))
        accepted = call(
            owner,
            "POST",
            "/e-invoice-intakes/" + receipt["id"] + "/accept",
            {
                "expected_revision": receipt["revision"],
                "idempotency_key": uuid4().hex,
                "unit_id": first["unit"]["id"],
                "acknowledge_warnings": True,
                "warning_reason": "Offizielles synthetisches Muster und dessen Hinweise geprüft.",
            },
        )
        identifier = accepted["invoice_id"]
        for kind in ("factual", "arithmetic"):
            call(owner, "POST", f"/invoices/{identifier}/review/{kind}-check", {"result": "confirmed"})
        manager = Client(current, findings, "verwalter")
        clients.append(manager)
        call(
            manager,
            "POST",
            f"/invoices/{identifier}/review/decision",
            {"decision": "approve", "reason": "Beleg und Leistung gegengeprüft."},
        )
        payment = call(owner, "GET", f"/invoices/{identifier}/payment-authorization")
        payment = call(
            owner,
            "POST",
            f"/invoices/{identifier}/payment-recipient",
            {
                "expected_revision": payment["revision"],
                "idempotency_key": uuid4().hex,
                "name": "QA Empfänger",
                "iban": "DE89370400440532013000",
                "reason": "Kontodaten aus geprüftem Stamm übernommen.",
            },
        )
        call(
            manager,
            "POST",
            f"/invoices/{identifier}/payment-authorization",
            {
                "expected_revision": payment["revision"],
                "idempotency_key": uuid4().hex,
                "reason": "Betrag und Empfänger unabhängig geprüft.",
                "bank_verification": "Rückruf über bekannte Kontaktnummer und Vergleich der Kontodaten.",
            },
        )
        check("Actual frozen validator and two-person financial approval persist before backup")

        invitation = call(
            owner,
            "POST",
            "/portal-admin/invitations",
            {
                "kind": "tenant",
                "party_id": first["tenant"]["id"],
                "relation_id": first["contract"]["id"],
                "email": first["tenant"]["email"],
                "idempotency_key": uuid4().hex,
                "verification": "Identität und persönliches Mietverhältnis anhand der Unterlagen geprüft.",
            },
        )
        portal = httpx.Client(headers={"Origin": current.base.removesuffix("/api/v1"), "X-Portal-Client": "web-v1"})
        response = portal.post(
            current.base + "/portal/accept",
            json={"token": invitation["invitation_url"].split("#")[1], "password": "PortalWindowsOps2026!"},
        )
        assert response.status_code == 200, response.text[:400]
        grant = portal.get(current.base + "/portal/me").json()["grants"][0]
        call(
            owner,
            "POST",
            f"/portal-admin/grants/{grant['id']}/publications",
            {
                "grant_revision": grant["revision"],
                "version_id": first["version"]["id"],
                "title": "QA Vertragsunterlage",
                "reason": "Eigene Fassung ausdrücklich geprüft.",
                "idempotency_key": uuid4().hex,
            },
        )
        portal.close()
        resource = call(owner, "GET", "/privacy/resources/document/" + second["document"]["id"])
        call(
            owner,
            "POST",
            "/privacy/resources/document/" + second["document"]["id"],
            {
                "action": "hold",
                "expected_revision": resource["revision"],
                "source_sha256": resource["source_sha256"],
                "reason": "Unterlage für laufende Prüfung aufbewahren.",
                "idempotency_key": uuid4().hex,
            },
        )
        journal = call(owner, "GET", "/privacy/journal")
        export = call(owner, "POST", "/data/portability-exports", {"idempotency_key": uuid4().hex})
        export = wait_row(owner, "/data/portability-exports/" + export["id"], ("ready",))
        customer_zip = request_file(owner, "/data/portability-exports/" + export["id"] + "/download")
        assert hashlib.sha256(customer_zip).hexdigest() == export["sha256"]
        with zipfile.ZipFile(io.BytesIO(customer_zip)) as archive:
            serialized = b"\n".join(archive.read(n) for n in archive.namelist() if n.endswith(".json"))
            for secret in (
                b"PortalWindowsOps2026!",
                b"totp_secret",
                b"refresh_token",
                owner.token.encode(),
            ):
                assert secret not in serialized

            def no_password_values(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key == "password_hash":
                            assert item is None, "Customer archive contains a credential"
                        no_password_values(item)
                elif isinstance(value, list):
                    for item in value:
                        no_password_values(item)

            for name in archive.namelist():
                if name.endswith(".json"):
                    no_password_values(json.loads(archive.read(name)))
        check("Customer archive contains original documents and financial evidence without credentials")
        current.stop(hard=True)
        cmd(current, "upgrade-check", "upgrade", "--check")
        backup = last_json(cmd(current, "backup", "ops", "backup"))
        assert backup["ok"]
        probe = last_json(cmd(current, "probe", "ops", "probe"))
        assert probe["ok"] and probe["readiness"] == "data_verified"
        target = output / "restored"
        assert target.resolve().is_relative_to(output)
        archive = current.dir / "backups/full" / backup["archive"]
        restored_report = last_json(cmd(current, "restore", "ops", "restore", str(archive), "--target", str(target)))
        assert restored_report["readiness"] == "data_verified"
        check("Frozen CLI full backup, restore probe and separate-target restore verify all new families")

        restored = Binary(output, binary)
        servers.append(restored)
        restored.dir, restored.log, restored.secret = target, output / "restored-server.log", current.secret
        original_env = restored.env
        restored.env = lambda: {
            **original_env(),
            "DATABASE_URL": "sqlite:///" + (target / "immo_manager.db").as_posix(),
        }
        restored.start(timeout=180)
        reopened = Client(restored, findings, "owner")
        clients.append(reopened)
        review = call(reopened, "GET", "/privacy/restore-review")
        assert review["pending"]
        grants = call(reopened, "GET", "/portal-admin/grants")["items"]
        assert grants and all(not row["active"] and not row["identity_active"] for row in grants)
        call(
            reopened,
            "POST",
            "/privacy/journal/import",
            {
                "controls": journal["controls"],
                "source_sha256": journal["sha256"],
                "reason": "Separates aktuelles Sperrjournal mit dem wiederhergestellten Stand abgeglichen.",
                "idempotency_key": uuid4().hex,
            },
        )
        review = call(reopened, "GET", "/privacy/restore-review")
        call(
            reopened,
            "POST",
            "/privacy/restore-review",
            {
                "expected_revision": review["revision"],
                "journal_sha256": review["journal_sha256"],
                "decisions_reconciled": True,
                "reason": "Alle aktuellen Sperr- und Löschentscheidungen nach der Wiederherstellung geprüft.",
                "idempotency_key": uuid4().hex,
            },
        )
        for household in fixture["households"]:
            data = request_file(
                reopened,
                f"/documents/{household['document']['id']}/work/versions/{household['version']['id']}/download",
            )
            assert hashlib.sha256(data).hexdigest() == household["sha256"]
        assert call(reopened, "GET", "/privacy/resources/document/" + second["document"]["id"])["held"]
        assert call(reopened, "GET", "/e-invoice-intakes/" + receipt["id"])["invoice_id"] == identifier
        check("Restored access gate, deactivated portal, reconciled journal, hold and byte-identical originals")
        restored.stop(hard=True)

        fresh = Binary(output, binary)
        servers.append(fresh)
        fresh.start(timeout=180)
        fresh_users = setup_users(fresh, findings)
        clients.extend(fresh_users.values())
        importer = fresh_users["owner"]
        response = importer.http.post(
            fresh.base + "/data/import-batches",
            headers={"Authorization": "Bearer " + importer.token, "Idempotency-Key": uuid4().hex},
            data={"options": json.dumps({"source_system": "QA Kundenwechsel"})},
            files={"files": ("customer.zip", customer_zip, "application/zip")},
        )
        assert response.status_code == 201, response.text[:500]
        batch = response.json()
        assert batch["state"] == "ready", batch["preview"]
        call(
            importer,
            "POST",
            "/data/import-batches/" + batch["id"] + "/commit",
            {
                "expected_revision": batch["revision"],
                "idempotency_key": uuid4().hex,
                "acknowledge_warnings": True,
                "reason": "Originaldateien und Kontrollsummen gegen Quellbestand geprüft.",
            },
        )
        review = call(importer, "GET", "/privacy/restore-review")
        if review["pending"]:
            call(
                importer,
                "POST",
                "/privacy/restore-review",
                {
                    "expected_revision": review["revision"],
                    "journal_sha256": review["journal_sha256"],
                    "decisions_reconciled": True,
                    "reason": "Kundenübernahme und alle enthaltenen Sperrentscheidungen geprüft.",
                    "idempotency_key": uuid4().hex,
                },
            )
        for household in fixture["households"]:
            data = request_file(
                importer,
                f"/documents/{household['document']['id']}/work/versions/{household['version']['id']}/download",
            )
            assert hashlib.sha256(data).hexdigest() == household["sha256"]
        assert not call(importer, "GET", f"/invoices/{identifier}/payment-authorization")["authorized"]
        for kind in ("units", "contracts", "invoices"):
            records = call(importer, "GET", "/" + kind + "?limit=1000")
            assert len(records) == export["manifest"]["controls"][kind]["count"]
        check(
            "Fresh Windows installation reimports exact counts and hashes; historical approval cannot authorize payments"
        )
    finally:
        for server in servers:
            server.stop(hard=True)
        for client in clients:
            client.http.close()
        (output / "results.json").write_text(
            json.dumps(
                {
                    "synthetic_only": True,
                    "checks": checks,
                    "servers_stopped": all(s.proc is None for s in servers),
                    "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
