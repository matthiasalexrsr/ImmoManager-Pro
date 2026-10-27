"""Complete-envelope and private-sink tests; synthetic MockTransport only."""

import base64
import json
import traceback
from typing import Any

import httpx
import pytest

from backend.services.providers import teha_transport as module
from backend.services.providers.exchange_observation import (
    EXCHANGE_HEADER_POLICY_VERSION,
    EXCHANGE_SECRET_POLICY_VERSION,
    PrivateJsonExchange,
    observe_json_exchange,
    private_json_values,
)
from backend.services.providers.teha_transport import TEHA_ORIGIN, TehaTransport
from backend.services.providers.teha_types import TehaError
from backend.tests.test_teha_transport import ACCESS, PDF, REFRESH, SECRET, Blocks, login_payload, period


def client_for(handler, sink=None, **options):
    def dispatch(request):
        assert request.url.host == "kunden.socs.ws"
        if request.url.path == "/api/user":
            return httpx.Response(200, json=login_payload())
        return handler(request)
    client = TehaTransport(transport=httpx.MockTransport(dispatch), private_exchange_sink=sink, **options)
    client.authenticate("private-observer@example.invalid", SECRET)
    return client


def error_from(code, call):
    with pytest.raises(TehaError) as captured:
        call()
    assert captured.value.code == code
    return captured.value


def fields_by_pointer(schema):
    return {field["pointer"]: field for field in schema["fields"]}


def test_auth_observation_captures_private_request_profile_and_all_schema_without_secrets():
    captured: list[PrivateJsonExchange] = []
    cookie = "synthetic-cookie-private-value"
    other_secret = "synthetic-nested-key-private-value"
    payload = login_payload(email="private-observer@example.invalid", rollen=["private-role"],
        unknown={"nested": [None, {"value": 42}], "client_secret": other_secret,
                 "echo": "private bearer: " + ACCESS, "other_echo": "key=" + other_secret,
                 "cookie_echo": "session=" + cookie, "pw_echo": "password=" + SECRET})
    original = json.loads(json.dumps(payload))
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload,
        headers={"Set-Cookie": f"session={cookie}; Secure; HttpOnly"})),
        private_exchange_sink=captured.append) as client:
        account = client.authenticate("private-observer@example.invalid", SECRET)
        snapshot = client.private_last_exchange_snapshot()
        assert snapshot is not None
        assert snapshot == captured[0].private_snapshot()
        assert snapshot["request"]["method"] == "POST"
        assert snapshot["request"]["path"] == "/api/user"
        assert snapshot["request"]["body"] == {"Mandant": 1, "Username": "private-observer@example.invalid"}
        assert snapshot["response"]["body"]["unknown"] == {"nested": [None, {"value": 42}]}
        assert snapshot["secret_policy_version"] == EXCHANGE_SECRET_POLICY_VERSION
        assert snapshot["header_policy_version"] == EXCHANGE_HEADER_POLICY_VERSION
        schema = client.private_exchange_schema_snapshot()
        assert schema == captured[0].private_schema_snapshot()
        fields = fields_by_pointer(schema)
        assert fields["/request/body/PasswordHash"]["types"] == ["string"]
        assert fields["/response/body/accessToken"]["types"] == ["string"]
        assert "/response/headers/set-cookie/0" in fields
        assert account.private_profile_snapshot()["unknown"] == {"nested": [None, {"value": 42}]}
        for secret in (SECRET, ACCESS, REFRESH, cookie, other_secret):
            assert secret not in json.dumps(snapshot)
            assert secret not in json.dumps(schema)
            assert secret not in json.dumps(account.private_profile_snapshot())
            assert secret not in repr(captured[0]) and secret not in repr(client)
        assert "private-observer" not in json.dumps(schema) and "private-role" not in json.dumps(schema)
    assert payload == original and len(captured) == 1
    assert client.private_last_exchange_snapshot() is None
    assert client.private_exchange_schema_snapshot() is None


