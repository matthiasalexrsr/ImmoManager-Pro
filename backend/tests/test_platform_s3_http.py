"""Owned HTTP S3 protocol fixture with independent SigV4 verification and private serving."""

import hashlib
import hmac
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.config import settings
from backend.db.access_models import StorageBindingORM
from backend.services import file_storage
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.upload_policy import UploadStaticFiles


@pytest.fixture
def s3_server():
    objects, requests = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body=b"", **headers):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def dispatch(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.command, self.path))
            authorization = self.headers.get("Authorization", "")
            assert authorization.startswith("AWS4-HMAC-SHA256 ")
            fields = dict(part.strip().split("=", 1) for part in authorization.split(" ", 1)[1].split(","))
            credential = fields["Credential"].split("/")
            assert credential[0] == "SYNTHETIC_ACCESS"
            canonical_headers = "".join(
                name + ":" + " ".join(self.headers[name].split()) + "\n" for name in fields["SignedHeaders"].split(";")
            )
            payload_hash = hashlib.sha256(body).hexdigest()
            assert self.headers["x-amz-content-sha256"] == payload_hash
            request_hash = hashlib.sha256(
                (
                    self.command
                    + "\n"
                    + self.path
                    + "\n\n"
                    + canonical_headers
                    + "\n"
                    + fields["SignedHeaders"]
                    + "\n"
                    + payload_hash
                ).encode()
            ).hexdigest()
            string = (
                "AWS4-HMAC-SHA256\n"
                + self.headers["x-amz-date"]
                + "\n"
                + "/".join(credential[1:])
                + "\n"
                + request_hash
            )
            key = b"AWS4SYNTHETIC_SECRET"
            for segment in credential[1:]:
                key = hmac.new(key, segment.encode(), hashlib.sha256).digest()
            signature = hmac.new(key, string.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, fields["Signature"]):
                self.reply(403, b"<Error><Code>SignatureDoesNotMatch</Code></Error>")
                return
            if self.command == "PUT":
                assert self.headers["If-None-Match"] == "*"
                if self.path in objects:
                    self.reply(412, b"<Error><Code>PreconditionFailed</Code></Error>")
                    return
                objects[self.path] = body
                self.reply(200)
            elif self.path not in objects:
                self.reply(404, b"<Error><Code>NoSuchKey</Code></Error>")
            elif self.command == "DELETE":
                del objects[self.path]
                self.reply(204)
            else:
                data = objects[self.path]
                if self.headers.get("Range") == "bytes=2-5":
                    self.reply(206, data[2:6])
                else:
                    self.reply(200, data, **{"x-amz-meta-sha256": hashlib.sha256(data).hexdigest()})

        do_PUT = do_GET = do_HEAD = do_DELETE = dispatch

    server = HTTPServer(("127.0.0.1", 0), Handler)
    assert server.server_port not in (8000, 8765)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", objects, requests
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_effective_selection_signed_wire_protocol_private_range_scope_and_binding(s3_server, tmp_path, monkeypatch):
    endpoint, objects, requests = s3_server
    engine = create_engine(f"sqlite:///{tmp_path / 'bindings.db'}")
    cast(Table, StorageBindingORM.__table__).create(engine)
    import backend.db.session as sessions

    monkeypatch.setattr(sessions, "SessionLocal", sessionmaker(bind=engine))
    for name, value in {
        "file_storage_backend": "s3",
        "s3_endpoint_url": endpoint,
        "s3_access_key": "SYNTHETIC_ACCESS",
        "s3_secret_key": "SYNTHETIC_SECRET",
        "s3_bucket": "fixture",
        "uploads_dir": str(tmp_path / "uploads"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(file_storage, "_storage", None)
    storage = file_storage.get_file_storage()  # Actual production selection and transport.
    assert isinstance(storage, file_storage.S3Storage)
    data = b"%PDF-1.4\x00\xffretained original"
    key = "documents/ä original.pdf"
    assert storage.save(key, BytesIO(data), "application/pdf").startswith("/uploads/")
    assert storage.get(key) == data and storage.exists(key)
    storage.save(key, BytesIO(data), "application/pdf")  # Conditional collision, verified byte-identical replay.
    with pytest.raises(file_storage.StorageUnavailable):
        storage.save(key, BytesIO(b"changed"), "application/pdf")
    assert next(iter(objects)) == "/fixture/documents/%C3%A4%20original.pdf"
    part = storage._client.get_object(Bucket="fixture", Key=key, Range="bytes=2-5")["Body"]
    try:
        assert part.read() == data[2:6]
    finally:
        part.close()
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    owner = auth.register_user("wire-owner", "wire@example.test", "Owner", "Secret123", "eigentuemer")
    restricted = auth.register_user(
        "wire-reader",
        "reader@example.test",
        "Reader",
        "Secret123",
        "readonly",
        portfolio_access="selected",
        portfolio_ids=[],
    )
    mini = FastAPI()
    mini.add_middleware(PortfolioScopeMiddleware)
    mini.mount("/uploads", UploadStaticFiles(directory=settings.uploads_dir))
    client = TestClient(mini)
    assert client.get(storage.get_url(key)).status_code == 401
    headers = {"Authorization": "Bearer " + auth.create_access_token(owner.id), "Range": "bytes=2-5"}
    response = client.get(storage.get_url(key), headers=headers)
    assert response.status_code == 206 and response.content == data[2:6]
    assert response.headers["cache-control"] == "private, no-store"
    before = len(requests)
    response = client.get(
        storage.get_url(key), headers={"Authorization": "Bearer " + auth.create_access_token(restricted.id)}
    )
    assert response.status_code in (403, 404) and len(requests) == before
    bad = file_storage.S3Storage(
        endpoint_url=endpoint, access_key="SYNTHETIC_ACCESS", secret_key="wrong", bucket="fixture"
    )
    with pytest.raises(file_storage.StorageUnavailable):
        bad.get(key)
    assert storage.delete(key) and storage.get(key) is None and not storage.exists(key)
    with pytest.raises(file_storage.StorageUnavailable):
        storage.save(key, BytesIO(data), "application/pdf")
    engine.dispose()
