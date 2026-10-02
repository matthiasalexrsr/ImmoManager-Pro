"""Sanitized contract fixtures; no live portal account or endpoint calls."""

import base64
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from backend.services.providers import teha_transport as module
from backend.services.providers.teha_transport import TEHA_ORIGIN, TehaTransport
from backend.services.providers.teha_types import TehaError, parse_naive_iso_datetime

ACCESS = "synthetic-access-token"
REFRESH = "synthetic-refresh-token"
SECRET = "synthetic-private-password"
PDF = b"%PDF-1.7\nsynthetic-original\n%%EOF\n"


def login_payload(**updates):
    return {"id": 7, "mandantId": 1, "accessToken": ACCESS, "refreshToken": REFRESH,
            "error": None, "name": "synthetic-private-account", **updates}


def period(object_id=101, period_number=1, **updates):
    return {"liegId": {"id": object_id, "abrechnungLaufendeNr": period_number},
            "liegenschaftenNummer": "synthetic-number", "abrechnungVon": "2025-01-01T00:00:00",
            "abrechnungBis": "2025-12-31T00:00:00", "unknown": {"private": ["preserved"]}, **updates}


def document(reference="synthetic-ref", **updates):
    return {"reference": reference, "fileName": "synthetic.pdf", "properties": {
        "Liegenschafts_ID": "101", "Abrechnung_laufende_Nummer": "1",
        "Abrechnungszeitraum_von": "01.01.2025", "unknown": "preserved"},
        "attachments": [], **updates}


def order(**updates):
    return {"terminId": 901, "auftragNummer": 801, "abrLfdNr": 1,
            "liegenschaftsnummer": "synthetic-number", "fullLiegNummer": "separate-full-number",
            "terminVon": "2026-10-05T09:00:00", "terminBis": "2026-10-05T13:00:00",
            "abrechnungBis": "2025-12-31T00:00:00", "ortsteil": None, **updates}


def user(**updates):
    return {"id": 11, "neId": 21, "lfdNr": "01", "serviceterminId": None,
            "bewohnerName": "synthetic-private-person", "kontaktdaten": {"private": "contact"}, **updates}


def make_transport(handler, **options):
    """All requests, including login, are routed exclusively to MockTransport."""
    def dispatch(request):
        assert str(request.url).startswith(TEHA_ORIGIN + "/")
        if request.url.path == "/api/user":
            return httpx.Response(200, json=login_payload())
        assert request.headers["Authorization"] == "Bearer " + ACCESS
        return handler(request)

    client = TehaTransport(transport=httpx.MockTransport(dispatch), **options)
    client.authenticate("synthetic-user", SECRET)
    return client


def assert_error(code, call, *, retryable=None):
    with pytest.raises(TehaError) as captured:
        call()
    assert captured.value.code == code
    if retryable is not None:
        assert captured.value.retryable is retryable
    for secret in (SECRET, ACCESS, REFRESH, "server-private-detail"):
        assert secret not in str(captured.value)
        assert secret not in repr(captured.value)
    return captured.value


def test_observed_authentication_and_private_session_close():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=login_payload(unknown_secret="must-not-be-retained"),
                              headers={"Set-Cookie": "private-session=synthetic; Secure; HttpOnly"})

    transport = TehaTransport(transport=httpx.MockTransport(handler))
    account = transport.authenticate("synthetic-user", SECRET)
    assert requests[0].method == "POST"
    assert requests[0].url == TEHA_ORIGIN + "/api/user"
    assert json.loads(requests[0].content) == {"Mandant": 1, "Username": "synthetic-user", "PasswordHash": SECRET}
    assert "Authorization" not in requests[0].headers
    assert account.account_id == 7 and account.mandant_id == 1
    assert account.source_snapshot() == {"id": 7, "mandantId": 1}
    assert transport.authenticated
    assert transport._refresh_token == REFRESH
    assert SECRET not in repr(transport) and ACCESS not in repr(transport)
    assert "must-not-be-retained" not in repr(account)
    transport.close()
    assert not transport.authenticated
    assert transport._access_token is None and transport._refresh_token is None
    assert not list(transport._client.cookies)
    assert_error("transport_closed", transport.list_property_periods)
    assert len(requests) == 1
    transport.close()  # Closing is idempotent.


def test_context_manager_clears_tokens_even_on_caller_exception():
    transport = make_transport(lambda request: httpx.Response(200, json={}))
    with pytest.raises(RuntimeError), transport:
        raise RuntimeError("caller failed")
    assert not transport.authenticated and transport._refresh_token is None
    assert_error("transport_closed", lambda: transport.__enter__())