def test_document_content_envelope_request_and_duplicate_metadata_headers_are_preserved():
    captured: list[PrivateJsonExchange] = []
    encoded = base64.b64encode(PDF).decode()
    envelope = {"content": encoded, "unknown_extra": {"null": None, "arr": [], "object": {}},
                "responseToken": "synthetic-response-secret", "alias": "token=synthetic-response-secret"}
    with client_for(lambda request: httpx.Response(200, json=envelope, headers=[
        ("Content-Type", "application/json"), ("Cache-Control", "private"), ("Cache-Control", "max-age=0"),
        ("X-Unknown-Private-Key", "do-not-retain-header-value"), ("Authorization", "synthetic-header-secret"),
        ("Cookie", "some=synthetic-cookie-secret"), ("Set-Cookie", "session=synthetic-cookie-secret; Secure")]),
        captured.append) as client:
        original = client.read_document("private-number", "private-ref")
        snapshot = client.private_last_exchange_snapshot()
        assert snapshot["request"]["body"] == {"Ref": "private-ref", "LiegNr": "private-number"}
        assert snapshot["request"]["path"] == "/api/Liegenschaften/document-content"
        assert snapshot["request"]["query"] == {}
        assert snapshot["response"]["body"] == {"content": encoded, "unknown_extra": envelope["unknown_extra"]}
        assert snapshot["response"]["headers"]["cache-control"] == ["private", "max-age=0"]
        schema = fields_by_pointer(client.private_exchange_schema_snapshot())
        assert schema["/response/headers/cache-control/0"]["occurrences"] == 2
        assert "/response/headers/x-unknown-private-key/0" in schema
        assert "/request/headers/authorization/0" in schema
        for forbidden in ("authorization", "cookie", "set-cookie", "x-unknown-private-key"):
            assert forbidden not in snapshot["response"]["headers"]
        for value in (ACCESS, REFRESH, "synthetic-response-secret", "do-not-retain-header-value",
                      "synthetic-header-secret", "synthetic-cookie-secret"):
            assert value not in json.dumps(snapshot)
        assert original.content == PDF
        assert "private-ref" not in repr(captured[-1]) and "private-number" not in repr(captured[-1])
    assert len(captured) == 2


@pytest.mark.parametrize("payload, code", [
    ({"success": False, "fehlermeldung": "password failed: " + SECRET, "new": [1, None]},
     "provider_operation_failed"),
    ({"success": True, "liegenschaften": [{"late_bad_row": True}], "new": "private-extra"},
     "provider_schema_changed"),
    ({"success": True, "liegenschaften": {}, "new": None}, "provider_schema_changed"),
    ([{"new": "private-extra"}], "provider_schema_changed"),
    (None, "provider_schema_changed"),
])
def test_complete_json_observed_before_any_fachliche_projection_even_when_rejected(payload, code):
    captured: list[PrivateJsonExchange] = []
    with client_for(lambda request: httpx.Response(200, content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}), captured.append) as client:
        error_from(code, client.list_property_periods)
        snapshot = client.private_last_exchange_snapshot()
        # No password was sent with this GET. Echo redaction is explicitly based
        # on actual current session literals or secret-named source fields.
        assert snapshot["response"]["body"] == payload
        assert len(captured) == 2
        assert client.private_exchange_schema_snapshot()["observations"] == 1


@pytest.mark.parametrize("status, code", [
    (401, "authentication_expired"), (403, "provider_permission_denied"), (404, "provider_http_error"),
    (429, "provider_rate_limited"), (503, "provider_temporarily_unavailable"), (302, "provider_redirect_denied"),
])
def test_completed_error_status_json_is_observed_without_following_or_replaying(status, code):
    captured: list[PrivateJsonExchange] = []
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"new_error": [None, "Bearer " + ACCESS]},
                              headers={"Retry-After": "3", "Location": "https://foreign.invalid/private"})
    with client_for(handler, captured.append) as client:
        error = error_from(code, client.list_property_periods)
        assert error.http_status == status
        assert client.private_last_exchange_snapshot()["response"]["body"] == {"new_error": [None]}
        assert client.private_last_exchange_snapshot()["response"]["status"] == status
        assert len(captured) == 2 and len(requests) == 1
        assert requests[0].url.host == "kunden.socs.ws"
        if status == 429:
            assert error.retry_after_seconds == 3.0 and error.retryable
        if status == 401:
            assert not client.authenticated and not list(client._client.cookies)
            error_from("authentication_required", client.list_technical_orders)


