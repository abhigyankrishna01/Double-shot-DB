"""
Regression tests for SQL safety bypasses that passed the original
regex + sqlparse layers because they are syntactically valid SELECTs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.sql_executor import (
    DisallowedStatementError,
    _validate_statement,
    execute_readonly_query,
)


# ── Dangerous functions inside a valid SELECT ─────────────────────────────────

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(600)",                                   # DoS: holds a connection
        "SELECT pg_sleep_for('10 minutes')",
        "SELECT PG_SLEEP (5)",                                    # case + whitespace
        "SELECT pg_catalog.pg_sleep(5)",                          # schema-qualified
        "SELECT pg_read_file('/etc/passwd')",                     # server file read
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT * FROM pg_ls_dir('.')",
        "SELECT set_config('statement_timeout', '0', false)",     # disables our timeout
        "SELECT pg_terminate_backend(123)",
        "SELECT pg_advisory_lock(1)",                             # lock DoS
        "SELECT query_to_xml('DELETE FROM orders', true, true, '')",  # executes a string
        "SELECT lo_import('/etc/passwd')",
        "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)",
        "WITH x AS (SELECT pg_sleep(5)) SELECT * FROM x",          # hidden in a CTE
    ],
)
def test_dangerous_functions_blocked(sql):
    with pytest.raises(DisallowedStatementError):
        _validate_statement(sql)


# ── Dangerous clauses ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO stolen FROM customers",         # creates a table
        "SELECT * FROM orders FOR SHARE",              # row locks
        "SELECT * FROM orders FOR KEY SHARE",
        "SELECT * FROM orders FOR NO KEY UPDATE",
    ],
)
def test_dangerous_clauses_blocked(sql):
    with pytest.raises(DisallowedStatementError):
        _validate_statement(sql)


# ── No false positives on normal analytical SQL ───────────────────────────────

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name, SUM(total) FROM orders GROUP BY name ORDER BY 2 DESC",
        "SELECT * FROM products WHERE description = 'call pg_sleep( later'",  # literal, not a call
        "SELECT * FROM logs WHERE note = 'moved INTO archive'",               # literal
        "SELECT lower(name), lpad(code, 5, '0') FROM customers",              # lo* / l* lookalikes
        "SELECT * FROM generate_series(1, 10) g",
        "WITH t AS (SELECT customer_id, COUNT(*) c FROM orders GROUP BY 1) SELECT * FROM t",
        "SELECT sleep_minutes FROM health_logs",                              # column name lookalike
        "SELECT COUNT(*) FROM events WHERE event_type = 'update'",           # keyword inside literal
        "SELECT * FROM audit WHERE action IN ('delete', 'create', 'drop')",
        "SELECT * FROM notes WHERE body = 'it''s an update'",                 # escaped quote
    ],
)
def test_normal_queries_still_pass(sql):
    _validate_statement(sql)


# ── Runtime guards are actually applied ───────────────────────────────────────

async def test_executor_sets_read_only_and_timeout():
    executed: list[str] = []

    result = MagicMock()
    result.keys.return_value = ["n"]
    result.fetchmany.return_value = [(1,)]

    session = MagicMock()

    async def _execute(stmt):
        executed.append(str(stmt))
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    settings = MagicMock(query_timeout_ms=1234)

    with patch("backend.tools.sql_executor.get_readonly_engine"), \
         patch("backend.tools.sql_executor.sessionmaker", return_value=lambda: session), \
         patch("backend.tools.sql_executor.get_settings", return_value=settings), \
         patch("backend.tools.sql_executor.query_cache.get", new=AsyncMock(return_value=None)), \
         patch("backend.tools.sql_executor.query_cache.set", new=AsyncMock()):
        rows = await execute_readonly_query("SELECT 1 AS n")

    assert rows == [{"n": 1}]
    assert executed[0] == "SET TRANSACTION READ ONLY"
    assert executed[1] == "SET LOCAL statement_timeout = 1234"
    assert executed[2].startswith("SELECT 1 AS n")
