"""Real assistant browser checks on a new synthetic SQLite installation only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_daily_browser_qa import BinaryServer  # noqa: E402
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


class AssistantServer(Server):
    def env(self):
        return {**super().env(), "JOB_SCHEDULER_ENABLED": "true", "JOB_SCHEDULER_INTERVAL_SECONDS": "1"}


class AssistantBinaryServer(BinaryServer):
    """The same owned binary lifecycle with genuine local assistant processing."""

    def env(self):
        return {**super().env(), "JOB_SCHEDULER_ENABLED": "true", "JOB_SCHEDULER_INTERVAL_SECONDS": "1"}


def fixture(server, owner, output):
    actor = owner.require_entity("GET", "/auth/me")
    portfolio = owner.require_entity("POST", "/portfolios", {"name": "KI Browser Musterbestand"})
    prop = owner.require_entity("POST", "/properties", {"portfolio_id": portfolio["id"], "name": "KI Browser Parkhof",
        "property_type": "residential", "address_line": "Musterweg 18", "city": "Musterstadt"})
    unit = owner.require_entity("POST", "/units", {"property_id": prop["id"], "label": "KI Browser Wohnung", "unit_type": "flat",
        "area_sqm": 50, "cold_rent": 500, "service_charge_advance": 0, "heating_advance": 0, "status": "vacant"})
    account = owner.require_entity("POST", "/accounts", {"portfolio_id": portfolio["id"], "name": "KI Browser Konto", "account_type": "checking"})
    income = owner.require_entity("POST", "/categories", {"portfolio_id": portfolio["id"], "name": "KI Browser Einnahmen", "category_type": "income"})
    owner.require_entity("POST", "/bookings", {"account_id": account["id"], "category_id": income["id"], "property_id": prop["id"],
        "unit_id": unit["id"], "booking_date": "2026-10-01", "amount": "123.45", "payment_text": "KI Browser geprüfte Einnahme", "status": "booked"})
    convo = owner.require_entity("POST", "/assistant/conversations", {"title": "Manueller Prüfentwurf", "provider": "local", "effort": "high", "idempotency_key": "qa-manual-conversation"})
    run = owner.require_entity("POST", f"/assistant/conversations/{convo['id']}/runs", {"content": "Lokale Quellenprüfung für einen ausdrücklich manuellen UI-Testentwurf.",
        "context": {"property_ids": [prop["id"]]}, "expected_revision": convo["revision"], "idempotency_key": "qa-manual-run"})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = owner.ok("GET", f"/assistant/runs/{run['id']}")
        if value and value["state"] == "completed":
            break
        if value and value["state"] in {"failed", "blocked", "unknown"}:
            raise RuntimeError("Synthetic local preparation did not complete")
        time.sleep(.2)
    else:
        raise RuntimeError("Synthetic local preparation timed out")
    data = {"synthetic_only": True, "actor_id": actor["id"], "property": prop, "unit": unit, "conversation": convo, "run": run}
    path = output / "assistant-fixture.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    # A named manual fixture exercises the existing note form; no model response
    # or provider suggestion is forged. The genuine local answer remains intact.
    code = """