@pytest.mark.parametrize("response, options, code", [
    (lambda: httpx.Response(200, text="<html>private</html>"), {}, "provider_response_not_json"),
    (lambda: httpx.Response(200, content=b'{', headers={"Content-Type": "application/json"}), {},
     "provider_response_invalid_json"),
    (lambda: httpx.Response(200, content=b'{"x":1,"x":2}', headers={"Content-Type": "application/json"}), {},
     "provider_response_invalid_json"),
    (lambda: httpx.Response(200, stream=Blocks([b'{}', b' ' * 300]),
                           headers={"Content-Type": "application/json"}), {"max_response_bytes": 250},
     "response_budget_exceeded"),
    (lambda: httpx.Response(401, content=b'{', headers={"Content-Type": "application/json"}), {},
     "authentication_expired"),
])
def test_incomplete_invalid_or_non_json_answers_never_create_an_observation(response, options, code):
    captured: list[PrivateJsonExchange] = []
    with client_for(lambda request: response(), captured.append, **options) as client:
        error_from(code, client.list_property_periods)
        assert client.private_last_exchange_snapshot() is None
        assert client.private_exchange_schema_snapshot() is None
        assert len(captured) == 1  # Only the completed login.


def test_ten_thousand_rows_and_late_top_level_fields_all_reach_private_sink_and_schema():
    rows = [period(object_id=index + 1) for index in range(10_007)]
    rows[-1]["late_schema"] = {"only_last": [None, 42]}
    payload = {"success": True, "liegenschaften": rows, "unknown_envelope": {"last": "retained"}}
    captured: list[PrivateJsonExchange] = []
    with client_for(lambda request: httpx.Response(200, json=payload), captured.append) as client:
        result = client.list_property_periods()
        assert len(result) == 10_007 and result[-1].object_id == 10_007
        private = captured[-1].private_response_snapshot()
        assert len(private["liegenschaften"]) == 10_007
        assert private["liegenschaften"][-1]["late_schema"] == {"only_last": [None, 42]}
        assert private["unknown_envelope"] == {"last": "retained"}
        fields = fields_by_pointer(client.private_exchange_schema_snapshot())
        assert fields["/response/body/liegenschaften/0"]["occurrences"] == 10_007
        assert fields["/response/body/liegenschaften/0/late_schema/only_last/0"]["types"] == ["integer", "null"]
        assert fields["/response/body/unknown_envelope/last"]["types"] == ["string"]
        assert fields["/response/body/liegenschaften/0/late_schema"]["missing_in_objects"] == 10_006


def test_default_retains_only_latest_exchange_and_shape_not_dynamic_field_history():
    number = 0
    def handler(request):
        nonlocal number
        number += 1
        return httpx.Response(200, json={"success": True, "liegenschaften": [], f"field_{number}": "private"})
    with client_for(handler) as client:
        for _ in range(20):
            assert client.list_property_periods() == []
        snapshot = client.private_last_exchange_snapshot()
        assert "field_20" in snapshot["response"]["body"]
        assert "field_1" not in snapshot["response"]["body"]
        schema = client.private_exchange_schema_snapshot()
        assert schema["observations"] == 1
        pointers = fields_by_pointer(schema)
        assert "/response/body/field_20" in pointers and "/response/body/field_1" not in pointers
        assert client._private_exchange_sink is None
    assert client._last_exchange is None and client._private_exchange_sink is None


