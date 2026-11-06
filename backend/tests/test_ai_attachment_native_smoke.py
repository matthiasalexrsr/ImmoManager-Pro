"""The native acceptance must exercise actual global-chat attachment inspection."""
import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException

from backend.services import assistant
from scripts.check_desktop_runtime import verify_ai_attachment_worker


def test_real_native_attachment_helper_reads_all_formats_without_a_provider(tmp_path):
    from PIL import Image
    from reportlab.pdfgen.canvas import Canvas
    png = BytesIO()
    Image.new('RGB', (8, 4), 'teal').save(png, 'PNG')
    pdf = BytesIO()
    canvas = Canvas(pdf, pagesize=(144, 72), invariant=1)
    canvas.drawString(8, 36, 'LOCAL AI WORKER')
    canvas.showPage()
    canvas.save()
    result = verify_ai_attachment_worker(tmp_path, pdf.getvalue(), png.getvalue())
    assert len(result) == 3 and all(item['status'] == 'ready' for item in result.values())


def reply(raw, name):
    if name.endswith('.pdf'):
        mime, text, omissions = 'application/pdf', 'LOCAL AI WORKER', []
    elif name.endswith('.png'):
        mime, text, omissions = 'image/png', '', ['Bild ohne lokale OCR']
    else:
        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        text = 'LOCAL DOCX BODY LOCAL DOCX TABLE LOCAL DOCX HEADER LOCAL DOCX FOOTER'
        omissions = []
    return {'status': 'ready', 'name': name, 'mime': mime, 'byte_length': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'text': text,
            'text_truncated': False, 'omissions': omissions}


def test_native_attachment_smoke_requires_all_three_public_service_calls(tmp_path, monkeypatch):
    calls = []

    def inspect(raw, name):
        calls.append(name)
        return reply(raw, name)
    monkeypatch.setattr(assistant, 'inspect_attachment', inspect)
    result = verify_ai_attachment_worker(tmp_path, b'%PDF-synthetic', b'synthetic PNG')
    assert calls == ['ai-chat-smoke.pdf', 'ai-chat-smoke.png', 'ai-chat-smoke.docx']
    assert len(result) == 3 and all(item['original_unchanged'] for item in result.values())
    assert result['application/pdf']['expected_phrases'] == ['LOCAL AI WORKER']
    assert len(result['application/vnd.openxmlformats-officedocument.wordprocessingml.document']['expected_phrases']) == 4


@pytest.mark.parametrize('name,changes', [
    ('ai-chat-smoke.pdf', {'text': ''}),
    ('ai-chat-smoke.pdf', {'text_truncated': True}),
    ('ai-chat-smoke.pdf', {'omissions': ['Worker failure']}),
    ('ai-chat-smoke.pdf', {'sha256': 'incorrect'}),
    ('ai-chat-smoke.pdf', {'status': 'error'}),
    ('ai-chat-smoke.png', {'omissions': []}),
    ('ai-chat-smoke.png', {'mime': 'image/jpeg'}),
    ('ai-chat-smoke.docx', {'text': 'LOCAL DOCX BODY LOCAL DOCX TABLE'}),
])
def test_native_attachment_smoke_rejects_missing_text_metadata_or_coverage(tmp_path, monkeypatch, name, changes):
    def inspect(raw, actual):
        value = reply(raw, actual)
        if actual == name:
            value.update(changes)
        return value
    monkeypatch.setattr(assistant, 'inspect_attachment', inspect)
    with pytest.raises(AssertionError):
        verify_ai_attachment_worker(tmp_path, b'%PDF-synthetic', b'synthetic PNG')


def test_native_attachment_smoke_never_accepts_worker_http_failure(tmp_path, monkeypatch):
    def failed(*args):
        raise HTTPException(503, 'synthetic worker failure')
    monkeypatch.setattr(assistant, 'inspect_attachment', failed)
    with pytest.raises(HTTPException):
        verify_ai_attachment_worker(tmp_path, b'%PDF-synthetic', b'synthetic PNG')