def test_four_period_rows_are_two_distinct_objects_with_unknown_fields_preserved():
    rows = [period(101, 1), period(101, 2), period(102, 1), period(102, 2)]
    with make_transport(lambda request: httpx.Response(200, json={
        "success": True, "fehlermeldung": None, "liegenschaften": rows})) as transport:
        periods = transport.list_property_periods()
    assert len(periods) == 4
    assert {item.object_id for item in periods} == {101, 102}
    assert {item.identity for item in periods} == {(101, 1), (101, 2), (102, 1), (102, 2)}
    assert periods[0].period_from_raw == "2025-01-01T00:00:00"
    snapshot = periods[0].source_snapshot()
    snapshot["unknown"]["private"].append("external mutation")
    assert periods[0].source_snapshot()["unknown"] == {"private": ["preserved"]}
    assert "synthetic-number" not in repr(periods[0])


def test_more_than_ten_thousand_rows_are_fully_available_without_paging_guesses():
    requests = []
    rows = [period(object_id=number + 1) for number in range(10_007)]

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "fehlermeldung": "", "liegenschaften": rows})

    with make_transport(handler) as transport:
        result = transport.list_property_periods()
    assert len(result) == 10_007
    assert result[-1].object_id == 10_007
    assert len(requests) == 1 and requests[0].url.query == b""


def test_document_paths_use_lieg_nr_string_and_ref_without_interpreting_filename():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json={"documents": [document(fileName="../../synthetic.pdf"),
                document(reference="second-ref", attachments=[{"unknown": "preserved"}])]})
        return httpx.Response(200, json={"content": base64.b64encode(PDF).decode()})

    with make_transport(handler) as transport:
        result = transport.list_documents("synthetic-number")
        assert len(result) == 2
        assert result[0].filename == "../../synthetic.pdf"  # Display only, never a local path.
        assert result[1].attachments_snapshot() == [{"unknown": "preserved"}]
        assert result[0].properties_snapshot()["Liegenschafts_ID"] == "101"
        content = transport.read_document(result[0].lieg_nr, result[0].reference)
    assert requests[0].url.path == "/api/Liegenschaften/documents"
    assert requests[0].method == requests[1].method == "POST"
    assert json.loads(requests[0].content) == {"LiegNr": "synthetic-number"}
    assert json.loads(requests[1].content) == {"Ref": "synthetic-ref", "LiegNr": "synthetic-number"}
    assert content.content == PDF
    assert content.sha256 == hashlib.sha256(PDF).hexdigest()
    assert content.size_bytes == len(PDF) and content.media_type == "application/pdf"
    assert "synthetic-ref" not in repr(content)
    assert "Liegenschafts_ID" not in repr(result[0])


def test_order_detail_uses_termin_id_instead_of_order_number_and_keeps_null_source():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "fehlermeldung": None,
            **({"auftraege": [order()]} if request.url.path == "/api/auftrag" else {"nutzerInAuftrag": [user()]})})

    with make_transport(handler) as transport:
        orders = transport.list_technical_orders()
        users = transport.read_order_users(orders[0].termin_id)
    assert orders[0].termin_id == 901 and orders[0].order_number == 801
    assert orders[0].source_snapshot()["fullLiegNummer"] == "separate-full-number"
    assert requests[1].url.path == "/api/Auftrag/901"
    assert users[0].user_id == 11 and users[0].unit_id == 21 and users[0].sequence_number == "01"
    assert users[0].source_snapshot()["serviceterminId"] is None
    assert "synthetic-private-person" not in repr(users[0])


@pytest.mark.parametrize("value", [True, False, None, "101", 0, -1, 1.5])
def test_inventory_object_identity_is_strictly_positive_numeric(value):
    with make_transport(lambda request: httpx.Response(200, json={
        "success": True, "liegenschaften": [period(object_id=value)]})) as transport:
        assert_error("provider_schema_changed", transport.list_property_periods)


@pytest.mark.parametrize("row", [period(liegId={"id": 101}), period(liegId=[]),
                                period(abrechnungVon=123), period(liegenschaftenNummer=101)])
def test_required_inventory_shape_is_not_guessed(row):
    with make_transport(lambda request: httpx.Response(200, json={"success": True, "liegenschaften": [row]})) as transport:
        assert_error("provider_schema_changed", transport.list_property_periods)