def test_mutating_sink_or_snapshot_cannot_mutate_latest_observation_or_dto_projection():
    count = 0
    def sink(exchange):
        nonlocal count
        count += 1
        exchange._snapshot["response"]["body"].clear()
        exchange._schema["fields"].clear()
    with client_for(lambda request: httpx.Response(200, json={"success": True, "liegenschaften": [period()]}),
                    sink) as client:
        assert len(client.list_property_periods()) == 1
        snapshot = client.private_last_exchange_snapshot()
        snapshot["response"]["body"].clear()
        client.private_exchange_schema_snapshot()["fields"].clear()
        assert client.private_last_exchange_snapshot()["response"]["body"]["success"]
        assert client.private_exchange_schema_snapshot()["fields"]
        assert count == 2


def test_observation_failure_is_safe_and_never_returns_a_successful_import():
    def sink(exchange):
        if exchange.private_snapshot()["request"]["path"] != "/api/user":
            raise RuntimeError("private-host-error " + SECRET + ACCESS)
    with client_for(lambda request: httpx.Response(200, json={"success": True, "liegenschaften": [period()]}),
                    sink) as client:
        error = error_from("provider_observation_failed", client.list_property_periods)
        formatted = "".join(traceback.format_exception(error))
        assert error.__suppress_context__
        for value in (SECRET, ACCESS, "private-host-error"):
            assert value not in str(error) and value not in repr(error) and value not in formatted
        assert client.private_last_exchange_snapshot() is None


def test_internal_observer_failure_also_blocks_a_successful_import(monkeypatch):
    with client_for(lambda request: httpx.Response(200, json={"success": True, "liegenschaften": []})) as client:
        def fail(**kwargs):
            raise RuntimeError("unsafe " + ACCESS)
        monkeypatch.setattr(module, "observe_json_exchange", fail)
        error = error_from("provider_observation_failed", client.list_property_periods)
        assert ACCESS not in "".join(traceback.format_exception(error))
        assert client.private_last_exchange_snapshot() is None


def test_timeout_after_partial_json_and_response_deadline_never_emit_a_complete_exchange(monkeypatch):
    captured: list[PrivateJsonExchange] = []
    class PartialTimeout(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"partial":'
            raise httpx.ReadTimeout("private " + ACCESS)
    with client_for(lambda request: httpx.Response(200, stream=PartialTimeout(),
        headers={"Content-Type": "application/json"}), captured.append) as client:
        error = error_from("provider_timeout", client.list_property_periods)
        assert ACCESS not in "".join(traceback.format_exception(error))
        assert client.private_last_exchange_snapshot() is None and len(captured) == 1
    with client_for(lambda request: httpx.Response(200, stream=Blocks([b'{}', b' ']),
        headers={"Content-Type": "application/json"}), captured.append,
        response_deadline_seconds=10) as client:
        clock = iter([0.0, 0.0, 11.0])
        monkeypatch.setattr(module, "monotonic", lambda: next(clock))
        error_from("provider_response_deadline", client.list_property_periods)
        assert client.private_last_exchange_snapshot() is None and len(captured) == 2


def test_complete_json_401_clears_auth_even_when_response_budget_aborts_before_observation():
    captured: list[PrivateJsonExchange] = []
    with client_for(lambda request: httpx.Response(401, json={"padding": "x" * 300}), captured.append,
                    max_response_bytes=250) as client:
        error_from("response_budget_exceeded", client.list_property_periods)
        assert not client.authenticated and client._refresh_token is None
        assert not list(client._client.cookies)
        assert client.private_last_exchange_snapshot() is None and len(captured) == 1


@pytest.mark.parametrize("status", [200, 401])
def test_observation_failure_on_login_or_401_clears_auth_and_cookies(status):
    responses = 0
    def handler(request):
        nonlocal responses
        responses += 1
        return httpx.Response(200 if responses == 1 else status, json=login_payload(),
                              headers={"Set-Cookie": "session=synthetic-private-cookie; Secure"})
    def sink(exchange):
        if responses > 1:
            raise RuntimeError("private " + SECRET)
    with TehaTransport(transport=httpx.MockTransport(handler), private_exchange_sink=sink) as client:
        client.authenticate("private-user", SECRET)
        call = (lambda: client.authenticate("private-user", SECRET)) if status == 200 else client.list_property_periods
        error_from("provider_observation_failed", call)
        assert not client.authenticated and client._refresh_token is None
        assert not list(client._client.cookies)
        assert client.private_last_exchange_snapshot() is None
        assert responses == 2


def test_interrupting_auth_sink_cleans_cookie_session_and_preserves_interrupt():
    def sink(exchange):
        raise KeyboardInterrupt
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=login_payload(),
        headers={"Set-Cookie": "session=synthetic-private-cookie; Secure"})), private_exchange_sink=sink) as client:
        with pytest.raises(KeyboardInterrupt):
            client.authenticate("private-user", SECRET)
        assert not client.authenticated and not list(client._client.cookies)
        assert client.private_last_exchange_snapshot() is None