import json,sys
from backend.dependencies import store
from backend.services import assistant_storage as db, assistant_handoff
from backend.services import assistant as service
from backend.services.assistant import Proposal,Run
p=sys.argv[1]; f=json.load(open(p,encoding='utf-8'))
import fitz
pdf=fitz.open(); page=pdf.new_page(); page.insert_text((72,72),'Manueller Browser-Originalbeleg: Heizungsbetrieb. Netto 100,00 EUR, MwSt 19,00 EUR, Gesamt 119,00 EUR.')
page=pdf.new_page(); page.insert_text((72,72),'Seite 2: Leistungen am Heizkessel, Wartung und Pruefung.'); raw=pdf.tobytes();pdf.close()
attached=service.add_attachment(store,f['actor_id'],f['conversation']['id'],raw,'Manueller-Rechnungsbeleg.pdf')
f['manual_attachment']=attached
receipt=assistant_handoff.attachment_evidence(store,f['actor_id'],attached['id'])
with db.work(store,f['actor_id'],write=True) as u:
 r=db.owned_child(u,Run,f['run']['id']); source=db.payload(r)['_bundle']['sources'][0]
 payload={'kind':'note','anchor':{'kind':source['kind'],'id':source['id']},
 'evidence':[{k:source[k] for k in ('kind','id','revision','sha256')}],
 'values':{'body':'Manueller synthetischer Prüfentwurf für die Browserabnahme.','conversation_kind':'note'}}
 proposal=db.put(u,Proposal,{'run_id':r.id,'payload':payload,'decision':None},conversation_id=r.conversation_id,state='proposed')
 f['manual_proposal_id']=proposal.id
 task_payload={'kind':'task','anchor':None,'evidence':[],'values':{'title':'Manuelle Browseraufgabe: Heizungsbetrieb anrufen','due_date':'2026-10-19','priority':'medium','status':'open'}}
 task=db.put(u,Proposal,{'run_id':r.id,'payload':task_payload,'decision':None},conversation_id=r.conversation_id,state='proposed')
 f['manual_task_proposal_id']=task.id
 invoice_values={'supplier':'Manueller Browser-Heizungsbetrieb','invoice_date':'2026-10-18','net_amount':'100.00','vat_rate':'19.00','vat_amount':'19.00','gross_amount':'119.00','property_id':f['property']['id'],'status':'open'}
 invoice_payload={'kind':'invoice','anchor':{'kind':source['kind'],'id':source['id']},'values':invoice_values,
 'evidence':[{k:s[k] for k in ('kind','id','revision','sha256')} for s in (source,receipt)]}
 invoice=db.put(u,Proposal,{'run_id':r.id,'payload':invoice_payload,'decision':None},conversation_id=r.conversation_id,state='proposed')
 f['manual_invoice_proposal_id']=invoice.id;f['manual_invoice_values']=invoice_values
 run_data=db.payload(r);run_data['attachment_ids']=[attached['id']];run_data['_proposal_ids']=[proposal.id,task.id,invoice.id]
 db.put(u,Run,run_data,row=r)
open(p,'w',encoding='utf-8').write(json.dumps(f))
"""
    seeded = subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT, env=server.env(), capture_output=True, text=True, encoding="utf-8", timeout=60)
    (output / "fixture.log").write_text(seeded.stdout + seeded.stderr, encoding="utf-8")
    if seeded.returncode:
        raise RuntimeError(f"Manual synthetic proposal failed; inspect {output / 'fixture.log'}")
    return path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/assistant-browser")
    parser.add_argument("--binary", type=Path, help="Optional built application inside this checkout")
    options = parser.parse_args()
    destination = options.output.resolve()
    if not destination.is_relative_to(ROOT) or not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("Output must stay in this checkout, and its frontend must be built")
    module = options.playwright.resolve(strict=True)
    binary = options.binary.resolve(strict=True) if options.binary else None
    if binary and (not binary.is_file() or not binary.is_relative_to(ROOT)):
        parser.error("Built application must be a file inside the assigned checkout")
    output = fresh_directory(destination, "assistant")
    server = AssistantBinaryServer(output / "server", binary) if binary else AssistantServer(output / "server", "assistant")
    if server.port in (8000, 8765):
        raise RuntimeError("Forbidden installation port")
    users = {}
    result = {"synthetic_only": True, "provider_login_started": False, "port": server.port, "exit_code": None,
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest() if binary else None}
    if binary:
        result["binary"] = str(binary)
    print("RESULT_DIR=" + str(output), flush=True)
    try:
        server.start(timeout=90)
        users = setup_users(server, Findings())
        data = fixture(server, users["owner"], output)
        environment = {**os.environ, "QA_BASE_URL": server.base.removesuffix("/api/v1"), "QA_ALLOW_TEST_WRITES": "1",
            "QA_PASSWORD": PASSWORD, "QA_OUTPUT": str(output / "checks"), "QA_PLAYWRIGHT_PATH": str(module), "QA_ASSISTANT_FIXTURE": str(data)}
        with (output / "browser.log").open("w", encoding="utf-8") as log:
            process, job = start_owned(["node", str(ROOT / "scripts/assistant_browser_qa.mjs")], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result["exit_code"] = process.wait(timeout=300)
            finally:
                stop_owned(process, job, hard=True)
        if result["exit_code"]:
            print((output / "browser.log").read_text(encoding="utf-8", errors="replace")[-5000:], flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result["server_stopped"] = server.proc is None
        (output / "completion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result["exit_code"] if result["exit_code"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
