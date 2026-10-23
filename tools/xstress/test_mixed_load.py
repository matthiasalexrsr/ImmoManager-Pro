"""Exercise the load driver through real HTTP, including rejection and lost writes."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from tools.xstress import roles
from tools.xstress.core import Findings


@pytest.mark.parametrize("fault", [None, "reader403", "lostwrite", "corruptedwrite"])
def test_mixed_load_overlaps_independent_clients_and_verifies_writes(fault):
    records, logins, created_users = {}, [], {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if self.path.endswith("/auth/login"):
                with lock:
                    logins.append(data["username"])
                return self.reply(200, {"access_token": data["username"]})
            if self.path.endswith("/auth/users"):
                with lock:
                    created_users[data["username"]] = data
                return self.reply(201, {"id": data["username"], **data})
            assert self.path.endswith("/bookings")
            username = self.headers.get("Authorization", "").removeprefix("Bearer ")
            assert created_users[username]["portfolio_access"] == "selected"
            assert created_users[username]["portfolio_ids"] == ["portfolio-1", "portfolio-2"]
            time.sleep(0.02)
            with lock:
                row = {"id": str(len(records) + 1), **data}
                records[row["id"]] = {**row, "amount": -1} if fault == "corruptedwrite" else row
            self.reply(201, row)

        def do_GET(self):
            if "/portfolios?" in self.path:
                return self.reply(200, [{"id": "portfolio-1"}, {"id": "portfolio-2"}])
            if "limit=1000" in self.path:
                with lock:
                    rows = list(records.values())
                return self.reply(200, [] if fault == "lostwrite" else rows)
            time.sleep(0.01)
            return self.reply(403 if fault == "reader403" else 200, [])

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    findings = Findings()
    try:
        result = roles.mixed_load(SimpleNamespace(base=f"http://127.0.0.1:{http.server_port}/api/v1"),
                                  findings, "account-1", ["tenant-1"], duration=0.5, writes_per_writer=3)
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
    assert result["clients"] == 10
    assert result["writers"] == 2
    assert result["acknowledged_writes"] == 6
    assert result["overlapping_requests"] > 0
    assert len(set(logins) - {"owner"}) == 10
    assert len(created_users) == 10
    assert all(user["portfolio_access"] == "selected" and
               user["portfolio_ids"] == ["portfolio-1", "portfolio-2"] for user in created_users.values())
    if fault is None:
        assert result["verified_writes"] == 6
        assert result["errors"] == 0
        assert not [item for item in findings.items if item["severity"] != "HINWEIS"]
    else:
        assert any(item["severity"] in ("FALSCH", "KRITISCH") for item in findings.items)
        if fault == "reader403":
            assert result["errors"] > 0
        else:
            assert result["verified_writes"] == 0