@pytest.mark.parametrize("payload", [{}, {"success": "true", "liegenschaften": []},
                                   {"success": True, "liegenschaften": {}},
                                   {"success": True, "liegenschaften": [None]}])
def test_invalid_success_and_list_shapes(payload):
    with make_transport(lambda request: httpx.Response(200, json=payload)) as transport:
        assert_error("provider_schema_changed", transport.list_property_periods)


def test_success_false_does_not_echo_provider_error():
    with make_transport(lambda request: httpx.Response(200, json={
        "success": False, "fehlermeldung": "server-private-detail " + SECRET})) as transport:
        assert_error("provider_operation_failed", transport.list_property_periods)


@pytest.mark.parametrize("operation", ["list_documents", "read_document"])
def test_optional_explicit_failure_overrides_an_otherwise_valid_document_body(operation):
    payload = {"success": False, "fehlermeldung": SECRET, "documents": [],
               "content": base64.b64encode(PDF).decode()}
    with make_transport(lambda request: httpx.Response(200, json=payload)) as transport:
        call = (lambda: transport.list_documents("number")) if operation == "list_documents" else (
            lambda: transport.read_document("number", "ref"))
        assert_error("provider_operation_failed", call)


@pytest.mark.parametrize("response, code", [
    (lambda: httpx.Response(200, text="<html>server-private-detail</html>"), "provider_response_not_json"),
    (lambda: httpx.Response(200, content=b"{", headers={"Content-Type": "application/json"}), "provider_response_invalid_json"),
    (lambda: httpx.Response(200, content=b'{"success":true,"success":false}', headers={"Content-Type": "application/json"}), "provider_response_invalid_json"),
    (lambda: httpx.Response(200, content=b'{"unknown":NaN}', headers={"Content-Type": "application/json"}), "provider_response_invalid_json"),
    (lambda: httpx.Response(200, content=b'{"unknown":1e9999}', headers={"Content-Type": "application/json"}), "provider_response_invalid_json"),
    (lambda: httpx.Response(200, content=b'\xff', headers={"Content-Type": "application/json"}), "provider_response_invalid_json"),
    (lambda: httpx.Response(200, json=[]), "provider_schema_changed"),
])
def test_response_must_be_unambiguous_finite_utf8_json_object(response, code):
    with make_transport(lambda request: response()) as transport:
        assert_error(code, transport.list_property_periods)


@pytest.mark.parametrize("payload, code", [
    (login_payload(error="server-private-detail " + SECRET), "authentication_failed"),
    (login_payload(accessToken=""), "provider_schema_changed"),
    (login_payload(accessToken="unsafe\r\nheader"), "provider_schema_changed"),
    (login_payload(accessToken="unsafe token"), "provider_schema_changed"),
    (login_payload(accessToken="unicode-ü"), "provider_schema_changed"),
    (login_payload(refreshToken=7), "provider_schema_changed"),
    (login_payload(id=True), "provider_schema_changed"),
    (login_payload(id="7"), "provider_schema_changed"),
    ({key: value for key, value in login_payload().items() if key != "error"}, "provider_schema_changed"),
    (login_payload(mandantId=2), "provider_account_mismatch"),
])
def test_bad_login_shapes_clear_prior_auth_and_cookies(payload, code):
    responses = [login_payload(), payload]

    def handler(request):
        return httpx.Response(200, json=responses.pop(0), headers={"Set-Cookie": "private-session=synthetic; Secure"})

    with TehaTransport(transport=httpx.MockTransport(handler)) as transport:
        transport.authenticate("synthetic-user", SECRET)
        assert_error(code, lambda: transport.authenticate("synthetic-user", SECRET))
        assert not transport.authenticated and transport._refresh_token is None
        assert not list(transport._client.cookies)


@pytest.mark.parametrize("username,password", [("", SECRET), ("user\nsecret", SECRET), ("user", ""), (None, SECRET)])
def test_invalid_credentials_are_rejected_before_request(username, password):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500)

    with TehaTransport(transport=httpx.MockTransport(handler)) as transport:
        assert_error("invalid_credentials_input", lambda: transport.authenticate(username, password))
    assert requests == []


def test_login_http_401_is_safe_and_no_refresh_endpoint_is_attempted():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, text="server-private-detail " + SECRET)

    with TehaTransport(transport=httpx.MockTransport(handler)) as transport:
        assert_error("authentication_failed", lambda: transport.authenticate("user", SECRET))
        assert_error("authentication_required", transport.list_property_periods)
    assert len(requests) == 1 and requests[0].url.path == "/api/user"