def test_failed_auth_json_is_observed_without_password_tokens_cookie_aliases_or_lingering_auth():
    payload = login_payload(error="password rejected: " + SECRET,
        username="private-user", unknown={"alias": "token=" + ACCESS, "nested": {"PasswordHash": SECRET}})
    captured: list[PrivateJsonExchange] = []
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
                       private_exchange_sink=captured.append) as client:
        error_from("authentication_failed", lambda: client.authenticate("private-user", SECRET))
        snapshot = client.private_last_exchange_snapshot()
        assert snapshot is not None
        assert snapshot["response"]["body"]["unknown"] == {"nested": {}}
        assert "error" not in snapshot["response"]["body"]
        assert not client.authenticated and not list(client._client.cookies)
        assert len(captured) == 1
        assert SECRET not in json.dumps(snapshot) and ACCESS not in json.dumps(snapshot)


def test_whole_envelope_secret_aliases_do_not_bypass_through_dto_private_source():
    payload = {"success": True, "unknown_api_key": "synthetic-envelope-secret",
               "liegenschaften": [period(unknown={"alias": "key=synthetic-envelope-secret", "safe": "preserved"})]}
    with client_for(lambda request: httpx.Response(200, json=payload)) as client:
        result = client.list_property_periods()
        assert result[0].source_snapshot()["unknown"] == {"safe": "preserved"}
        assert "synthetic-envelope-secret" not in json.dumps(client.private_last_exchange_snapshot())


def test_schema_redacts_known_secret_dynamic_field_names_including_pointer_escaping():
    secret = "synthetic/~private-token"
    payload = login_payload(accessToken=secret.replace("/", "_"),
                            unknown={"prefix-" + secret: "private", "safe": "preserved"})
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        account = client.authenticate("private-user", secret)
        for schema in (client.private_exchange_schema_snapshot(), account.profile_schema_snapshot()):
            encoded = json.dumps(schema)
            assert secret not in encoded and secret.replace("~", "~0").replace("/", "~1") not in encoded
            assert "[redacted]" in encoded
        assert account.private_profile_snapshot()["unknown"] == {"safe": "preserved"}


def test_auth_private_source_and_schema_share_all_secret_header_alias_knowledge():
    header_secret = "synthetic-sensitive-header-value"
    payload = login_payload(extra={"alias": "header=" + header_secret,
                                   "field-" + header_secret: "private", "safe": "preserved"})
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload,
        headers={"Authorization": header_secret}))) as client:
        account = client.authenticate("private-user", SECRET)
        assert account.private_profile_snapshot()["extra"] == {"safe": "preserved"}
        snapshot = client.private_last_exchange_snapshot()
        assert snapshot is not None
        assert snapshot["response"]["body"]["extra"] == {"safe": "preserved"}
        schema = account.profile_schema_snapshot()
        assert header_secret not in json.dumps(schema) and "[redacted]" in json.dumps(schema)
        fields = fields_by_pointer(schema)
        assert fields[""]["object_parent_occurrences"] is None
        assert fields["/accessToken"]["types"] == ["string"]
        assert fields["/extra/safe"]["occurrences"] == 1


