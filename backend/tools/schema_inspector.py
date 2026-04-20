"""
Introspects the public schema — columns, types, nullability, and FK relationships —
and returns a richly formatted string for LLM prompt injection.
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.db.connection import get_readonly_engine

logger = logging.getLogger(__name__)

_COLUMNS_QUERY = """
SELECT
    t.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable
FROM information_schema.tables t
JOIN information_schema.columns c
    ON t.table_name = c.table_name
    AND t.table_schema = c.table_schema
WHERE t.table_schema = 'public'
    AND t.table_type = 'BASE TABLE'
ORDER BY t.table_name, c.ordinal_position;
"""

_FK_QUERY = """
SELECT
    tc.table_name        AS from_table,
    kcu.column_name      AS from_column,
    ccu.table_name       AS to_table,
    ccu.column_name      AS to_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema   = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
    AND tc.table_schema   = ccu.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema  = 'public'
ORDER BY tc.table_name, kcu.column_name;
"""


async def get_schema_context() -> str:
    engine = get_readonly_engine()
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        col_result = await session.execute(text(_COLUMNS_QUERY))
        col_rows = col_result.fetchall()

        fk_result = await session.execute(text(_FK_QUERY))
        fk_rows = fk_result.fetchall()

    if not col_rows:
        logger.warning("schema_inspector found no tables in public schema")
        return "No tables found in the public schema."

    # Build table → columns map
    tables: dict[str, list[str]] = {}
    for table_name, col_name, data_type, nullable in col_rows:
        tables.setdefault(table_name, [])
        null_str = "NULL" if nullable == "YES" else "NOT NULL"
        tables[table_name].append(f"  - {col_name} ({data_type}, {null_str})")

    # Build FK map: table → list of relationship strings
    fk_map: dict[str, list[str]] = {}
    for from_table, from_col, to_table, to_col in fk_rows:
        fk_map.setdefault(from_table, [])
        fk_map[from_table].append(f"  - {from_table}.{from_col} → {to_table}.{to_col}")

    parts: list[str] = []
    for table, cols in tables.items():
        block = f"Table: {table}\nColumns:\n" + "\n".join(cols)
        if table in fk_map:
            block += "\nRelationships:\n" + "\n".join(fk_map[table])
        parts.append(block)

    schema_str = "\n\n".join(parts)
    logger.info("schema_inspector built context", extra={"tables": list(tables.keys())})
    return schema_str
