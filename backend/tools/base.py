"""
Tool abstraction layer.
New tools (CSV reader, REST API, vector search, etc.) implement BaseTool
and register with the tool registry — no changes to agent code needed.
"""

from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel


class ToolInput(BaseModel):
    pass


class ToolOutput(BaseModel):
    success: bool
    data: Any
    error: str = ""


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, input: ToolInput) -> ToolOutput: ...

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


# ── Tool Registry ─────────────────────────────────────────────────────────────

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(self._tools)}")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())


tool_registry = ToolRegistry()