def test_http_401_clears_session_and_subsequent_reads_make_no_network_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={"private": SECRET})

    with make_transport(handler) as transport:
        assert_error("authentication_expired", transport.list_property_periods)
        assert not transport.authenticated and transport._refresh_token is None
        assert_error("authentication_required", transport.list_technical_orders)
    assert len(requests) == 1


@pytest.mark.parametrize("status,code,retryable", [(403, "provider_permission_denied", False),
    (404, "provider_http_error", False), (408, "provider_temporarily_unavailable", True),
    (425, "provider_temporarily_unavailable", True), (503, "provider_temporarily_unavailable", True)])
def test_http_error_classification_is_safe_without_automatic_retry(status, code, retryable):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="server-private-detail " + SECRET)

    with make_transport(handler) as transport:
        error = assert_error(code, transport.list_property_periods, retryable=retryable)
    assert error.http_status == status and len(requests) == 1


@pytest.mark.parametrize("header,expected", [("15", 15.0), ("invalid-private-value", None), ("NaN", None), ("-1", None)])
def test_429_exposes_safe_retry_after_without_automatic_replay(header, expected):
    with make_transport(lambda request: httpx.Response(429, headers={"Retry-After": header})) as transport:
        error = assert_error("provider_rate_limited", transport.list_property_periods, retryable=True)
    assert error.retry_after_seconds == expected


def test_retry_after_http_date():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60), usegmt=True)
    with make_transport(lambda request: httpx.Response(429, headers={"Retry-After": future})) as transport:
        error = assert_error("provider_rate_limited", transport.list_property_periods)
    assert 50 <= error.retry_after_seconds <= 60


@pytest.mark.parametrize("location", ["https://foreign.invalid/private?token=" + ACCESS, "/api/user"])
def test_redirects_are_rejected_without_following_or_echoing_location(location):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": location})

    with make_transport(handler) as transport:
        assert_error("provider_redirect_denied", transport.list_property_periods)
    assert len(requests) == 1


@pytest.mark.parametrize("failure,code", [(httpx.ReadTimeout, "provider_timeout"),
                                        (httpx.ConnectError, "provider_network_error")])
def test_network_errors_do_not_expose_exception_details(failure, code):
    def handler(request):
        raise failure("server-private-detail " + SECRET, request=request)

    with make_transport(handler) as transport:
        assert_error(code, transport.list_property_periods, retryable=True)


class Blocks(httpx.SyncByteStream):
    def __init__(self, blocks):
        self.blocks = blocks
        self.closed = False

    def __iter__(self):
        yield from self.blocks

    def close(self):
        self.closed = True


def test_response_budget_counts_streamed_bytes_and_closes_response():
    stream = Blocks([b" " * 150, b" " * 150])
    with make_transport(lambda request: httpx.Response(200, stream=stream,
        headers={"Content-Type": "application/json"}), max_response_bytes=250) as transport:
        assert_error("response_budget_exceeded", transport.list_property_periods)
    assert stream.closed


def test_content_length_budget_can_be_increased_without_record_cap():
    response = {"success": True, "liegenschaften": [period()], "unknown": "x" * 300}
    with make_transport(lambda request: httpx.Response(200, json=response), max_response_bytes=250) as transport:
        assert_error("response_budget_exceeded", transport.list_property_periods)
    with make_transport(lambda request: httpx.Response(200, json=response), max_response_bytes=2000) as transport:
        assert len(transport.list_property_periods()) == 1


def test_decompressed_body_is_budgeted_even_if_compressed_content_length_is_small():
    raw = json.dumps({"success": True, "liegenschaften": [], "padding": "x" * 5000}).encode()
    compressed = gzip.compress(raw)
    assert len(compressed) < 250
    with make_transport(lambda request: httpx.Response(200, content=compressed, headers={
        "Content-Type": "application/json", "Content-Encoding": "gzip"}), max_response_bytes=250) as transport:
        assert_error("response_budget_exceeded", transport.list_property_periods)


def test_response_deadline_is_separate_from_socket_timeout(monkeypatch):
    clock = iter([0.0, 0.0, 11.0])
    with make_transport(lambda request: httpx.Response(200, stream=Blocks([b"{}", b" "]),
        headers={"Content-Type": "application/json"}), response_deadline_seconds=10) as transport:
        monkeypatch.setattr(module, "monotonic", lambda: next(clock))
        assert_error("provider_response_deadline", transport.list_property_periods, retryable=True)


