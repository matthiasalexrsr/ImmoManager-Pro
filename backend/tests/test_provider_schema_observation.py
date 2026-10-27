"""Complete shape capture and private snapshots without source value reports."""

import json
from copy import deepcopy
from typing import Any

import pytest

from backend.services.providers.schema_observation import (
    JsonSchemaObserver,
    SchemaObservationError,
    is_profile_secret_key,
    json_snapshot,
    private_profile_snapshot,
)
from backend.services.providers.teha_types import TehaAccount, TehaDocument


def field(report, pointer, array_positions=()):
    return next(row for row in report["fields"] if row["pointer"] == pointer
                and row["array_positions"] == list(array_positions))


def test_every_array_row_is_observed_including_field_and_type_change_at_10007():
    rows: list[dict[str, Any]] = [{"stable": "synthetic-private-value"} for _ in range(10_007)]
    rows[-1] = {"stable": None, "late": {"nested": False}}
    input_data = {"rows": rows}
    original = deepcopy(input_data)
    observer = JsonSchemaObserver().observe(input_data)
    report = observer.report()
    stable = field(report, "/rows/0/stable", (1,))
    assert stable["type_occurrences"] == {"null": 1, "string": 10_006}
    assert stable["occurrences"] == stable["object_parent_occurrences"] == 10_007
    assert stable["nullable_observed"] is True and stable["missing_in_objects"] == 0
    late = field(report, "/rows/0/late", (1,))
    assert late["occurrences"] == 1 and late["missing_in_objects"] == 10_006
    assert field(report, "/rows/0/late/nested", (1,))["types"] == ["boolean"]
    assert input_data == original
    assert "synthetic-private-value" not in json.dumps(report)
    assert "synthetic-private-value" not in repr(observer)


def test_shared_python_aliases_still_count_every_occurrence():
    shared = {"value": 7}
    report = JsonSchemaObserver().observe([shared] * 10_007).report()
    assert field(report, "/0/value", (0,))["occurrences"] == 10_007
    assert field(report, "/0", (0,))["types"] == ["object"]


def test_missing_and_null_are_distinct_and_mixed_primitive_types_are_not_guessed():
    report = JsonSchemaObserver().observe({"rows": [{"value": None}, {"value": True},
        {"value": 1}, {"value": 1.5}, {"value": "private"}, {}]}).report()
    observed = field(report, "/rows/0/value", (1,))
    assert observed["type_occurrences"] == {"boolean": 1, "integer": 1, "null": 1, "number": 1, "string": 1}
    assert observed["occurrences"] == 5 and observed["missing_in_objects"] == 1
    assert observed["object_parent_occurrences"] == 6 and observed["null_occurrences"] == 1


def test_json_pointer_escaping_empty_keys_and_numeric_object_keys_are_exact():
    report = JsonSchemaObserver().observe({"a/b": {"~": "private", "": 7, "0": False}}).report()
    assert field(report, "/a~1b/~0")["types"] == ["string"]
    assert field(report, "/a~1b/")["types"] == ["integer"]
    assert field(report, "/a~1b/0")["types"] == ["boolean"]


def test_array_zero_and_object_zero_have_separate_statistics_even_at_same_pointer():
    observer = JsonSchemaObserver().observe({"items": [{"name": "private"}]})
    observer.observe({"items": {"0": {"name": None}}})
    report = observer.report()
    assert field(report, "/items/0/name", (1,))["types"] == ["string"]
    assert field(report, "/items/0/name")["types"] == ["null"]
    assert report["observations"] == 2


@pytest.mark.parametrize("value,kind", [(None, "null"), (True, "boolean"), (1, "integer"),
                                     (1.5, "number"), ("private", "string"), ({}, "object"), ([], "array")])
def test_root_values_and_empty_containers_are_observed(value, kind):
    observed = field(JsonSchemaObserver().observe(value).report(), "")
    assert observed["type_occurrences"] == {kind: 1}
    assert observed["object_parent_occurrences"] is None


def test_independent_batches_merge_without_mutating_the_other_or_prior_report():
    first = JsonSchemaObserver().observe({"rows": [{"a": True}]})
    second = JsonSchemaObserver().observe({"rows": [{"b": None}, {"a": 7}]})
    before = second.report()
    first.merge(second)
    report = first.report()
    assert report["observations"] == 2
    assert field(report, "/rows/0/a", (1,))["type_occurrences"] == {"boolean": 1, "integer": 1}
    assert field(report, "/rows/0/a", (1,))["missing_in_objects"] == 1
    assert second.report() == before
    report["fields"].clear()
    assert first.report()["fields"]


