"""Unit tests for sql_executor validation and limit-injection logic."""

import pytest
from backend.tools.sql_executor import (
    DisallowedStatementError,
    _enforce_limit,
    _validate_no_stacking,
    _validate_regex,
    _validate_sqlparse,
    _validate_statement,
)


# ── _validate_no_stacking ─────────────────────────────────────────────────────

class TestValidateNoStacking:
    def test_clean_select_passes(self):
        _validate_no_stacking("SELECT * FROM orders")

    def test_trailing_semicolon_is_stripped(self):
        _validate_no_stacking("SELECT * FROM orders;")

    def test_stacked_drop_blocked(self):
        with pytest.raises(DisallowedStatementError, match="Multiple SQL statements"):
            _validate_no_stacking("SELECT 1; DROP TABLE orders")

    def test_stacked_select_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_no_stacking("SELECT 1; SELECT 2")

    def test_semicolon_inside_comment_is_stripped_first(self):
        # comment containing ';' should be stripped before the check
        _validate_no_stacking("SELECT id FROM orders -- filter; here")

    def test_cte_passes(self):
        _validate_no_stacking(
            "WITH cte AS (SELECT id FROM orders) SELECT * FROM cte"
        )


# ── _validate_regex ───────────────────────────────────────────────────────────

class TestValidateRegex:
    def test_select_passes(self):
        _validate_regex("SELECT * FROM orders")

    def test_cte_passes(self):
        _validate_regex("WITH t AS (SELECT 1) SELECT * FROM t")

    def test_drop_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("DROP TABLE orders")

    def test_delete_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("DELETE FROM orders WHERE 1=1")

    def test_insert_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("INSERT INTO orders VALUES (1, 2)")

    def test_truncate_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("TRUNCATE TABLE orders")

    def test_alter_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("ALTER TABLE orders ADD COLUMN foo INT")

    def test_update_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("UPDATE orders SET status='x'")

    def test_non_select_non_with_blocked(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("EXPLAIN SELECT * FROM orders")

    def test_case_insensitive_blocking(self):
        with pytest.raises(DisallowedStatementError):
            _validate_regex("drop table orders")


# ── _validate_sqlparse ────────────────────────────────────────────────────────

class TestValidateSqlparse:
    def test_select_passes(self):
        _validate_sqlparse("SELECT id FROM orders")

    def test_empty_blocked(self):
        with pytest.raises(DisallowedStatementError, match="[Ee]mpty"):
            _validate_sqlparse("   ")

    def test_multiple_statements_blocked(self):
        with pytest.raises(DisallowedStatementError, match="[Mm]ultiple"):
            _validate_sqlparse("SELECT 1; SELECT 2")

    def test_ddl_token_blocked(self):
        with pytest.raises(DisallowedStatementError, match="DDL"):
            _validate_sqlparse("CREATE TABLE foo (id INT)")

    def test_cte_passes(self):
        _validate_sqlparse(
            "WITH cte AS (SELECT id FROM orders) SELECT * FROM cte"
        )


# ── _validate_statement (full pipeline) ──────────────────────────────────────

class TestValidateStatement:
    def test_valid_select(self):
        _validate_statement("SELECT * FROM customers LIMIT 10")

    def test_stacking_caught_first(self):
        with pytest.raises(DisallowedStatementError):
            _validate_statement("SELECT 1; DROP TABLE customers")


# ── _enforce_limit ────────────────────────────────────────────────────────────

class TestEnforceLimit:
    def test_adds_limit_when_missing(self):
        result = _enforce_limit("SELECT * FROM orders", max_rows=100)
        assert "LIMIT 100" in result

    def test_does_not_add_when_already_present(self):
        sql = "SELECT * FROM orders LIMIT 50"
        result = _enforce_limit(sql, max_rows=500)
        assert result.count("LIMIT") == 1
        assert "LIMIT 50" in result

    def test_strips_trailing_semicolon(self):
        result = _enforce_limit("SELECT * FROM orders;", max_rows=100)
        assert result.rstrip().endswith("LIMIT 100")

    def test_does_not_confuse_subquery_limit(self):
        # Outer query has no LIMIT — one should be added even though the subquery has one
        sql = "SELECT * FROM (SELECT id FROM orders LIMIT 10) sub"
        result = _enforce_limit(sql, max_rows=500)
        assert result.count("LIMIT") == 2

    def test_cte_gets_limit(self):
        sql = "WITH cte AS (SELECT id FROM orders) SELECT * FROM cte"
        result = _enforce_limit(sql, max_rows=200)
        assert "LIMIT 200" in result