@pytest.mark.parametrize("updates", [{"max_response_bytes": 0}, {"max_document_bytes": -1},
    {"max_response_bytes": True}, {"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
    {"timeout_seconds": True}, {"response_deadline_seconds": float("nan")}, {"timeout_seconds": 10**400}])
def test_technical_budgets_must_be_positive_finite_and_not_booleans(updates):
    assert_error("invalid_transport_budget", lambda: TehaTransport(**updates))


@pytest.mark.parametrize("row", [document(reference=1), document(fileName=None),
                                document(properties=[]), document(attachments={})])
def test_malformed_document_metadata_is_not_importable(row):
    with make_transport(lambda request: httpx.Response(200, json={"documents": [row]})) as transport:
        assert_error("provider_schema_changed", lambda: transport.list_documents("synthetic-number"))


@pytest.mark.parametrize("encoded", ["!invalid!", "JVBERi0=garbage", "JVBERi0==", "JVBERi1=", "üinvalid"])
def test_invalid_noncanonical_base64_is_rejected(encoded):
    with make_transport(lambda request: httpx.Response(200, json={"content": encoded})) as transport:
        assert_error("provider_document_invalid_base64", lambda: transport.read_document("number", "ref"))


def test_non_pdf_content_is_not_labelled_pdf():
    with make_transport(lambda request: httpx.Response(200, json={
        "content": base64.b64encode(b"<html>private-error</html>").decode()})) as transport:
        assert_error("provider_document_not_pdf", lambda: transport.read_document("number", "ref"))


def test_document_budget_checks_actual_bytes_and_is_adjustable():
    def handler(request):
        return httpx.Response(200, json={"content": base64.b64encode(PDF).decode()})

    with make_transport(handler, max_document_bytes=len(PDF) - 1) as transport:
        assert_error("document_budget_exceeded", lambda: transport.read_document("number", "ref"))
    with make_transport(handler, max_document_bytes=len(PDF)) as transport:
        assert transport.read_document("number", "ref").content == PDF


@pytest.mark.parametrize("identifier", [True, 0, -1, "901", "../user", "https://foreign.invalid"])
def test_order_path_only_accepts_observed_numeric_termin_identity(identifier):
    requests = []
    with make_transport(lambda request: requests.append(request)) as transport:
        assert_error("provider_schema_changed", lambda: transport.read_order_users(identifier))
    assert requests == []


@pytest.mark.parametrize("method,path,login", [
    ("POST", "/api/auftrag", False), ("POST", "/api/user/refresh", False),
    ("GET", "https://foreign.invalid/private", False), ("GET", "/api/Auftrag/../user", False),
    ("GET", "/api/Auftrag/901?other=1", False), ("POST", "/api/user", False),
    ("GET", "/api/liegenschaften", True),
])
def test_internal_request_primitive_is_also_limited_to_observed_operations(method, path, login):
    requests = []
    with make_transport(lambda request: requests.append(request)) as transport:
        assert_error("provider_operation_not_allowed", lambda: transport._request(method, path, login=login))
    assert requests == []


@pytest.mark.parametrize("row", [order(terminId=True), order(auftragNummer="801"),
                                order(abrLfdNr=1.5), order(terminVon=None)])
def test_malformed_technical_order_shapes(row):
    with make_transport(lambda request: httpx.Response(200, json={"success": True, "auftraege": [row]})) as transport:
        assert_error("provider_schema_changed", transport.list_technical_orders)


@pytest.mark.parametrize("row", [user(id=True), user(neId="21"), user(lfdNr=1)])
def test_malformed_order_user_identity_does_not_infer_local_user_or_unit(row):
    with make_transport(lambda request: httpx.Response(200, json={"success": True, "nutzerInAuftrag": [row]})) as transport:
        assert_error("provider_schema_changed", lambda: transport.read_order_users(901))


@pytest.mark.parametrize("value", ["not-a-date", "01.01.2025", "2025-01-01", "2025-01-01T00:00:00Z", None])
def test_explicit_date_conversion_rejects_unknown_format_or_invented_timezone(value):
    assert_error("provider_datetime_invalid", lambda: parse_naive_iso_datetime(value))


def test_raw_iso_dates_are_preserved_and_optional_conversion_stays_naive():
    raw = "2025-01-01T00:00:00"
    parsed = parse_naive_iso_datetime(raw)
    assert parsed == datetime(2025, 1, 1)
    assert parsed.tzinfo is None
