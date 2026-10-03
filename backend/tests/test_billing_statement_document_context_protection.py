"""Pure immutable context guard; no DB/Auth/App or native finalization fixture."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from backend.services.billing_statement_document_contexts import (
    KEY,
    DocumentContextIntegrityError,
    protect_period_document_contexts,
)
from backend.tests.test_billing_statement_document_contexts import capture, draft, parents, rehash


@pytest.mark.parametrize("status", ["draft", "review"])
def test_only_actual_new_finalization_can_add_an_original_context(status):
    snapshot = parents()
    current = draft(snapshot)
    current["status"] = status
    original = deepcopy(current)
    replacement = capture(snapshot, deepcopy(current))
    replacement["status"] = "finalized"
    protect_period_document_contexts(current, replacement)
    assert current == original and KEY not in current["owner_cost_share"]


@pytest.mark.parametrize("status", ["finalized", "delivered", "disputed", "corrected"])
def test_old_absence_cannot_be_backfilled(status):
    snapshot = parents()
    current = draft(snapshot)
    replacement = capture(snapshot, deepcopy(current))
    current["status"] = status
    replacement["status"] = "finalized"
    with pytest.raises(DocumentContextIntegrityError):
        protect_period_document_contexts(current, replacement)


@pytest.mark.parametrize("status", ["draft", "review", "delivered", "corrected"])
def test_capture_family_cannot_be_added_outside_new_finalization(status):
    snapshot = parents()
    current = draft(snapshot)
    replacement = capture(snapshot, deepcopy(current))
    replacement["status"] = status
    with pytest.raises(DocumentContextIntegrityError):
        protect_period_document_contexts(current, replacement)


@pytest.mark.parametrize("mutation", ["remove", "issuer", "object", "capture", "source", "partial", "null"])
def test_existing_family_cannot_be_overwritten_or_removed(mutation):
    snapshot = parents()
    current = capture(snapshot, draft(snapshot))
    rehash(snapshot, current)
    replacement = deepcopy(current)
    frozen = replacement["owner_cost_share"][KEY]
    entry = frozen["statements"]["statement-1-a"]
    if mutation == "remove":
        del replacement["owner_cost_share"][KEY]
    elif mutation == "issuer":
        entry["issuer"]["identity"]["name"] = "Replacement issuer"
    elif mutation == "object":
        entry["rental_object"]["unit_label"] = "Replacement label"
    elif mutation == "capture":
        entry["captured_by"] = "Other actor"
    elif mutation == "source":
        entry["party_digest"] = "0" * 64
    elif mutation == "partial":
        del frozen["statements"]["statement-1-b"]
    else:
        replacement["owner_cost_share"][KEY] = None
    with pytest.raises(DocumentContextIntegrityError):
        protect_period_document_contexts(current, replacement)


@pytest.mark.parametrize("status", ["delivered", "disputed", "corrected"])
def test_status_changes_preserve_the_exact_context(status):
    snapshot = parents()
    current = capture(snapshot, draft(snapshot))
    rehash(snapshot, current)
    original = deepcopy(current)
    replacement = deepcopy(current)
    replacement["status"] = status
    protect_period_document_contexts(current, replacement)
    assert current == original and replacement["owner_cost_share"] == current["owner_cost_share"]


def test_absent_legacy_context_remains_absent_and_untouched():
    snapshot = parents()
    current = draft(snapshot)
    rehash(snapshot, current)
    replacement = deepcopy(current)
    replacement["status"] = "corrected"
    protect_period_document_contexts(current, replacement)
    assert KEY not in current["owner_cost_share"] and KEY not in replacement["owner_cost_share"]


def test_guard_is_pure_in_a_fresh_process_with_fixed_fail_closed_imports():
    snapshot = parents()
    current = capture(snapshot, draft(snapshot))
    rehash(snapshot, current)
    code = '''
import importlib.abc, json, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("backend.auth", "backend.config", "backend.dependencies", "backend.app", "backend.storage",
            "backend.repositories", "backend.services.billing_settlement", "backend.services.billing_statement_party_storage",
            "backend.services.billing_statement_document_context_storage", "sqlalchemy")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("pure context guard reached ambient runtime: " + fullname)
sys.meta_path.insert(0, Reject())
from backend.services.billing_statement_document_contexts import DocumentContextIntegrityError, protect_period_document_contexts
data = json.loads(sys.stdin.read())
protect_period_document_contexts(data, dict(data, status="delivered"))
replacement = json.loads(json.dumps(data))
replacement["owner_cost_share"].pop("statement_document_contexts")
try:
    protect_period_document_contexts(data, replacement)
except DocumentContextIntegrityError:
    print("PURE_CONTEXT_PROTECTION")
else:
    raise AssertionError("immutable original disappeared")
'''
    result = subprocess.run([sys.executable, "-c", code], input=json.dumps(current), text=True,
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "PURE_CONTEXT_PROTECTION" in result.stdout
