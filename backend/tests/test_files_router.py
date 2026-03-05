from backend.routers.files import _file_url_to_key


def test_file_url_to_key_variants():
    assert _file_url_to_key('/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('https://example.com/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('s3://bucket/documents/x.pdf') == 'documents/x.pdf'