@pytest.mark.parametrize("bad,code", [(float("nan"), "non_finite_json_number"),
    (float("inf"), "non_finite_json_number"), ({7: "private-value"}, "non_string_json_key"),
    ({"late": {"private-value"}}, "non_json_value")])
def test_invalid_late_observation_is_safe_and_does_not_change_prior_state(bad, code):
    observer = JsonSchemaObserver().observe({"accepted": True})
    before = observer.report()
    with pytest.raises(SchemaObservationError) as captured:
        observer.observe([{"valid": 1}, bad])
    assert str(captured.value) == code
    assert "private-value" not in repr(captured.value)
    assert observer.report() == before


def test_cycles_are_rejected_without_a_hang_or_partial_merge():
    cycle: list[Any] = []
    cycle.append(cycle)
    observer = JsonSchemaObserver().observe({"valid": True})
    before = observer.report()
    with pytest.raises(SchemaObservationError, match="^cyclic_json_value$"):
        observer.observe(cycle)
    assert observer.report() == before
    with pytest.raises(SchemaObservationError, match="^cyclic_json_value$"):
        json_snapshot(cycle)


def test_observation_and_snapshot_are_iterative_beyond_python_recursion_depth():
    source: dict[str, Any] = {"tail": "private-value"}
    for _ in range(1200):
        source = {"child": source}
    observer = JsonSchemaObserver().observe(source)
    assert len(observer.report()["fields"]) == 1202
    copied = json_snapshot(source)
    original_cursor, copy_cursor = source, copied
    for _ in range(1200):
        assert copy_cursor is not original_cursor
        original_cursor, copy_cursor = original_cursor["child"], copy_cursor["child"]
    assert copy_cursor == {"tail": "private-value"}
    copy_cursor["tail"] = "changed"
    assert original_cursor["tail"] == "private-value"


@pytest.mark.parametrize("key", ["accessToken", "Refresh_Token", "PASSWORD-HASH", "Authorization",
    "Set-Cookie", "nestedClientSecret", "myApiKey", "privateKey", "Credentials", "csrfToken",
    "secrets", "secretKey", "currentSecretKeys", "sharedKey", "signingKey", "encryptionKey"])
def test_secret_key_policy_is_case_and_separator_robust(key):
    assert is_profile_secret_key(key)
    assert private_profile_snapshot({"nested": [{key: "secret", "name": "private-profile"}]}) == {
        "nested": [{"name": "private-profile"}]}


def test_profile_retains_unknown_values_and_roles_but_strips_known_secret_aliases_recursively():
    original = {"email": "synthetic@example.invalid", "Username": "synthetic-user", "rollen": ["synthetic-role"],
        "extra": {"count": 7, "unknown": True, "neutral": "session-secret", "PasswordHash": "password-secret",
        "rows": ["session-secret", "keep", {"Cookie": "cookie-secret", "value": 42}]}}
    before = deepcopy(original)
    profile = private_profile_snapshot(original, known_secret_values=("session-secret", "password-secret"))
    assert profile == {"email": "synthetic@example.invalid", "Username": "synthetic-user", "rollen": ["synthetic-role"],
        "extra": {"count": 7, "unknown": True, "rows": ["keep", {"value": 42}]}}
    assert original == before
    profile["rollen"].append("external mutation")
    assert original["rollen"] == ["synthetic-role"]


def test_private_account_and_document_snapshot_methods_also_handle_deep_nesting():
    source: dict[str, Any] = {"Password": "secret", "value": "private-profile"}
    for _ in range(1200):
        source = {"child": source}
    filtered = private_profile_snapshot(source)
    account = TehaAccount(account_id=7, mandant_id=1, _source=filtered)
    account_copy = account.private_profile_snapshot()
    for _ in range(1200):
        account_copy = account_copy["child"]
    assert account_copy == {"value": "private-profile"}
    assert "private-profile" not in repr(account)
    doc = TehaDocument(reference="ref", filename="private.pdf", lieg_nr="number",
                       _source={"properties": source, "attachments": [source]})
    for copied in (doc.properties_snapshot(), doc.attachments_snapshot()[0]):
        for _ in range(1200):
            copied = copied["child"]
        assert copied == {"Password": "secret", "value": "private-profile"}


def test_secret_field_names_and_types_remain_observable_without_secret_values():
    source = {"accessToken": "synthetic-private-token", "password": "synthetic-private-password", "profile": {"roles": []}}
    report = JsonSchemaObserver().observe(source).report()
    assert field(report, "/accessToken")["types"] == ["string"]
    assert field(report, "/password")["types"] == ["string"]
    assert field(report, "/profile/roles")["types"] == ["array"]
    serialized = json.dumps(report)
    assert "synthetic-private-token" not in serialized and "synthetic-private-password" not in serialized
