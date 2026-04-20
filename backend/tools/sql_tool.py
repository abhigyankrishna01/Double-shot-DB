"""
SQLQueryTool: wraps execute_readonly_query behind the BaseTool interface.
Registered in the tool registry at import time so agents can look it up by name.
"""

from pydantic import Field
from backend.tools.base import BaseTool, ToolInput, ToolOutput, tool_registry
from backend.tools.sql_executor import execute_readonly_query, SQLExecutionError


class SQLQueryInput(ToolInput):
    sql: str = Field(..., description="A valid PostgreSQL SELECT query")


class SQLQueryTool(BaseTool):
    name = "sql_query"
    description = (
        "Execute a read-only SQL SELECT query against the PostgreSQL database. "
        "Returns rows as a list of dicts. Raises on mutation attempts."
    )

    async def run(self, input: SQLQueryInput) -> ToolOutput:  # type: ignore[override]
        try:
            data = await execute_readonly_query(input.sql)
            return ToolOutput(success=True, data=data)
        except SQLExecutionError as exc:
            return ToolOutput(success=False, data=[], error=str(exc))


# Auto-register on import
tool_registry.register(SQLQueryTool())
