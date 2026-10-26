"""Exercise integrated features only on a newly owned synthetic instance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_daily_browser_qa import BinaryServer  # noqa: E402
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


class IntegrationEnv:
    def env(self):
        return {
            **super().env(),
            "PORTAL_ENABLED": "true",
            "PORTAL_LOCAL_TEST_MODE": "true",
            "PORTAL_PUBLIC_URL": self.base.removesuffix("/api/v1"),
            "JOB_SCHEDULER_ENABLED": "true",
            "JOB_SCHEDULER_INTERVAL_SECONDS": "1",
        }


class Source(IntegrationEnv, Server):
    pass


class Binary(IntegrationEnv, BinaryServer):
    pass


def seed(server, user, output):
    def call(method, path, data=None, **kwargs):
        response = user.http.request(
            method, server.base + path, json=data, headers={"Authorization": "Bearer " + user.token}, **kwargs
        )
        assert response.is_success, (method, path, response.status_code, response.text[:500])
        return response.json()

    portfolio = call("POST", "/portfolios", {"name": "QA Integration"})
    prop = call(
        "POST",
        "/properties",
        {"portfolio_id": portfolio["id"], "name": "QA Gemeinsames Haus", "property_type": "residential"},
    )
    households = []
    from PIL import Image
    from reportlab.pdfgen import canvas

    for number in (1, 2):
        tenant = call(
            "POST", "/tenants", {"full_name": f"QA Haushalt {number}", "email": f"household{number}@example.test"}
        )
        unit = call(
            "POST", "/units", {"property_id": prop["id"], "label": f"QA Wohnung {number}", "unit_type": "residential"}
        )
        contract = call(
            "POST",
            "/contracts",
            {
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "tenant_id": tenant["id"],
                "contract_number": f"QA-PORTAL-{number}",
                "start_date": "2025-01-01",
                "cold_rent": 500,
                "deposit_amount": 1500,
            },
        )
        data = io.BytesIO()
        pdf = canvas.Canvas(data)
        pdf.drawString(60, 780, f"Private Vertragsunterlage QA Haushalt {number}")
        pdf.showPage()
        pdf.save()
        raw = data.getvalue()
        uploaded = call(
            "POST", "/files/upload?folder=documents", files={"file": (f"Haushalt-{number}.pdf", raw, "application/pdf")}
        )
        doc = call(
            "POST",
            "/documents",
            {
                "title": f"QA Private Unterlage {number}",
                "file_url": uploaded["file_url"],
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "tenant_id": tenant["id"],
                "contract_id": contract["id"],
            },
        )
        source = call("GET", f"/documents/{doc['id']}/work/source")
        archive = call(
            "POST",
            f"/documents/{doc['id']}/work/archive",
            {
                "command_key": uuid4().hex,
                "expected_version": None,
                "expected_sha256": source["sha256"],
                "expected_document_revision": source["document_revision"],
            },
        )
        households.append(
            {
                "tenant": tenant,
                "unit": unit,
                "contract": contract,
                "document": doc,
                "version": archive["version"],
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    image = output / "damage.png"
    Image.new("RGB", (64, 48), "#367a98").save(image)
    files = {
        "properties.csv": "external_ref;name;property_type\nM-H1;QA Importhaus;residential\n",
        "units.csv": "external_ref;property_ref;label;unit_type;area_sqm\nM-U1;M-H1;QA Importwohnung;residential;65,50\n",
        "parties.csv": "external_ref;party_kind;full_name\nM-P1;tenant;QA Importpartei\n",
        "contracts.csv": "external_ref;property_ref;unit_ref;tenant_ref;contract_number;start_date;cold_rent;deposit_amount\nM-V1;M-H1;M-U1;M-P1;QA-IMPORT-1;2026-01-01;500,25;1500\n",
        "accounts.csv": "external_ref;name;account_type;opening_balance;iban\nM-K1;QA Importkonto;checking;1234,56;DE89370400440532013000\n",
        "receivables.csv": "external_ref;contract_ref;due_date;amount_due;description;kind\nM-O1;M-V1;2026-09-01;123,45;QA Offener Posten;other\n",
    }
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8-sig")
    # The normal staff default intentionally has no portfolio access. Grant
    # this checker exactly the synthetic portfolio before testing four eyes.
    manager = next(row for row in call("GET", "/auth/users") if row["username"] == "verwalter")
    call("PATCH", "/auth/users/" + manager["id"], {"portfolio_access": "selected", "portfolio_ids": [portfolio["id"]]})
    result = {
        "portfolio": portfolio,
        "property": prop,
        "households": households,
        "csv": list(files),
        "invoice": str(ROOT / "backend/tests/fixtures/e-invoice-runtime/xrechnung-ubl.xml"),
    }
    (output / "fixture.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--script", default="integration_browser_qa.mjs")
    options = parser.parse_args()
    binary = options.binary.absolute() if options.binary else None
    if binary and not binary.resolve(strict=True).is_relative_to(ROOT):
        parser.error("Binary must be from this assigned checkout")
    output = fresh_directory(ROOT / "artifacts/integration-browser", "binary" if binary else "source")
    server = Binary(output, binary) if binary else Source(output, "server")
    if server.port in (8000, 8765):
        raise RuntimeError("Live installation port prohibited")
    users = {}
    result = {
        "synthetic_only": True,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "binary": str(binary) if binary else None,
        "exit_code": None,
    }
    print("RESULT_DIR=" + str(output), flush=True)
    try:
        server.start(timeout=180)
        users = setup_users(server, Findings())
        seed(server, users["owner"], output)
        environment = {
            **os.environ,
            "QA_BASE_URL": server.base.removesuffix("/api/v1"),
            "QA_ALLOW_TEST_WRITES": "1",
            "QA_PASSWORD": PASSWORD,
            "QA_OUTPUT": str(output),
            "QA_PLAYWRIGHT_PATH": str(options.playwright.resolve()),
        }
        with (output / "browser.log").open("w", encoding="utf-8") as log:
            process, job = start_owned(
                ["node", str(ROOT / "scripts" / options.script)],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                result["exit_code"] = process.wait(timeout=1200)
            finally:
                stop_owned(process, job, hard=True)
        if result["exit_code"]:
            print((output / "browser.log").read_text(encoding="utf-8")[-2500:], flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result["server_stopped"] = server.proc is None
        (output / "completion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result["exit_code"] or 0


if __name__ == "__main__":
    raise SystemExit(main())