def test_short_secret_matching_fixed_wrapper_does_not_erase_response_shape_projection():
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=login_payload()))) as client:
        account = client.authenticate("private-user", "body")
        fields = fields_by_pointer(account.profile_schema_snapshot())
        assert fields[""]["types"] == ["object"]
        assert fields["/accessToken"]["types"] == ["string"]
        assert fields["/error"]["types"] == ["null"]


def test_generic_private_snapshot_is_complete_iterative_nonmutating_and_conservative():
    source: Any = {"keep": [1, None, "safe"], "client_secret": "new-secret", "alias": "key=new-secret"}
    original = json.loads(json.dumps(source))
    copied = private_json_values(source)
    assert copied == {"keep": [1, None, "safe"]} and source == original
    copied["keep"].append("mutation")
    assert source == original
    nested: Any = {"leaf": "safe", "password": SECRET}
    for _ in range(1_200):
        nested = {"next": nested}
    private = private_json_values(nested)
    for _ in range(1_200):
        private = private["next"]
    assert private == {"leaf": "safe"}
    assert private_json_values({"text": "contains x", "other": 1}, known_secret_values=("x",)) == {"other": 1}


def test_generic_exchange_captures_actual_query_all_shapes_and_only_allowed_header_values():
    exchange = observe_json_exchange(method="GET", path="/synthetic/read",
        query=[["page", "2"], ["page", "3"], ["api_key", "synthetic-query-secret"]],
        body=None, request_headers=[("Cookie", "session=secret"), ("Accept", "application/json")],
        status=200, response_headers=[("Content-Type", "application/json"), ("X-Secret", "synthetic-secret")],
        payload={"unknown": [None, {}, []], "echo": "key=synthetic-query-secret"},
        known_secret_values=("synthetic-secret",))
    snapshot = exchange.private_snapshot()
    assert snapshot["request"]["query"] == {"page": ["2", "3"]}
    assert snapshot["request"]["body"] is None
    assert snapshot["response"]["body"] == {"unknown": [None, {}, []]}
    assert snapshot["request"]["headers"] == {"accept": ["application/json"]}
    assert snapshot["response"]["headers"] == {"content-type": ["application/json"]}
    assert "secret" not in repr(exchange)
    assert exchange.private_schema_snapshot()["observations"] == 1
    assert "/request/query/api_key/0" in fields_by_pointer(exchange.private_schema_snapshot())
    assert "synthetic-query-secret" not in json.dumps(snapshot)
    assert TEHA_ORIGIN not in repr(exchange)


@pytest.mark.parametrize("sink", [False, "private-invalid-sink"])
def test_invalid_sink_is_rejected_before_constructing_a_session(sink):
    error_from("invalid_observation_sink", lambda: TehaTransport(private_exchange_sink=sink))


def test_async_sink_cannot_be_accepted_as_a_completed_observation():
    async def async_sink(exchange):
        pass
    invalid_sink: Any = async_sink  # Deliberate runtime contract violation.
    error_from("invalid_observation_sink", lambda: TehaTransport(private_exchange_sink=invalid_sink))
    def wrapped_sink(exchange):
        return async_sink(exchange)
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=login_payload())),
                       private_exchange_sink=wrapped_sink) as client:
        error_from("provider_observation_failed", lambda: client.authenticate("private-user", SECRET))
        assert not client.authenticated and client.private_last_exchange_snapshot() is None


def test_non_none_sink_result_is_not_silently_treated_as_success():
    def sink(exchange):
        return False
    with TehaTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=login_payload())),
                       private_exchange_sink=sink) as client:
        error_from("provider_observation_failed", lambda: client.authenticate("private-user", SECRET))
        assert not client.authenticated


def test_private_exchange_repr_and_independent_copy_expose_no_payload_values():
    source = PrivateJsonExchange({"private": {"value": "synthetic-private"}}, {"fields": []})
    copy = source.independent_copy()
    copy._snapshot["private"]["value"] = "mutation"
    assert source.private_snapshot() == {"private": {"value": "synthetic-private"}}
    assert "synthetic-private" not in repr(source)
