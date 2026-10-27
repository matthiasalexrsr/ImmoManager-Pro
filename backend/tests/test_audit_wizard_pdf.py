"""Content and injection regressions for the independent contract wizard."""
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend import app as application


def renderer():
    loaded = application._load_contract_wizard_mount()
    assert loaded is not None
    return loaded[0]


def pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(renderer()(data))).pages)


@pytest.mark.parametrize("amount", ["100.50", "100,50", 100.5])
def test_structured_wizard_keeps_decimal_amounts(amount):
    text = pdf_text({"miete": {"grund": amount, "betrieb": "20.25"}})
    assert "100,50" in text and "20,25" in text and "120,75" in text
    assert "10.050" not in text


def test_preview_pdf_preserves_every_character_without_markup_execution():
    literal = '<img src="file:///should-never-be-opened"/> Müller & Partner'
    blocks = [{"kind": "title", "text": "Wohnraum-Mietvertrag"},
              {"kind": "paragraph", "text": literal},
              {"kind": "paragraph", "text": "Grundmiete 100,50 Euro; Küchen 2; Sondervereinbarung"}]
    text = pdf_text({"_preview_blocks": blocks})
    assert literal in text and "100,50" in text and "Küchen 2" in text


def test_structured_pdf_treats_names_as_literal_text():
    literal = '<img src="file:///should-never-be-opened"/> Müller & Partner'
    text = pdf_text({"vermieter": [{"name": literal}]})
    assert " ".join(literal.split()) in " ".join(text.split())


def test_user_image_markup_cannot_trigger_a_server_side_request():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from PIL import Image

    image = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(image, format='PNG')
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(image.getvalue())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            markup = f'<img src="http://127.0.0.1:{server.server_port}/owned.png" width="2" height="2"/>'
            text = pdf_text({'vermieter': [{'name': markup}]})
            assert ' '.join(markup.split()) in ' '.join(text.split())
            assert requests == []
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_standalone_fastapi_adapter_uses_current_template_contract():
    renderer()  # Load the optional package through the application's normal path.
    from mietvertrag_wizard.fastapi_integration import mount_fastapi

    local = FastAPI()
    mount_fastapi(local)
    with TestClient(local) as client:
        page = client.get("/mietvertrag/")
        assert page.status_code == 200 and "Mietvertrag Wizard" in page.text
        invalid = client.post("/mietvertrag/api/pdf", json={"_preview_blocks": []})
        assert invalid.status_code == 422


@pytest.mark.parametrize("blocks", [None, [], "text", [{"kind": "image", "text": "x"}],
                                   [{"kind": "paragraph", "text": "x" * 10001}],
                                   [{"kind": "paragraph", "text": "x" * 10000}] * 21])
def test_invalid_or_excessive_preview_is_rejected_with_422(blocks):
    local = FastAPI()
    assert application._mount_contract_wizard_if_available(local)
    with TestClient(local) as client:
        response = client.post("/mietvertrag/api/pdf", json={"_preview_blocks": blocks})
    assert response.status_code == 422
