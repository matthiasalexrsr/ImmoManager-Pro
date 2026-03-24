"""Tests for error_helpers module."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from backend.error_helpers import (
    ERROR_CATALOG,
    DatabaseOperationError,
    safe_db_operation,
    safe_get_related,
    safe_parse_decimal,
)


class TestErrorCatalog:
    def test_catalog_has_expected_keys(self):
        expected = {"NOT_FOUND", "VALIDATION_ERROR", "AUTH_FAILED", "PERMISSION_DENIED",
                    "CONFLICT", "RATE_LIMITED", "DB_ERROR", "INTERNAL_ERROR"}
        assert set(ERROR_CATALOG.keys()) == expected

    def test_catalog_entries_have_required_fields(self):
        for code, entry in ERROR_CATALOG.items():
            assert "description" in entry, f"{code} missing description"
            assert "http_status" in entry, f"{code} missing http_status"


class TestDatabaseOperationError:
    def test_with_detail(self):
        err = DatabaseOperationError("create_user", "duplicate email")
        assert "create_user" in str(err)
        assert "duplicate email" in str(err)
        assert err.operation == "create_user"

    def test_without_detail(self):
        err = DatabaseOperationError("delete_user")
        assert "delete_user" in str(err)
        assert err.detail == ""


class TestSafeParseDecimal:
    def test_normal_value(self):
        assert safe_parse_decimal(12.5) == Decimal("12.5")

    def test_none(self):
        assert safe_parse_decimal(None) == Decimal("0")

    def test_invalid_string(self):
        assert safe_parse_decimal("not-a-number") == Decimal("0")

    def test_custom_fallback(self):
        assert safe_parse_decimal(None, Decimal("99")) == Decimal("99")

    def test_string_number(self):
        assert safe_parse_decimal("42.7") == Decimal("42.7")


class TestSafeGetRelated:
    def test_success(self):
        fetch = MagicMock(return_value={"id": "123"})
        result = safe_get_related(fetch, "123", "unit")
        assert result == {"id": "123"}

    def test_failure_returns_none(self):
        fetch = MagicMock(side_effect=Exception("not found"))
        result = safe_get_related(fetch, "bad-id", "unit")
        assert result is None


class TestSafeDbOperation:
    def test_success(self):
        @safe_db_operation("test_op")
        def good_func():
            return "ok"

        assert good_func() == "ok"

    def test_integrity_error(self):
        class FakeRepo:
            db = MagicMock()

            @safe_db_operation("create_item")
            def create(self):
                raise IntegrityError("stmt", {}, Exception("dup"))

        repo = FakeRepo()
        with pytest.raises(DatabaseOperationError):
            repo.create()
        repo.db.rollback.assert_called_once()

    def test_operational_error(self):
        class FakeRepo:
            db = MagicMock()

            @safe_db_operation("fetch_item")
            def fetch(self):
                raise OperationalError("stmt", {}, Exception("conn"))

        repo = FakeRepo()
        with pytest.raises(DatabaseOperationError):
            repo.fetch()
        repo.db.rollback.assert_called_once()

    def test_generic_sqlalchemy_error(self):
        class FakeRepo:
            db = MagicMock()

            @safe_db_operation("update_item")
            def update(self):
                raise SQLAlchemyError("generic")

        repo = FakeRepo()
        with pytest.raises(DatabaseOperationError):
            repo.update()
        repo.db.rollback.assert_called_once()
