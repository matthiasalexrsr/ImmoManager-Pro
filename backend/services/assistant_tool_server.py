"""Ephemeral loopback MCP transport. The bearer exists only for one owned run."""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import assistant_tools

MAX_REQUEST_BYTES = 128 * 1024


@contextmanager
def application_mcp(store, actor_id: str, run_id: str, lease: str):
    bearer = "Bearer " + secrets.token_urlsafe(48)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass  # Never log headers, arguments, file contents or tokens.

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def reply(self, status, data=None):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if data is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if body:
                self.wfile.write(body)

        def do_GET(self):
            self.reply(405)

        def do_POST(self):
            from ..dependencies import begin_request_scope, end_request_scope
            scope = begin_request_scope()
            try:
                self.post()
            finally:
                end_request_scope(scope)

        def post(self):
            if self.path != "/mcp" or not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"), bearer.encode("ascii")):
                self.reply(401)
                return
            if self.headers.get("Origin"):
                self.reply(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES or self.headers.get("Transfer-Encoding"):
                    self.reply(413)
                    return
                request = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                    raise ValueError
            except (ValueError, OSError, RecursionError):
                self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC request"}})
                return
            identifier = request.get("id")
            if request["method"] != "tools/call":
                try:
                    assistant_tools.assert_active(store, actor_id, run_id, lease)
                except Exception:
                    self.reply(409, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32001, "message": "Run unavailable"}})
                    return
            if "id" not in request:
                self.reply(204)
                return
            if isinstance(identifier, bool) or not isinstance(identifier, str | int):
                self.reply(400)
                return
            method, params = request["method"], request.get("params", {})
            if not isinstance(params, dict):
                self.reply(200, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": "Invalid params"}})
                return
            result: dict
            try:
                if method == "initialize":
                    result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}},
                              "serverInfo": {"name": "immomanager", "version": "1.0"}}
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    result = {"tools": assistant_tools.descriptors()}
                elif method == "tools/call":
                    if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
                        self.reply(200, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": "Invalid tool params"}})
                        return
                    output = assistant_tools.call(store, actor_id, run_id, lease, params["name"], params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False, allow_nan=False)}],
                              "structuredContent": output, "isError": not output["ok"]}
                else:
                    self.reply(200, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Method not found"}})
                    return
            except Exception:
                self.reply(200, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32603, "message": "Application tool unavailable"}})
                return
            self.reply(200, {"jsonrpc": "2.0", "id": identifier, "result": result})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True, name="assistant-mcp")
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_port}/mcp", "headers": {"Authorization": bearer},
               "server_name": "immomanager", "tools": list(assistant_tools.TOOLS)}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
