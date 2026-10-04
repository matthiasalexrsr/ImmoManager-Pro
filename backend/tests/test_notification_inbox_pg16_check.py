"""Prepared pure native-tree/record counterexamples; no PG connection fixture.

The frozen input was Root's real synthetic PG16.15 catalog sample. Pure parser
inputs do not prove catalog binding; Root must run its independent native gate.
"""

import json
from pathlib import Path
from time import monotonic

import pytest

from backend.services.notification_inbox_pg16_check import (
    PG16IdentityColumn,
    PG16InboxCheckError,
    PG16InboxCheckLimits,
    _checked_constraint_tree,
    parse_pg16_notification_identity_tree,
    validate_pg16_notification_identity_check,
)

SAMPLE = Path(__file__).with_name("fixtures") / "notification_inbox_pg16_check_snapshot.json"
COLUMNS = (PG16IdentityColumn("actor_id", 1, -1, 100),
           PG16IdentityColumn("notification_id", 2, -1, 100))


@pytest.fixture
def native_sample():
    sample = json.loads(SAMPLE.read_text(encoding="utf-8-sig"))
    assert sample["server_version_num"] == "160015"
    return sample


def test_actual_frozen_pg16_native_tree_is_the_supported_pure_input(native_sample):
    parse_pg16_notification_identity_tree(native_sample["checks"][0]["native_tree"], COLUMNS)


@pytest.mark.parametrize("before,after", [
    (":boolop and", ":boolop or"),
    (":opno 521", ":opno 525"),
    (":opfuncid 147", ":opfuncid 99999"),
    (":opretset false", ":opretset true"),
    (":funcid 1317", ":funcid 99999"),
    (":funcresulttype 23", ":funcresulttype 25"),
    (":funcvariadic false", ":funcvariadic true"),
    (":inputcollid 100", ":inputcollid 9999"),
    (":resulttype 25", ":resulttype 1043"),
    (":relabelformat 2", ":relabelformat 0"),
    (":varno 1", ":varno 2"),
    (":varlevelsup 0", ":varlevelsup 1"),
    (":varnosyn 1", ":varnosyn 2"),
    (":vartype 1043", ":vartype 25"),
    (":vartypmod -1", ":vartypmod 24"),
    (":varnullingrels (b)", ":varnullingrels (b 1)"),
    (":consttype 23", ":consttype 20"),
    (":constisnull false", ":constisnull true"),
    (":constbyval true", ":constbyval false"),
    ("4 [ 0 0 0 0 0 0 0 0 ]", "4 [ 1 0 0 0 0 0 0 0 ]"),
    ("4 [ 0 0 0 0 0 0 0 0 ]", "4 [ 0 0 0 0 ]"),
    ("{CONST", "{PARAM"),
    (":boolop and", ":boolop and :boolop and"),
    (":boolop and", ":newfield false :boolop and"),
])
def test_frozen_native_tree_semantic_mutations_refuse(native_sample, before, after):
    tree = native_sample["checks"][0]["native_tree"]
    assert before in tree
    with pytest.raises(PG16InboxCheckError):
        parse_pg16_notification_identity_tree(tree.replace(before, after, 1), COLUMNS)


def test_native_two_guards_for_one_column_are_not_both_identity_guards(native_sample):
    tree = native_sample["checks"][0]["native_tree"].replace(
        ":varattno 2", ":varattno 1"
    ).replace(":varattnosyn 2", ":varattnosyn 1")
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_guard_invalid$"):
        parse_pg16_notification_identity_tree(tree, COLUMNS)


@pytest.mark.parametrize("change", ["trailing", "missing-close", "quoted-atom", "huge-location"])
def test_native_tree_malformed_container_or_unsupported_atom_refuses(native_sample, change):
    tree = native_sample["checks"][0]["native_tree"]
    if change == "trailing":
        tree += " extra"
    elif change == "missing-close":
        tree = tree[:-1]
    elif change == "quoted-atom":
        tree = tree.replace(":boolop and", ':boolop "and"')
    else:
        tree = tree.replace(":location 398", ":location " + "9" * 500)
    with pytest.raises(PG16InboxCheckError):
        parse_pg16_notification_identity_tree(tree, COLUMNS)


@pytest.mark.parametrize("limits", [PG16InboxCheckLimits(tree_bytes=128),
                                   PG16InboxCheckLimits(tokens=16),
                                   PG16InboxCheckLimits(depth=2)])
def test_native_tree_boundaries_refuse(native_sample, limits):
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_budget_exceeded$"):
        parse_pg16_notification_identity_tree(native_sample["checks"][0]["native_tree"], COLUMNS, limits=limits)


def _record(sample):
    # Project the real synthetic native fields into the actual SQL query record.
    # The remaining query booleans are explicit parser-fixture facts, not claimed
    # observations of a live server. Public native API never accepts this DTO.
    check = sample["checks"][0]
    tree = check["native_tree"].encode("utf-8")
    relation = {"oid": check["relation_oid"], "relnamespace": 90000}
    row = {"conrelid": relation["oid"], "connamespace": relation["relnamespace"],
           "convalidated": check["convalidated"], "conkey": check["conkey"],
           "conislocal": True, "coninhcount": 0, "connoinherit": False,
           "condeferrable": False, "condeferred": False, "contypid": 0,
           "confrelid": 0, "enforced": True, "size": len(tree), "tree": tree}
    return row, relation


@pytest.mark.parametrize("field,value", [
    ("convalidated", False), ("enforced", False), ("conrelid", 1),
    ("connamespace", 1), ("conkey", [1]), ("conkey", [1, 1]),
    ("coninhcount", 1), ("conislocal", False), ("condeferrable", True),
])
def test_native_constraint_record_projection_refuses_broken_binding(native_sample, field, value):
    row, relation = _record(native_sample)
    row[field] = value
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_guard_invalid$"):
        _checked_constraint_tree(row, relation, COLUMNS, PG16InboxCheckLimits(), None)


def test_native_constraint_prefix_cannot_claim_a_larger_unread_tree(native_sample):
    row, relation = _record(native_sample)
    row["size"] += 1
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_catalog_invalid$"):
        _checked_constraint_tree(row, relation, COLUMNS, PG16InboxCheckLimits(), None)


def test_expired_real_deadline_refuses_pure_parse(native_sample):
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_timeout$"):
        parse_pg16_notification_identity_tree(native_sample["checks"][0]["native_tree"], COLUMNS,
                                             deadline=monotonic() - 1)


def test_catalog_record_dto_is_not_accepted_as_native_connection(native_sample):
    with pytest.raises(PG16InboxCheckError, match="^notification_inbox_pg16_check_catalog_invalid$"):
        validate_pg16_notification_identity_check(native_sample)
