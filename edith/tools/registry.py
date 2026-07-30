"""Tool schema definitions + dispatch table.

Tool functions must be pure text in/out — no print()/input() — so the
agent-core I/O contract holds. Instances are built per-session (bound to a
db connection / llm client via closures) rather than held as module globals.
"""

from typing import Callable


class ToolRegistry:
    def __init__(self) -> None:
        self._schemas: list[dict] = []
        self._dispatch: dict[str, Callable[..., str]] = {}

    def register(self, schema: dict, fn: Callable[..., str]) -> None:
        self._schemas.append(schema)
        self._dispatch[schema["function"]["name"]] = fn

    def dispatch(self, name: str, args: dict) -> str:
        fn = self._dispatch.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'"
        return fn(**args)

    def schemas(self) -> list[dict]:
        return list(self._schemas)
