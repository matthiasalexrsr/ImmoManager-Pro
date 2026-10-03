"""Selected SQLite L2 evidence validation; no live context and no mutation.

The caller owns image selection, explicit keys, read transaction and cancellation.
Static History metadata registration is an existing image-API dependency, not
an authenticated runtime or a write/CommitAuthority contract.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from dataclasses import dataclass

from sqlalchemy import Integer

from ...db.integration_history_models import (
    TABLES as HISTORY_TABLE_NAMES,
    IntegrationRunEventORM,
    IntegrationRunORM,
)
from ...db.teha_receive_release_l2 import L2_TABLE_NAMES, frozen_l2_tables
from ...db.teha_receive_schema import TehaReceiveSchemaError
from ..document_version_validation import (
    TABLES as ORIGINAL_TABLE_NAMES,
    VERSION_FIELDS,
    verify_document_versions,
)
from ..iban_encryption import IBANKeyring
from ..integrations.history_crypto import stamp
from ..integrations.history_types import HistoryError, HistoryLimits
from ..integrations.history_validation import (
    checked_json, raw_projection, rows, validate_history_journal, verified_artifacts,
)
from ..recovery_archive import RecoveryError
from .teha_import_validation import TehaImportEvidenceError, mapping_reference, validate_document_manifest
from .teha_receive_contract import ExternalIdentity
from .teha_receive_image_evidence import (
    TehaImageEvidenceError, exchange_from_artifacts, prove_content, prove_source, prove_source_association,
)
from .teha_receive_image_schema import validate_teha_image_schema

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TARGET = {"property": "internal_property_id", "period": "billing_period_id", "unit": "unit_id",
           "user": "tenant_id", "technical_order": "task_id"}
_IMAGE_RELATIONS = frozenset((
    *L2_TABLE_NAMES, *HISTORY_TABLE_NAMES, *ORIGINAL_TABLE_NAMES,
    "portfolios", "properties", "billing_periods", "units", "tenants", "tasks",
    "documents", "contracts", "resource_portfolio_grants",
))


class TehaImageError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TehaImageLimits:
    """Explicit allocation budgets, never a maximum number of retained rows."""
    batch_size: int
    row_bytes: int
    original_metadata_bytes: int
    schema_bytes: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (
                self.batch_size, self.row_bytes, self.original_metadata_bytes, self.schema_bytes)):
            raise ValueError("TEHA image budgets must be positive integers")


@dataclass(frozen=True)
class TehaImageReport:
    family_present: bool
    mappings: int = 0
    receipts: int = 0
    document_receipts: int = 0
    task_receipts: int = 0
    command_digest_reconstructed: bool = False


def _fail(code="TEHA_IMAGE_EVIDENCE_INVALID"):
    raise TehaImageError(code)


def _evidence_json(raw):
    try:
        return checked_json(raw)
    except HistoryError:
        _fail()


class _Image:
    def __init__(self, connection, keys, history_limits, limits, deadline):
        self.connection, self.keys, self.history_limits = connection, keys, history_limits
        self.limits, self.deadline = limits, deadline
        self.tables = {table.name: table for table in frozen_l2_tables()}

    def check(self):
        if time.monotonic() >= self.deadline:
            _fail("TEHA_IMAGE_BUDGET_EXCEEDED")

    def one(self, sql, parameters=None):
        self.check()
        cursor = self.connection.execute(sql, parameters or {})
        try:
            value = cursor.fetchone()
            self.check()
            return dict(zip((item[0] for item in cursor.description), value, strict=True)) if value is not None else None
        finally:
            cursor.close()

    def assert_main_name_binding(self):
        """Reject actual name-resolution escapes before reused image APIs run."""
        names = tuple(sorted(_IMAGE_RELATIONS))
        marks = ",".join("?" for _ in names)
        # SQLite identifiers resolve ASCII case-insensitively, with TEMP first.
        # Index aliases matter too: reused schema APIs use index PRAGMAs.
        shadow = self.one(
            "SELECT 1 AS present FROM temp.sqlite_schema AS shadow WHERE "
            f"(shadow.type IN ('table','view') AND shadow.name COLLATE NOCASE IN ({marks})) OR "
            "(shadow.type='index' AND EXISTS (SELECT 1 FROM main.sqlite_schema AS selected "
            f"WHERE selected.type='index' AND selected.tbl_name COLLATE NOCASE IN ({marks}) "
            "AND selected.name COLLATE NOCASE=shadow.name)) LIMIT 1", names + names,
        )
        if shadow is not None:
            _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
        # Only fixed relation-presence facts are retained, not the catalog stock.
        self.check()
        cursor = self.connection.execute(
            "SELECT name FROM main.sqlite_schema WHERE type IN ('table','view') "
            f"AND name COLLATE NOCASE IN ({marks})", names,
        )
        try:
            present = set()
            for (name,) in cursor:
                self.check()
                present.add(name.lower())
        finally:
            cursor.close()
        missing = tuple(name for name in names if name not in present)
        self.check()
        if not missing:
            return
        marks = ",".join("?" for _ in missing)
        # An unrelated attachment is harmless; a missing-main relation supplied
        # by that attachment would make the image proof span different images.
        cursor = self.connection.execute(
            "SELECT CASE WHEN length(CAST(name AS BLOB))<=? THEN name ELSE NULL END "
            "FROM pragma_database_list WHERE name NOT IN ('main','temp')", (self.limits.schema_bytes,),
        )
        try:
            for (alias,) in cursor:
                self.check()
                if alias is None:
                    _fail("TEHA_IMAGE_BUDGET_EXCEEDED")
                quoted = alias.replace('"', '""')
                if self.one(
                    f'SELECT 1 AS present FROM "{quoted}".sqlite_schema '
                    f"WHERE type IN ('table','view') AND name COLLATE NOCASE IN ({marks}) LIMIT 1", missing,
                ) is not None:
                    _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
        finally:
            cursor.close()
        self.check()

    def projection(self, fields, integers=()):
        text = [name for name in fields if name not in integers]
        valid = lambda name: f"({name} IS NULL OR (typeof({name})='text' AND length(CAST({name} AS BLOB))<=:row_bytes))"
        columns = [name if name in integers else f"CASE WHEN {valid(name)} THEN {name} ELSE NULL END AS {name}"
                   for name in fields]
        columns.append("CASE WHEN " + " AND ".join(valid(name) for name in text) + " THEN 0 ELSE 1 END AS _invalid_text")
        return ",".join(columns)

    def bounded_one(self, table, fields, identifier, *, integers=()):
        value = self.one(f"SELECT {self.projection(fields, integers)} FROM {table} WHERE id=:id",
                         {"id": identifier, "row_bytes": self.limits.row_bytes})
        if value is None or value.pop("_invalid_text"):
            _fail()
        return value

    def batches(self, table, fields, *, integers=(), condition="1=1"):
        """Bounded BINARY keyset; all stock is scanned regardless of batch count."""
        last = None
        while True:
            self.check()
            suffix = " AND id COLLATE BINARY>:last" if last is not None else ""
            cursor = self.connection.execute(
                f"SELECT {self.projection(fields, integers)} FROM {table} WHERE ({condition}){suffix} "
                "ORDER BY id COLLATE BINARY LIMIT :batch_size",
                {"row_bytes": self.limits.row_bytes, "batch_size": self.limits.batch_size, "last": last},
            )
            try:
                names = [column[0] for column in cursor.description]
                batch = cursor.fetchall()
            finally:
                cursor.close()
            if not batch:
                return
            for raw in batch:
                self.check()
                value = dict(zip(names, raw, strict=True))
                if value.pop("_invalid_text") or not isinstance(value["id"], str) or not value["id"]:
                    _fail()
                last = value["id"]
                yield value

    def l2_row(self, value, table):
        for column in self.tables[table].columns:
            item = value[column.name]
            if item is None:
                if not column.nullable:
                    _fail()
            elif isinstance(column.type, Integer):
                if type(item) is not int or item <= 0:
                    _fail()
            elif not isinstance(item, str) or not item:
                _fail()
        for name in ("external_identity_hash", "source_sha256", "revision", "mapping_sha256", "command_sha256", "content_sha256"):
            if name in value and value[name] is not None and not _SHA.fullmatch(value[name]):
                _fail()
        for name in ("created_at", "updated_at", "confirmed_at", "imported_at"):
            if name in value:
                stamp(value[name])
        connection = value["connection_key"]
        if len(connection) > 200 or connection != connection.strip() or any(ord(char) < 32 for char in connection):
            _fail()
        if table == L2_TABLE_NAMES[0]:
            if value["state"] != "confirmed":
                _fail()
            value["external_identity_json"] = _evidence_json(value["external_identity_json"])
        else:
            if value["state"] != "imported" or len(value["command_key"]) > 100:
                _fail()
            if value["operational_job_id"] is not None or value["work_item_id"] is not None:
                _fail("TEHA_IMAGE_JOB_BINDING_UNSUPPORTED")
            document = value["source_kind"] == "document"
            task = value["source_kind"] == "technical_order"
            if (not (document or task) or (document and (value["content_sha256"] is None
                    or value["document_id"] is None or value["document_version_id"] is None or value["task_id"] is not None))
                    or (task and (value["task_id"] is None or any(value[name] is not None for name in
                        ("content_sha256", "document_id", "document_version_id"))))):
                _fail()
        return value

    def mapping(self, identifier):
        table = self.tables[L2_TABLE_NAMES[0]]
        value = self.bounded_one(table.name, tuple(table.columns.keys()), identifier, integers=("generation",))
        return self.l2_row(value, table.name)

    def target(self, kind, identifier, portfolio):
        self.bounded_one("portfolios", ("id",), portfolio)
        context = dict.fromkeys(("portfolio_id", "property_id", "unit_id", "tenant_id", "billing_period_id"))
        context["portfolio_id"] = portfolio
        if kind == "property":
            parent = self.bounded_one("properties", ("id", "portfolio_id"), identifier)
            context["property_id"] = identifier
        elif kind in {"period", "unit"}:
            table = "billing_periods" if kind == "period" else "units"
            target = self.bounded_one(table, ("id", "property_id"), identifier)
            parent = self.bounded_one("properties", ("id", "portfolio_id"), target["property_id"])
            context["property_id"] = parent["id"]
            context["billing_period_id" if kind == "period" else "unit_id"] = identifier
        elif kind == "user":
            self.bounded_one("tenants", ("id",), identifier)
            grant = self.one("SELECT 1 AS present FROM resource_portfolio_grants WHERE resource_type='tenants' "
                             "AND resource_id=:id AND portfolio_id=:portfolio", {"id": identifier, "portfolio": portfolio})
            if grant is None:
                _fail("TEHA_IMAGE_TARGET_INVALID")
            context["tenant_id"] = identifier
            return context
        elif kind == "technical_order":
            target = self.bounded_one("tasks", ("id", "property_id", "unit_id"), identifier)
            parent = self.bounded_one("properties", ("id", "portfolio_id"), target["property_id"])
            context["property_id"] = parent["id"]
            if target["unit_id"] is not None:
                unit = self.bounded_one("units", ("id", "property_id"), target["unit_id"])
                if unit["property_id"] != parent["id"]:
                    _fail("TEHA_IMAGE_TARGET_INVALID")
                context["unit_id"] = unit["id"]
        else:
            _fail("TEHA_IMAGE_TARGET_INVALID")
        if parent["portfolio_id"] != portfolio:
            _fail("TEHA_IMAGE_TARGET_INVALID")
        return context

    def exchange(self, run_id, connection_key):
        # The full journal was authenticated on this same snapshot beforehand.
        run = next(rows(self.connection,
                        f"SELECT {raw_projection(IntegrationRunORM.__table__, self.history_limits)} "
                        "FROM integration_runs WHERE id=?", (run_id,)), None)
        if run is None or run["integration_id"] != "teha" or run["scope_kind"] != "installation":
            _fail("TEHA_IMAGE_SOURCE_BINDING_INVALID")
        request, response, count, terminal = None, None, 0, None
        for event in rows(self.connection,
                          f"SELECT {raw_projection(IntegrationRunEventORM.__table__, self.history_limits)} "
                          "FROM integration_run_events WHERE run_id=? ORDER BY event_number", (run_id,)):
            self.check()
            count += 1
            if count > 3:
                _fail("TEHA_IMAGE_SOURCE_BINDING_INVALID")
            artifacts = verified_artifacts(self.connection, run, event, self.keys, self.history_limits,
                                           deadline=self.deadline)
            if event["state"] == "accepted":
                request = artifacts.get("request")
            response, terminal = artifacts.get("response"), event
        if terminal is None or terminal["state"] != "completed" or terminal["success"] != 1:
            _fail("TEHA_IMAGE_SOURCE_BINDING_INVALID")
        return exchange_from_artifacts(request, response, connection_key)

    def mapping_proof(self, mapping):
        reference, checksum = mapping_reference(mapping)
        context = self.target(reference["kind"], reference["target_id"], reference["portfolio_id"])
        identity = ExternalIdentity.create(reference["kind"], **reference["external_identity"]["parts"])
        exchange = self.exchange(reference["source_history_run_id"], reference["connection_key"])
        _, source = prove_source(exchange, identity.kind, identity.token, reference["source_sha256"], expected_identity=identity)
        if mapping["generation"] > 1 and self.one(
                "SELECT 1 AS present FROM teha_external_mappings WHERE connection_key=:connection AND kind=:kind "
                "AND external_identity_hash=:identity AND generation=:generation",
                {"connection": mapping["connection_key"], "kind": mapping["kind"],
                 "identity": mapping["external_identity_hash"], "generation": mapping["generation"] - 1}) is None:
            _fail()
        return reference, checksum, context, identity, source

    def document(self, receipt, mapping, context, identity):
        version = self.bounded_one("document_versions", VERSION_FIELDS, receipt["document_version_id"], integers=("number", "size_bytes"))
        raw = self.one("SELECT CASE WHEN typeof(metadata_snapshot)='text' AND length(CAST(metadata_snapshot AS BLOB))"
                       "<=:maximum THEN metadata_snapshot ELSE NULL END AS snapshot FROM document_versions WHERE id=:id",
                       {"maximum": self.limits.original_metadata_bytes, "id": version["id"]})
        snapshot = _evidence_json(raw["snapshot"])
        if (version["number"] != 1 or version["operation"] != "archive_original"
                or version["actor_id"] != receipt["imported_by"] or version["request_sha256"] != receipt["command_sha256"]
                or version["idempotency_key"] != "generated-" + receipt["document_id"]):
            _fail("TEHA_IMAGE_ORIGINAL_BINDING_INVALID")
        extension = validate_document_manifest(version, receipt, snapshot, mapping=mapping, mapping_target_binding=context)
        content = self.exchange(extension["content_history_run_id"], receipt["connection_key"])
        prove_content(content, identity, version)

    def original_budget(self):
        # Prevent the generic verifier's special full snapshot read, and its
        # scalar projections, from materializing unbounded damaged image text.
        present = self.one("SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='document_versions'")
        if present is None:
            return
        fields = [name for name in VERSION_FIELDS if name not in {"number", "size_bytes"}]
        checks = [f"length(CAST({name} AS BLOB))>:row_bytes" for name in fields]
        checks.append("length(CAST(metadata_snapshot AS BLOB))>:metadata_bytes")
        if self.one("SELECT 1 AS bad FROM document_versions WHERE " + " OR ".join(checks) + " LIMIT 1",
                    {"row_bytes": self.limits.row_bytes, "metadata_bytes": self.limits.original_metadata_bytes}):
            _fail("TEHA_IMAGE_BUDGET_EXCEEDED")
        for table, fields in {
            "documents": ("id", "file_url", "property_id", "unit_id", "contract_id"),
            "properties": ("id", "portfolio_id"), "units": ("id", "property_id"), "portfolios": ("id",),
            "contracts": ("id", "property_id", "unit_id", "tenant_id"), "tenants": ("id",),
            "document_version_chunks": ("version_id", "portfolio_id"),
        }.items():
            if self.one(f"SELECT 1 AS bad FROM {table} WHERE " + " OR ".join(
                    f"length(CAST({name} AS BLOB))>:row_bytes" for name in fields) + " LIMIT 1",
                    {"row_bytes": self.limits.row_bytes}):
                _fail("TEHA_IMAGE_BUDGET_EXCEEDED")

    def validate(self):
        self.check()
        validate_history_journal(self.connection, self.keys, deadline=self.deadline, limits=self.history_limits)
        self.original_budget()
        verify_document_versions(self.connection, deadline=self.deadline)
        mappings, receipts, documents, tasks = 0, 0, 0, 0
        mapping_table, receipt_table = (self.tables[name] for name in L2_TABLE_NAMES)
        for mapping in self.batches(mapping_table.name, tuple(mapping_table.columns.keys()), integers=("generation",)):
            self.mapping_proof(self.l2_row(mapping, mapping_table.name))
            mappings += 1
        for receipt in self.batches(receipt_table.name, tuple(receipt_table.columns.keys()), integers=("mapping_generation",)):
            receipt = self.l2_row(receipt, receipt_table.name)
            mapping = self.mapping(receipt["mapping_id"])
            reference, checksum, context, mapped_identity, mapping_source = self.mapping_proof(mapping)
            if (receipt["portfolio_id"] != reference["portfolio_id"] or receipt["connection_key"] != reference["connection_key"]
                    or receipt["mapping_generation"] != reference["generation"] or receipt["mapping_sha256"] != checksum):
                _fail("TEHA_IMAGE_MAPPING_BINDING_INVALID")
            source = self.exchange(receipt["source_history_run_id"], receipt["connection_key"])
            identity, source_row = prove_source(source, receipt["source_kind"], receipt["external_identity_hash"], receipt["source_sha256"])
            prove_source_association(source, identity, source_row, mapped_identity, mapping_source)
            if receipt["source_kind"] == "document":
                self.document(receipt, mapping, context, identity)
                documents += 1
            else:
                task_context = self.target("technical_order", receipt["task_id"], receipt["portfolio_id"])
                if reference["kind"] != "property" or task_context["property_id"] != context["property_id"]:
                    _fail("TEHA_IMAGE_TARGET_INVALID")
                tasks += 1
            receipts += 1
        # Reverse closure: every TEHA extension belongs to its exact first
        # archive and receipt. Do not infer a TEHA receipt from live category.
        if self.one("SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='document_versions'"):
            condition = "CASE WHEN json_valid(metadata_snapshot) THEN json_type(metadata_snapshot,'$.teha_import') IS NOT NULL ELSE 0 END"
            for version in self.batches("document_versions", ("id", "document_id"), condition=condition):
                receipt = self.one("SELECT 1 AS present FROM teha_import_receipts WHERE document_version_id=:id "
                                   "AND document_id=:document AND source_kind='document'", {"id": version["id"], "document": version["document_id"]})
                if receipt is None:
                    _fail("TEHA_IMAGE_ORIGINAL_RECEIPT_MISSING")
        self.check()
        return TehaImageReport(True, mappings, receipts, documents, tasks)


def validate_teha_receive_image(connection, *, image_keys, history_limits, image_limits, deadline):
    """Validate all L2 evidence on one caller-owned, already read-only image.

    No independent command-digest reconstruction or write authority is claimed.
    Root must preserve the closure and compose this before recovery mutation.
    """
    if not isinstance(connection, sqlite3.Connection):
        _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
    try:
        context_valid = (connection.in_transaction
                         and connection.execute("PRAGMA query_only").fetchone()[0] == 1
                         and connection.execute("PRAGMA trusted_schema").fetchone()[0] == 0)
    except sqlite3.Error:
        _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
    if not context_valid:
        _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
    if (type(image_limits) is not TehaImageLimits or type(history_limits) is not HistoryLimits
            or isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)):
        _fail("TEHA_IMAGE_CONTEXT_REQUIRED")
    image = _Image(connection, image_keys, history_limits, image_limits, deadline)
    try:
        image.check()
        image.assert_main_name_binding()
        if not validate_teha_image_schema(connection, schema_bytes=image_limits.schema_bytes):
            # Entire absence is legacy-compatible only when no retained TEHA
            # original asserts the missing receipt family. No key lookup.
            if image.one("SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='document_versions'"):
                if image.one("SELECT 1 AS bad FROM document_versions WHERE CASE WHEN json_valid(metadata_snapshot) "
                             "THEN json_type(metadata_snapshot,'$.teha_import') IS NOT NULL ELSE 0 END LIMIT 1"):
                    _fail("TEHA_IMAGE_FAMILY_MISSING")
            return TehaImageReport(False)
        if type(image_keys) is not IBANKeyring:
            _fail("TEHA_IMAGE_KEYS_REQUIRED")
        return image.validate()
    except TehaImageError:
        raise
    except HistoryError as error:
        if error.code == "HISTORY_KEY_UNAVAILABLE":
            _fail("TEHA_IMAGE_KEYS_REQUIRED")
        if error.code == "HISTORY_BUDGET_EXCEEDED":
            _fail("TEHA_IMAGE_BUDGET_EXCEEDED")
        _fail("TEHA_IMAGE_HISTORY_INVALID")
    except TehaImageEvidenceError as error:
        _fail(str(error))
    except TehaReceiveSchemaError:
        _fail("TEHA_IMAGE_SCHEMA_INVALID")
    except (TehaImportEvidenceError, RecoveryError, sqlite3.Error, TypeError, ValueError, KeyError,
            UnicodeError, OverflowError, RecursionError):
        _fail()
