"""Run the extreme stress test.

    python -m tools.xstress.run                    # 120 units, 5 years (about 30–60 minutes)
    python -m tools.xstress.run --quick            # 15 units, 1 year: checks that the test itself works
    python -m tools.xstress.run --units 300 --years 5 --seed 7 --out /tmp/xstress

Results: <out>/report.md (readable) and <out>/findings.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from . import bad_input, roles, saveload
from .core import PASSWORD, REPO, Findings, Server, setup_users, write_report
from .invariants import run_checks
from .timeline import Simulation
from .world import build_world, month_end

HERE = Path(__file__).parent


def ui_pass(server: Server, findings: Findings, out: Path) -> None:
    findings.phase = "oberfläche"
    if not (REPO / "frontend" / "dist" / "index.html").exists():
        findings.add("HINWEIS", "Oberfläche", "frontend/dist fehlt – Oberflächendurchlauf übersprungen (npm run build)")
        return
    origin = server.base.removesuffix("/api/v1")
    for username in ("owner", "buchhaltung", "hausmeister", "steuerberater"):
        target = out / f"ui_{username}.json"
        result = subprocess.run(["node", str(HERE / "ui.js"), origin, username, PASSWORD, str(target)],
                                cwd=REPO / "frontend", capture_output=True, text=True, timeout=900,
                                env={**os.environ, "NODE_PATH": os.environ.get("XSTRESS_NODE_PATH", "")})
        if result.returncode != 0 or not target.exists():
            findings.add("HINWEIS", "Oberfläche", f"Durchlauf für {username} nicht möglich", result.stderr[-400:])
            continue
        data = json.loads(target.read_text())
        for issue in data["issues"]:
            severity = {"js": "KRITISCH", "http 403": "RECHTE"}.get(issue["kind"],
                                                                 "KRITISCH" if issue["kind"].startswith("http") else "FALSCH")
            findings.add(severity, "Oberfläche", f"{username} · {issue['page']}: {issue['kind']}", issue["detail"])
        for p in data["pages"]:
            if p["ms"] > 4000:
                findings.add("LANGSAM", "Oberfläche", f"{username} · {p['page']} lädt in {p['ms'] / 1000:.1f} s")
            if username == "steuerberater" and p["editButtons"]:
                findings.add("RECHTE", "Oberfläche",
                             f"Nur-Lesen sieht auf „{p['page']}“ {p['editButtons']} Bearbeiten-/Neu-Knöpfe")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--units", type=int, default=120)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=REPO / "stress-results")
    parser.add_argument("--quick", action="store_true", help="15 units, 1 year")
    parser.add_argument("--skip", nargs="*", default=[], choices=["saveload", "fehldaten", "rechte", "ui"])
    args = parser.parse_args()
    if args.quick:
        args.units, args.years = 15, 1
    started = time.time()
    work = args.out / "server"
    if work.exists():
        shutil.rmtree(work)
    findings = Findings()
    world = build_world(seed=args.seed, units=args.units, years=args.years)
    print(f"Welt: {world.start} – {world.end}, {len(world.units)} Einheiten, {len(world.tenancies)} Mietverhältnisse, "
          f"{len(world.tenants)} Mieter", flush=True)
    server = Server(work, "main")
    server.start()
    try:
        users = setup_users(server, findings)
        sim = Simulation(world, users, findings, args.seed)
        middle_year = world.start.year + args.years // 2

        def after_month(month: date) -> None:
            if month.month in (6, 12):
                run_checks(sim, month_end(month))
            if month.month == 12 and "saveload" not in args.skip:
                saveload.checkpoint(server, users, findings, world.portfolios[0].account_id,
                                    full=month.year in (middle_year, world.end.year))
            if month.month == 7 and month.year == middle_year:
                findings.add("HINWEIS", "Speichern/Laden", "Stromausfall simuliert (Server hart beendet)")
                server.restart(hard=True)
                saveload.relogin(users)
            print(f"{month:%Y-%m} fertig · {len(findings.items)} Befunde · {time.time() - started:.0f} s", flush=True)

        sim.run(after_month)
        run_checks(sim, world.end)
        run_checks(sim, date.today())
        if "fehldaten" not in args.skip:
            bad_input.run(server, findings)
        if "rechte" not in args.skip:
            roles.run(server, findings)
        if "saveload" not in args.skip:
            saveload.checkpoint(server, users, findings, world.portfolios[0].account_id, full=True)
        if "ui" not in args.skip:
            ui_pass(server, findings, args.out)
    finally:
        server.stop()
    report = write_report(findings, args.out, {"started": datetime.fromtimestamp(started).isoformat(timespec="minutes"),
                                               "minutes": (time.time() - started) / 60, "seed": args.seed,
                                               "units": args.units, "years": args.years})
    print(f"\nBericht: {report}")


if __name__ == "__main__":
    main()
