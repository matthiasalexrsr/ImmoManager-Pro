"""Deterministic German rule/owned-provider-process fault corpus; no model benchmark."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHILD = '''import json,sys,time
mode=sys.argv[1]
sys.stdin.read()
def emit(value):
 print(json.dumps(value),flush=True)
emit({'type':'system','subtype':'init','tools':['Bash'] if mode=='tools' else [],'mcp_servers':[], 'plugins':[], 'session_id':'session-current'})
if mode=='double-init':
 emit({'type':'system','subtype':'init','tools':[],'mcp_servers':[], 'plugins':[], 'session_id':'session-current'})
if mode in ['timeout','cancel']: time.sleep(30)
elif mode=='bad-json': print('not-json',flush=True)
elif mode=='missing': pass
else:
 emit({'type':'result','subtype':'success','is_error':False,'result':'' if mode=='empty' else 'Kontrollierte Antwort 119,00 EUR', 'session_id':'session-stale' if mode=='stale-session' else 'session-current'})
 if mode=='double-final':
  emit({'type':'result','subtype':'success','is_error':False,'result':'Zweite Antwort','session_id':'session-current'})
if mode=='nonzero': sys.exit(7)
'''


def run(output, repetitions, require_clean_source=False):
    from scripts.check_frozen_desktop import isolated_environment
    from scripts.release_stress import percentiles, snapshot, source_eligible
    output.mkdir(parents=True, exist_ok=False)
    (output/".release-ai-corpus-owned.json").write_text(json.dumps({"kind":"synthetic-controlled-provider-corpus"}),encoding="utf-8")
    source_before = snapshot()
    if require_clean_source and not source_before['clean']:
        source_after = snapshot()
        report = {'schema':'immomanager-deterministic-ai-stress/1','status':'failed','workload_status':'not_run',
            'release_eligible':False,'source_before':source_before,'source_after':source_after,
            'source_unchanged':source_before==source_after,'groups':{},'findings':[{'code':'source_not_clean'}],
            'scope':'Clean source required before any workload; no acceptance or model-quality claim.'}
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        (output/'report.md').write_text('# Source gate failed\n\nWorkload not executed: checkout not clean.\n',encoding='utf-8')
        return report
    env = isolated_environment(output, 18889)
    env.update(ENVIRONMENT="development", SQLITE_PERSISTENT_STORE="false", ALLOW_INMEMORY_FALLBACK="true",
        DATABASE_URL="sqlite:///:memory:", SECRET_KEY_FILE=str(output/"data/keys.json"),
        INTEGRATION_STATE_FILE=str(output/"data/integrations.json"), AI_CACHE_DIR=str(output/"cache"),
        AI_ENABLED="false", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    os.environ.clear()
    os.environ.update(env)
    # Prevent a repository/operator .env from supplementing this private env.
    os.chdir(output)
    from backend.services import ai_surfaces as surfaces
    from backend.services import assistant_provider_claude as adapter
    from backend.services.assistant_provider_protocol import ProviderError
    started = time.monotonic()
    child_file = output/"controlled-provider.py"
    child_file.write_text(CHILD, encoding="utf-8")
    rows, errors, children = [], [], []
    original_factory, original_timeout = adapter.CliProcess, adapter.EXECUTE_TIMEOUT

    def capture(*args, **kwargs):
        child = original_factory(*args, **kwargs)
        children.append(child)
        return child
    adapter.CliProcess, adapter.EXECUTE_TIMEOUT = capture, 1
    expected = {"success":None,"bad-json":"provider_protocol_error","missing":"provider_result_missing",
        "empty":"empty_answer","tools":"provider_isolation_failed","nonzero":"provider_execution_failed",
        "timeout":"provider_timeout","cancel":"cancelled","stale-session":"provider_protocol_error"}
    expected.update({'double-init':'provider_protocol_error','double-final':'provider_protocol_error'})
    try:
        for repetition in range(repetitions):
            for mode,wanted in expected.items():
                profile=output/f"provider-{repetition}-{mode}"
                profile.mkdir()
                own_start=len(children)
                began=time.perf_counter()
                observed=None
                text=None
                try:
                    answer=adapter.execute(SimpleNamespace(provider="claude",path=profile),
                        [sys.executable,"-u",str(child_file),mode],{},lambda event:None,
                        lambda:mode=="cancel" and len(children)>own_start and time.perf_counter()-began>.1)
                    text=answer["text"]
                except ProviderError as error:
                    observed=error.code
                retained=children[own_start:]
                closed=bool(retained) and all(c.process.poll() is not None for c in retained)
                correct=observed==wanted and closed and (wanted is not None or text=="Kontrollierte Antwort 119,00 EUR")
                row={"kind":"provider_process","case":mode,"repetition":repetition,"expected_code":wanted,
                     "actual_code":observed,"seconds":time.perf_counter()-began,"passed":correct,
                     "own_processes":len(retained),"all_owned_children_exited":closed}
                rows.append(row)
                if not correct:
                    errors.append(row)
        for index in range(40):
            net=(Decimal("100.00")+Decimal(index)*Decimal("37.13")).quantize(Decimal(".01"))
            rate=Decimal([0,7,19][index%3])
            vat=(net*rate/100).quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
            gross=net+vat
            def fmt(value):
                return format(value,",.2f").replace(",","_").replace(".",",").replace("_",".")
            text=f"Neckar Hausservice GmbH\nRechnung BW-2026-{index:04}\nDatum 06.11.2026\nNetto {fmt(net)} EUR\nUmsatzsteuer {rate} % {fmt(vat)} EUR\nBrutto {fmt(gross)} EUR"
            began=time.perf_counter()
            actual=surfaces.local_values(surfaces.INVOICE,text,filename="rechnung.txt")
            correct=all(Decimal(str(actual.get(key,{}).get("value","-1")))==value for key,value in
                        [("net_amount",net),("vat_amount",vat),("gross_amount",gross)])
            row={"kind":"german_local_rules","case":index,"expected":{"net":str(net),"vat":str(vat),"gross":str(gross)},
                 "vat_rate":str(rate),"seconds":time.perf_counter()-began,"passed":correct}
            rows.append(row)
            if not correct:
                errors.append(row | {"actual":actual})
        for index in range(20):
            facts={"units":[{"id":"allowed-unit","label":"WE 1"}],"tenants":[],"contracts":[]}
            values,dropped=surfaces.clean_values(surfaces.DOCUMENT,{"unit":{"value":"foreign-unit-"+str(index)}},facts,source="local")
            correct="unit" not in values and bool(dropped)
            row={"kind":"assignment_boundary","case":index,"passed":correct,"seconds":0}
            rows.append(row)
            if not correct:
                errors.append(row)
    finally:
        adapter.CliProcess,adapter.EXECUTE_TIMEOUT=original_factory,original_timeout
        for child in children:
            child.close()
    groups={}
    for kind in {row["kind"] for row in rows}:
        cases=[r for r in rows if r["kind"]==kind]
        groups[kind]={**percentiles([r["seconds"] for r in cases]),"passed":sum(r["passed"] for r in cases),
                      "failed":sum(not r["passed"] for r in cases),"failure_rate":sum(not r["passed"] for r in cases)/len(cases)}
    source_after = snapshot()
    report={"schema":"immomanager-deterministic-ai-stress/1","created_at":datetime.now(timezone.utc).isoformat(),
        "status":"passed" if not errors else "failed","source_commit":source_before['head'],
        "base_tree":source_before['base_tree'],"working_changes":source_before['working_changes'],
        "source_before":source_before,"source_after":source_after,"source_unchanged":source_before==source_after,
        "seconds":time.monotonic()-started,"groups":groups,"cases":rows,"findings":errors,
        "owned_provider_processes":len(children),"all_owned_provider_processes_exited":all(c.process.poll() is not None for c in children),
        "hf_dependencies":{name:importlib.util.find_spec(name) is not None for name in ["transformers","torch","sentence_transformers","huggingface_hub"]},
        "hf_german_model_benchmark":{"status":"not_executed","reason":"No installed HF runtime/model; no downloaded model or live inference. This is a release-quality gap."},
        "scope":"Actual local German parsing/assignment rules and actual controlled child-process transport. Synthetic protocol responses are NOT real model accuracy, source faithfulness or German HF quality.",
        "files":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/"backend/services/assistant_provider_claude.py",ROOT/"backend/services/ai_surfaces.py"]}}
    report['workload_status'] = report['status']
    report['release_eligible'] = source_eligible(source_before, source_after, report['status']=='passed')
    report['release_eligibility_scope'] = 'Source-bound stress gate only; signing, upgrade, security and real model-quality decisions remain independent.'
    if require_clean_source and not report['release_eligible']:
        report['status'] = 'failed'
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"report.md").write_text("# Deterministischer KI-Zuverlaessigkeitskorpus\n\n"+report["scope"]+"\n\nErgebnis: "+report["status"]+"\n\n```json\n"+json.dumps(groups,indent=2)+"\n```\n\nHF-Modellbenchmark: nicht ausgefuehrt; echte Qualitaetsluecke.\n",encoding="utf-8")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--require-clean-source",action="store_true")
    args=parser.parse_args(argv)
    if not 1<=args.repetitions<=10:
        parser.error("repetitions must be1..10")
    output=args.output.resolve()
    if output.exists():
        parser.error("Output must be a new directory; existing evidence is never overwritten")
    try:
        report=run(output,args.repetitions,args.require_clean_source)
    except Exception as error:
        report={"schema":"immomanager-deterministic-ai-stress/1","status":"failed","release_eligible":False,"groups":{},
                "findings":[{"type":type(error).__name__,"message":str(error)[:300]}],
                "scope":"Harness did not complete; no model-quality or acceptance claim."}
        if (output/".release-ai-corpus-owned.json").is_file() and not (output/"report.json").exists():
            (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            (output/"report.md").write_text("# Abgebrochener KI-Test\n\n"+json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"groups":report["groups"],"findings":report["findings"]},ensure_ascii=True))
    return int(report["status"]!="passed")


if __name__=="__main__":
    raise SystemExit(main())
