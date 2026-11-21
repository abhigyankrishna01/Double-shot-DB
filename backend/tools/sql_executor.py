"""
Executes SQL using the READ-ONLY database connection exclusively.

Validation layers (defense-in-depth):
  1. Regex fast-filter — strips comments, blocks known mutation keywords
  2. sqlparse AST check — blocks DDL/non-SELECT DML at token level
  3. Function / clause denylist — blocks sleep, file access, config tampering,
     SELECT INTO and row locks, which are all valid inside a plain SELECT
  4. Auto-LIMIT injection — prevents runaway result sets
  5. Per-query guards — READ ONLY transaction + statement_timeout
  6. PostgreSQL read-only role — true enforcement boundary at the DB

Caching: successful results stored in async TTL cache (query_cache.py).
"""

import logging
import re
from typing import Any

import sqlparse
import sqlparse.tokens as T
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.config import get_settings
from backend.db.connection import get_readonly_engine
from backend.tools.query_cache import query_cache

logger = logging.getLogger(__name__)

_DISALLOWED_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|UPSERT|GRANT|REVOKE|EXECUTE|CALL)\b",
    re.IGNORECASE,
)


# Functions that are legal inside a SELECT but dangerous: DoS (sleep, locks),
# server file access, config tampering (e.g. disabling statement_timeout),
# backend control, or executing arbitrary SQL from a string.
_DANGEROUS_FUNCTIONS = (
    r"pg_sleep(_for|_until)?", r"pg_read_(binary_)?file", r"pg_ls_\w+", r"pg_stat_file",
    r"lo_\w+", r"dblink\w*", r"set_config", r"pg_terminate_backend", r"pg_cancel_backend",
    r"pg_reload_conf", r"pg_rotate_logfile", r"pg_(try_)?advisory_\w+",
    r"query_to_xml\w*", r"pg_logical_\w+", r"pg_switch_wal", r"pg_create_\w+",
)
_DANGEROUS_FUNCTION_PATTERN = re.compile(
    r"\b(" + "|".join(_DANGEROUS_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)
# SELECT ... INTO creates a table; FOR SHARE / KEY SHARE take row locks.
_DANGEROUS_CLAUSE_PATTERN = re.compile(
    r"\bINTO\b|\bFOR\s+(NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b",
    re.IGNORECASE,
)


class SQLExecutionError(Exception):
    pass


class DisallowedStatementError(SQLExecutionError):
    pass


# ── Validation ────────────────────────────────────────────────────────────────

def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)


def _validate_no_stacking(sql: str) -> None:
    """Explicit semicolon check: blocks stacked statements even if sqlparse misses them."""
    cleaned = _strip_comments(sql).strip().rstrip(";").rstrip()
    if ";" in cleaned:
        raise DisallowedStatementError(
            "Multiple SQL statements separated by ';' are not permitted."
        )


def _strip_string_literals(sql: str) -> str:
    """Blank out '...' literals so data values (e.g. status = 'update') are not
    mistaken for keywords or function calls. Literals cannot execute."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _validate_regex(sql: str) -> None:
    cleaned = _strip_string_literals(_strip_comments(sql))
    if _DISALLOWED_PATTERN.search(cleaned):
        raise DisallowedStatementError(
            "Statement contains disallowed mutation keywords. Only SELECT is permitted."
        )
    stripped = cleaned.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        raise DisallowedStatementError(
            "Only SELECT / WITH (CTE) statements are permitted."
        )


def _validate_sqlparse(sql: str) -> None:
    statements = [s for s in sqlparse.parse(sql) if s.value.strip()]

    if not statements:
        raise DisallowedStatementError("Empty SQL statement.")
    if len(statements) > 1:
        raise DisallowedStatementError(
            "Multiple SQL statements are not permitted."
        )

    stmt = statements[0]
    stmt_type = stmt.get_type()
    if stmt_type and stmt_type.upper() not in ("SELECT", "UNKNOWN"):
        raise DisallowedStatementError(
            f"Statement type '{stmt_type}' is not permitted. Only SELECT is allowed."
        )

    for token in stmt.flatten():
        if token.ttype is T.DDL:
            raise DisallowedStatementError(f"DDL token '{token.value}' rejected.")
        if token.ttype is T.DML and token.normalized.upper() not in ("SELECT",):
            raise DisallowedStatementError(f"DML token '{token.value}' rejected.")


def _validate_functions(sql: str) -> None:
    cleaned = _strip_string_literals(_strip_comments(sql))
    match = _DANGEROUS_FUNCTION_PATTERN.search(cleaned)
    if match:
        raise DisallowedStatementError(f"Function '{match.group(1)}' is not permitted.")
    match = _DANGEROUS_CLAUSE_PATTERN.search(cleaned)
    if match:
        raise DisallowedStatementError(f"Clause '{match.group(0).upper()}' is not permitted.")


def _validate_statement(sql: str) -> None:
    _validate_no_stacking(sql)   # cheapest check first
    _validate_regex(sql)
    _validate_functions(sql)
    _validate_sqlparse(sql)


# ── Query Cost Guard ──────────────────────────────────────────────────────────

def _enforce_limit(sql: str, max_rows: int) -> str:
    """
    Inject LIMIT <max_rows> if the outermost query has none.
    Uses paren-depth counting so subquery LIMITs are not mistaken for top-level.
    """
    normalized = sql.strip().rstrip(";").rstrip()

    depth = 0
    # Split on parentheses and whitespace to walk token-by-token
    for token in re.split(r"(\(|\))", normalized):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and re.match(r"^\s*LIMIT\s*$", token, re.IGNORECASE):
            return normalized  # already has a top-level LIMIT

    # Also catch "LIMIT 500" sitting at the end of the string
    if re.search(r"\bLIMIT\s+\d+\s*$", normalized, re.IGNORECASE):
        return normalized

    return f"{normalized}\nLIMIT {max_rows}"


# ── Executor ──────────────────────────────────────────────────────────────────

async def execute_readonly_query(sql: str, max_rows: int = 500) -> list[dict[str, Any]]:
    """
    Validate, limit-enforce, cache-check, then execute a SELECT against the
    read-only engine. Returns rows as dicts.
    """
    _validate_statement(sql)
    sql = _enforce_limit(sql, max_rows)

    cached = await query_cache.get(sql)
    if cached is not None:
        logger.info("query_cache_hit", extra={"sql_preview": sql[:120]})
        return cached

    engine: AsyncEngine = get_readonly_engine()
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            logger.info("executing_query", extra={"sql_preview": sql[:120]})
            # Per-transaction guards. SET LOCAL works through poolers like
            # PgBouncer/Neon, unlike connection-level server_settings.
            timeout_ms = int(get_settings().query_timeout_ms)
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            result = await session.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows)
            data = [dict(zip(columns, row)) for row in rows]
            logger.info("query_success", extra={"row_count": len(data)})
            await query_cache.set(sql, data)
            return data
        except DisallowedStatementError:
            raise
        except Exception as exc:
            logger.error("query_failed", extra={"error": str(exc), "sql_preview": sql[:120]})
            raise SQLExecutionError(f"Query execution failed: {exc}") from exc
